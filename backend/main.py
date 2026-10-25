import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .collector import openwaters_loop
from .config import load_config

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app):
    load_config()
    task = asyncio.create_task(openwaters_loop())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="OpenWaters Vessel Tracking", lifespan=lifespan)


def vessel_result(vessel):
    position = vessel.get("position") or {}
    return {
        **vessel, **position,
        "provider": "OpenWaters",
        "position_available": position.get("latitude") is not None and position.get("longitude") is not None,
        "historical": True,
    }


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/vessels")
def list_vessels():
    return [vessel_result(v) for v in load_config()["vessels"] if v.get("enabled", True)]


@app.get("/api/lookup/{identifier}")
def lookup_vessel(identifier: str):
    for vessel in list_vessels():
        if identifier in (vessel["mmsi"], str(vessel.get("imo", ""))):
            return vessel
    raise HTTPException(404, "Vessel is not monitored. Add its MMSI to config.json.")


app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")


@app.get("/", include_in_schema=False)
def frontend():
    return FileResponse(FRONTEND / "index.html")
