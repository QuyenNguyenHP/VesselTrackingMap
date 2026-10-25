# OpenWaters Vessel Tracking

A FastAPI app that monitors configured vessels using OpenWaters only and shows their latest known locations on a Leaflet map. No provider API key is required by this implementation.

## Configure vessels

Edit `config.json` in the project root. The initial list is empty; add the real MMSI numbers of the vessels you want to monitor:

```json
{
  "vessels": [
    {
      "mmsi": "123456789",
      "imo": "1234567",
      "name": "Replace with your vessel",
      "enabled": true
    }
  ]
}
```

The identifiers above are placeholders. MMSI must be a unique nine-digit string. IMO and name are optional; IMO is used only for local search. Set `enabled` to false to pause monitoring. Changes are read on the next poll without restarting.

The app polls immediately on startup and every **300 seconds (five minutes)** thereafter, requesting `/vessels?mmsi=...` from `https://ais.openwaters.io/v1`. It saves the latest returned location under each vessel's `position` in the same `config.json`:

```json
"position": {
  "latitude": 1.3,
  "longitude": 103.8,
  "speed": 12.4,
  "course": 90,
  "timestamp": "2026-10-24T06:00:00Z",
  "received_at": "2026-10-24T06:01:00+00:00",
  "provider": "OpenWaters"
}
```

`timestamp` is the provider's observation time; `received_at` is when the app saved the report. `last_checked_at` and top-level `last_poll_at` record successful checks, even when no position is returned. Missing reports and failed requests preserve the previous location. Polling every five minutes does not guarantee a new AIS observation every five minutes.

Only the latest position is saved, not a route history. Writes use atomic file replacement. Stop the app before manually editing if you need to avoid any chance of concurrent edits. Run only one app worker/instance per config file.

## Run locally

```bash
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell instead:
# .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8011
```

Open http://localhost:8011. Monitoring starts automatically with the web app. Search configured vessels by MMSI or IMO. The map refreshes saved data every minute.

Optional environment variables: `CONFIG_PATH` (defaults to the project-root config.json) and `OPENWATERS_API_BASE_URL`. Set these in the process environment; `.env` is not loaded automatically.

## Docker

```bash
docker compose up --build -d
```

Compose mounts the project directory at `/data` so updates persist to the host's `config.json`. A directory mount allows atomic replacement of the file. No separate collector service or database is needed.

## API

- `GET /api/vessels`: enabled vessels and latest saved locations.
- `GET /api/lookup/{mmsi_or_imo}`: one configured vessel.
- `GET /api/health`: process health (does not imply provider availability).

Vessel configuration is managed through the JSON file. The former database registration and history endpoints are no longer used.
