# Vessel Finder

A simple Ubuntu web app that looks up a vessel by IMO number and displays its information and latest available AIS position on a Leaflet map.

The FastAPI backend also serves the frontend, so only one application process is required.

## Setup

```bash
cd /home/daikai/VesselTrackingMap
sudo apt update
sudo apt install -y python3-venv
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Create an API key at [VesselAPI](https://dashboard.vesselapi.com/) and add it to `.env`:

```dotenv
VESSEL_API_KEY=your_vesselapi_key_here
```

`AISSTREAM_API_KEY` is not required for the simple IMO search. AISStream cannot search directly by IMO; it streams new AIS messages using MMSI filters.

OpenWaters is used as a free fallback for positions heard in the last 30 minutes. The collector polls it every five minutes by default and stores positions for registered vessels. Override the interval with `OPENWATERS_POLL_SECONDS` (minimum 60).

## Run

```bash
cd /home/daikai/VesselTrackingMap
.venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8011
```

Open [http://localhost:8011](http://localhost:8011), enter a valid seven-digit IMO number, and select **Search**.

The API endpoint used by the frontend is:

```text
GET /api/lookup/{imo}
```

## Notes

- Vessel positions depend on terrestrial AIS coverage and may not be current or available.
- Keep the API key in `.env`; never put it in frontend JavaScript or commit it to Git.
- The included OpenStreetMap tiles are appropriate for light usage. Review the tile policy before production use.
