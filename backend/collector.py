import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import websockets
from dotenv import load_dotenv

from .database import connect, initialize

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("ais-collector")
URL = "wss://stream.aisstream.io/v0/stream"
OPENWATERS_API_BASE_URL = os.getenv("OPENWATERS_API_BASE_URL", "https://ais.openwaters.io/v1").rstrip("/")
OPENWATERS_POLL_SECONDS = max(60, int(os.getenv("OPENWATERS_POLL_SECONDS", "300")))


def registered_mmsis() -> list[str]:
    with connect() as conn:
        return [row[0] for row in conn.execute("SELECT mmsi FROM vessels")]


def store_position(mmsi: str, lat, lon, speed=None, course=None, source_at=None) -> bool:
    if not mmsi or not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return False
    now = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        known = conn.execute("SELECT 1 FROM vessels WHERE mmsi=?", (mmsi,)).fetchone()
        if not known:
            return False
        latest = conn.execute("SELECT source_at FROM positions WHERE mmsi=? ORDER BY id DESC LIMIT 1", (mmsi,)).fetchone()
        if latest and source_at and latest["source_at"] == source_at:
            return False
        conn.execute("INSERT INTO positions (mmsi,lat,lon,speed,course,source_at,received_at) VALUES (?,?,?,?,?,?,?)", (mmsi, lat, lon, speed, course, source_at, now))
    return True


def store(message: dict) -> bool:
    if message.get("MessageType") != "PositionReport":
        return False
    meta = message.get("MetaData", {})
    report = message.get("Message", {}).get("PositionReport", {})
    return store_position(
        str(meta.get("MMSI", report.get("UserID", ""))),
        report.get("Latitude"),
        report.get("Longitude"),
        report.get("Sog"),
        report.get("Cog"),
        meta.get("time_utc"),
    )


def fetch_openwaters() -> int:
    mmsis = registered_mmsis()
    if not mmsis:
        return 0
    request = Request(
        f"{OPENWATERS_API_BASE_URL}/vessels?{urlencode({'mmsi': ','.join(mmsis)})}",
        headers={"Accept": "application/geo+json, application/json"},
    )
    with urlopen(request, timeout=20) as response:
        features = json.load(response).get("features", [])
    stored = 0
    for feature in features:
        properties = feature.get("properties", {})
        coordinates = feature.get("geometry", {}).get("coordinates", [])
        if len(coordinates) < 2:
            continue
        lon, lat = coordinates[:2]
        stored += store_position(
            str(properties.get("mmsi", "")), lat, lon,
            properties.get("sog"), properties.get("cog"), properties.get("seen"),
        )
    return stored


async def openwaters_loop() -> None:
    while True:
        try:
            stored = await asyncio.to_thread(fetch_openwaters)
            LOG.info("OpenWaters poll stored %d new position(s)", stored)
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            LOG.warning("OpenWaters poll failed: %s", exc)
        await asyncio.sleep(OPENWATERS_POLL_SECONDS)


def prune() -> None:
    days = max(1, int(os.getenv("POSITION_RETENTION_DAYS", "90")))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with connect() as conn:
        conn.execute("DELETE FROM positions WHERE received_at < ?", (cutoff,))


async def collect_once(key: str) -> None:
    mmsis = registered_mmsis()
    if not mmsis:
        LOG.info("No vessels registered; checking again in 30 seconds")
        await asyncio.sleep(30)
        return
    subscription = {"APIKey": key, "BoundingBoxes": [[[-90, -180], [90, 180]]], "FiltersShipMMSI": mmsis, "FilterMessageTypes": ["PositionReport"]}
    LOG.info("Connecting with %d registered MMSI(s)", len(mmsis))
    async with websockets.connect(URL, ping_interval=20, ping_timeout=20, open_timeout=30) as socket:
        await socket.send(json.dumps(subscription))
        while True:
            raw = await asyncio.wait_for(socket.recv(), timeout=300)
            store(json.loads(raw))


async def aisstream_loop(key: str) -> None:
    delay = 2
    while True:
        try:
            prune()
            await collect_once(key)
            delay = 2
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOG.warning("Collector disconnected: %s; retrying in %ds", exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)


async def main() -> None:
    initialize()
    key = os.getenv("AISSTREAM_API_KEY", "").strip()
    tasks = [openwaters_loop()]
    if key:
        tasks.append(aisstream_loop(key))
    else:
        LOG.warning("AISSTREAM_API_KEY is missing; running OpenWaters polling only")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())

