import hmac
import json
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .database import connect, initialize

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")
VESSEL_API_KEY = os.getenv("VESSEL_API_KEY", "").strip()
VESSEL_API_BASE_URL = os.getenv("VESSEL_API_BASE_URL", "https://api.vesselapi.com/v1").rstrip("/")


def valid_imo(value: str) -> bool:
    return len(value) == 7 and value.isdigit() and sum(int(n) * w for n, w in zip(value[:6], range(7, 1, -1))) % 10 == int(value[-1])


class VesselIn(BaseModel):
    imo: str
    mmsi: str
    name: str = Field(min_length=1, max_length=120)
    drums_ship_id: str | None = Field(default=None, max_length=200)

    @field_validator("imo")
    @classmethod
    def check_imo(cls, value: str) -> str:
        value = value.strip()
        if not valid_imo(value):
            raise ValueError("IMO must be seven digits with a valid checksum")
        return value

    @field_validator("mmsi")
    @classmethod
    def check_mmsi(cls, value: str) -> str:
        value = value.strip()
        if len(value) != 9 or not value.isdigit():
            raise ValueError("MMSI must contain exactly nine digits")
        return value


def require_admin(x_api_key: str | None = Header(default=None)) -> None:
    if not ADMIN_API_KEY or not x_api_key or not hmac.compare_digest(x_api_key, ADMIN_API_KEY):
        raise HTTPException(401, "A valid X-API-Key header is required")


def vessel_api_get(path: str, **params) -> dict:
    if not VESSEL_API_KEY:
        raise HTTPException(503, "VESSEL_API_KEY is not configured in .env")
    request = Request(
        f"{VESSEL_API_BASE_URL}{path}?{urlencode(params)}",
        headers={"Authorization": f"Bearer {VESSEL_API_KEY}", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.load(response)
    except HTTPError as exc:
        try:
            error_body = json.load(exc)
            detail = error_body.get("message") or error_body.get("detail")
        except Exception:
            detail = None
        if exc.code == 404:
            raise HTTPException(404, detail or "No vessel or recent AIS position was found for this IMO")
        if exc.code in (401, 403):
            raise HTTPException(502, "The vessel-data API rejected the configured API key")
        if exc.code == 429:
            raise HTTPException(429, "The vessel-data API rate limit has been reached")
        raise HTTPException(502, detail or f"Vessel-data API returned HTTP {exc.code}")
    except (URLError, TimeoutError):
        raise HTTPException(502, "Could not connect to the vessel-data API")


def parse_api_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def find_historical_position(imo: str) -> dict:
    now = datetime.now(timezone.utc)
    newer_boundary = now - timedelta(hours=80)
    # Search newest windows first so the first result is the nearest known fix.
    for days_back in (30, 180, 365, 1825):
        older_boundary = now - timedelta(days=days_back)
        response = vessel_api_get(
            "/vessels/positions",
            **{
                "filter.ids": imo,
                "filter.idType": "imo",
                "time.from": older_boundary.isoformat().replace("+00:00", "Z"),
                "time.to": newer_boundary.isoformat().replace("+00:00", "Z"),
                "pagination.limit": 50,
            },
        )
        positions = response.get("vesselPositions", [])
        if positions:
            return max(
                positions,
                key=lambda item: parse_api_time(item.get("timestamp") or item.get("processed_timestamp"))
                or datetime.min.replace(tzinfo=timezone.utc),
            )
        newer_boundary = older_boundary
    return {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize()
    yield


app = FastAPI(title="DRUMS Fleet Tracking", version="1.0.0", lifespan=lifespan)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/lookup/{imo}")
def lookup_vessel(imo: str):
    imo = imo.strip()
    if not valid_imo(imo):
        raise HTTPException(422, "Enter a valid seven-digit IMO number")

    info_response = vessel_api_get(f"/vessel/{imo}", **{"filter.idType": "imo"})
    vessel = info_response.get("vessel", info_response)

    historical = False
    try:
        position_response = vessel_api_get(f"/vessel/{imo}/position", **{"filter.idType": "imo"})
        position = position_response.get("position", position_response)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        position = find_historical_position(imo)
        historical = bool(position)

    lat = position.get("latitude")
    lon = position.get("longitude")
    if lat is None or lon is None:
        coordinates = position.get("location", {}).get("coordinates", [])
        if len(coordinates) >= 2:
            lon, lat = coordinates[:2]
    return {
        "provider": "VesselAPI",
        "imo": str(vessel.get("imo") or position.get("imo") or imo),
        "mmsi": str(vessel.get("mmsi") or position.get("mmsi") or ""),
        "name": vessel.get("name") or position.get("vessel_name") or "Unknown vessel",
        "vessel_type": vessel.get("vessel_type"),
        "flag": vessel.get("country"),
        "call_sign": vessel.get("call_sign"),
        "year_built": vessel.get("year_built"),
        "length": vessel.get("length"),
        "breadth": vessel.get("breadth"),
        "latitude": lat,
        "longitude": lon,
        "position_available": lat is not None and lon is not None,
        "speed": position.get("sog"),
        "course": position.get("cog"),
        "heading": position.get("heading"),
        "nav_status": position.get("nav_status"),
        "timestamp": position.get("timestamp") or position.get("processed_timestamp"),
        "historical": historical,
    }


@app.post("/api/vessels", status_code=201, dependencies=[Depends(require_admin)])
def create_vessel(vessel: VesselIn):
    try:
        with connect() as conn:
            conn.execute("INSERT INTO vessels (imo,mmsi,name,drums_ship_id) VALUES (?,?,?,?)", (vessel.imo, vessel.mmsi, vessel.name.strip(), vessel.drums_ship_id))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "IMO or MMSI already exists")
    return {"status": "created", "imo": vessel.imo}


@app.get("/api/vessels")
def list_vessels():
    with connect() as conn:
        rows = conn.execute("""
            SELECT v.*, p.lat, p.lon, p.speed, p.course, p.source_at, p.received_at
            FROM vessels v LEFT JOIN positions p ON p.id =
              (SELECT id FROM positions WHERE mmsi=v.mmsi ORDER BY id DESC LIMIT 1)
            ORDER BY v.name COLLATE NOCASE
        """).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/vessels/{imo}/history")
def vessel_history(imo: str, limit: int = Query(500, ge=1, le=2000)):
    with connect() as conn:
        vessel = conn.execute("SELECT mmsi FROM vessels WHERE imo=?", (imo,)).fetchone()
        if not vessel:
            raise HTTPException(404, "Vessel not found")
        rows = conn.execute("SELECT lat,lon,speed,course,source_at,received_at FROM positions WHERE mmsi=? ORDER BY id DESC LIMIT ?", (vessel["mmsi"], limit)).fetchall()
    return [dict(row) for row in reversed(rows)]


@app.delete("/api/vessels/{imo}", status_code=204, dependencies=[Depends(require_admin)])
def delete_vessel(imo: str):
    with connect() as conn:
        cursor = conn.execute("DELETE FROM vessels WHERE imo=?", (imo,))
        if cursor.rowcount == 0:
            raise HTTPException(404, "Vessel not found")


app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    candidate = (FRONTEND / path).resolve()
    if path and candidate.is_relative_to(FRONTEND.resolve()) and candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(FRONTEND / "index.html")

