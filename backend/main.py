import hmac
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .database import connect, initialize

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")


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


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize()
    yield


app = FastAPI(title="DRUMS Fleet Tracking", version="1.0.0", lifespan=lifespan)


@app.get("/api/health")
def health():
    return {"status": "ok"}


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

