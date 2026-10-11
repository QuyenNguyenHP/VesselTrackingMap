import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import websockets
from dotenv import load_dotenv

from .database import connect, initialize

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("ais-collector")
URL = "wss://stream.aisstream.io/v0/stream"


def registered_mmsis() -> list[str]:
    with connect() as conn:
        return [row[0] for row in conn.execute("SELECT mmsi FROM vessels")]


def store(message: dict) -> bool:
    if message.get("MessageType") != "PositionReport":
        return False
    meta = message.get("MetaData", {})
    report = message.get("Message", {}).get("PositionReport", {})
    mmsi = str(meta.get("MMSI", report.get("UserID", "")))
    lat, lon = report.get("Latitude"), report.get("Longitude")
    if not mmsi or not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return False
    now = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        known = conn.execute("SELECT 1 FROM vessels WHERE mmsi=?", (mmsi,)).fetchone()
        if not known:
            return False
        conn.execute("INSERT INTO positions (mmsi,lat,lon,speed,course,source_at,received_at) VALUES (?,?,?,?,?,?,?)", (mmsi, lat, lon, report.get("Sog"), report.get("Cog"), meta.get("time_utc"), now))
    return True


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


async def main() -> None:
    initialize()
    key = os.getenv("AISSTREAM_API_KEY", "").strip()
    if not key:
        raise SystemExit("AISSTREAM_API_KEY is missing")
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


if __name__ == "__main__":
    asyncio.run(main())

