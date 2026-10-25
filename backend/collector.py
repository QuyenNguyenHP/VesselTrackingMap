import asyncio
import json
import logging
import math
import os
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import load_config, save_config

LOG = logging.getLogger(__name__)
POLL_SECONDS = 300
OPENWATERS_BATCH_SIZE = 6
BASE_URL = os.getenv("OPENWATERS_API_BASE_URL", "https://ais.openwaters.io/v1").rstrip("/")


def fetch_openwaters():
    config = load_config()
    requested = {v["mmsi"] for v in config["vessels"] if v.get("enabled", True)}
    if not requested:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    positions = {}
    requested_list = sorted(requested)
    for offset in range(0, len(requested_list), OPENWATERS_BATCH_SIZE):
        batch = requested_list[offset:offset + OPENWATERS_BATCH_SIZE]
        request = Request(
            f"{BASE_URL}/vessels?{urlencode({'mmsi': ','.join(batch)})}",
            headers={"Accept": "application/geo+json, application/json"},
        )
        with urlopen(request, timeout=20) as response:
            payload = json.load(response)
        for feature in payload.get("features", []):
            properties = feature.get("properties") or {}
            coordinates = (feature.get("geometry") or {}).get("coordinates") or []
            mmsi = str(properties.get("mmsi", ""))
            if mmsi not in requested or len(coordinates) < 2:
                continue
            lon, lat = coordinates[:2]
            if any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) for n in (lat, lon)):
                continue
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            positions[mmsi] = {
                "latitude": lat, "longitude": lon,
                "speed": properties.get("sog"), "course": properties.get("cog"),
                "timestamp": properties.get("seen"), "received_at": now,
                "provider": "OpenWaters",
            }
    # Reload after the request to preserve developer changes made during network I/O.
    config = load_config()
    stored = 0
    for vessel in config["vessels"]:
        mmsi = vessel["mmsi"]
        if mmsi not in requested or not vessel.get("enabled", True):
            continue
        vessel["last_checked_at"] = now
        if mmsi in positions:
            vessel["position"] = positions[mmsi]
            stored += 1
    config["last_poll_at"] = now
    save_config(config)
    return stored


async def openwaters_loop():
    while True:
        started = asyncio.get_running_loop().time()
        try:
            stored = await asyncio.to_thread(fetch_openwaters)
            LOG.info("OpenWaters updated %d vessel positions", stored)
        except Exception:
            LOG.exception("OpenWaters poll failed; retaining saved positions")
        elapsed = asyncio.get_running_loop().time() - started
        await asyncio.sleep(max(0, POLL_SECONDS - elapsed))
