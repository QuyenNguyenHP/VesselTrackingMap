# DRUMS Fleet Tracking

Self-hosted AIS vessel map using FastAPI, SQLite, AISStream, and Leaflet. Free AIS coverage is best-effort, so the dashboard displays when each position was last received.

## Run directly on Windows (no Docker)

You need Python 3.11 or newer, an [AISStream](https://aisstream.io/) API key, and verified IMO/MMSI pairs.

### 1. Open PowerShell in the project

```powershell
Set-Location -LiteralPath 'C:\Users\DAIKAI VR\Desktop\Githup Repo\Vessel tracking Map'
python --version
```

### 2. Create the Python environment

Run this once:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

These commands call the environment's Python directly, so changing the PowerShell execution policy is unnecessary.

### 3. Configure the application

```powershell
notepad .env
```

Set the following values and save it:

```dotenv
AISSTREAM_API_KEY=YOUR_REAL_AISSTREAM_API_KEY
ADMIN_API_KEY=USE_A_LONG_RANDOM_SECRET_HERE
DATABASE_PATH=fleet.db
POSITION_RETENTION_DAYS=90
```

Generate a secure admin key if needed:

```powershell
$bytes = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
[Convert]::ToHexString($bytes)
```

Copy the result into `ADMIN_API_KEY`. Do not share or commit `.env`.

### 4. Start the API and dashboard (terminal 1)

```powershell
Set-Location -LiteralPath 'C:\Users\DAIKAI VR\Desktop\Githup Repo\Vessel tracking Map'
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8011
```

Leave this terminal open. Open [http://localhost:8011](http://localhost:8011), or launch it from another terminal:

```powershell
Start-Process 'http://localhost:8011'
Invoke-RestMethod 'http://localhost:8011/api/health'
```

The expected health result is `status : ok`.

### 5. Start the AIS collector (terminal 2)

Open a second PowerShell terminal:

```powershell
Set-Location -LiteralPath 'C:\Users\DAIKAI VR\Desktop\Githup Repo\Vessel tracking Map'
.\.venv\Scripts\python.exe -m backend.collector
```

Leave this terminal open too. It shows AISStream connection and reconnection messages. A message saying no vessels are registered is normal initially.

### 6. Register a vessel (terminal 3)

Replace the placeholders with verified vessel information and use the same admin key stored in `.env`:

```powershell
$adminKey = 'YOUR_ADMIN_API_KEY'
$headers = @{ 'X-API-Key' = $adminKey }
$body = @{
    imo           = 'VALID_7_DIGIT_IMO'
    mmsi          = 'VALID_9_DIGIT_MMSI'
    name          = 'VESSEL NAME'
    drums_ship_id = 'https://drums.example/ship/123'
} | ConvertTo-Json

Invoke-RestMethod `
    -Method Post `
    -Uri 'http://localhost:8011/api/vessels' `
    -Headers $headers `
    -ContentType 'application/json' `
    -Body $body
```

The IMO must have seven digits and a valid checksum. The MMSI must have exactly nine digits. `drums_ship_id` is optional and can contain the full DRUMS dashboard URL.

After registering vessels, stop the collector with `Ctrl+C` and run it again to subscribe to the updated MMSI list immediately. An idle collector otherwise checks the registry again after 30 seconds.

AISStream provides live messages rather than an immediate position lookup. A map marker appears only after a new AIS position is broadcast for that MMSI.

### Stop and restart

Press `Ctrl+C` in the API and collector terminals to stop them. To restart later, repeat steps 4 and 5. The `fleet.db` SQLite file retains vessels and position history.

Do not delete `fleet.db`, `fleet.db-shm`, or `fleet.db-wal` unless you intend to erase stored data.

### Access from another computer

Find this computer's IPv4 address with `ipconfig`. On another device on the same trusted network, browse to `http://WINDOWS_PC_IP:8011`. If blocked, allow inbound TCP port 8011 in Windows Firewall for the private network profile only.

Terminal processes stop when their windows close or the user signs out. For unattended production use, run them as Windows services with a service manager such as NSSM and place an authenticated HTTPS reverse proxy in front of the application.

## Useful API commands

```powershell
# List vessels
Invoke-RestMethod 'http://localhost:8011/api/vessels'

# View track history
Invoke-RestMethod 'http://localhost:8011/api/vessels/IMO_NUMBER/history'

# Delete a vessel and its stored positions
$headers = @{ 'X-API-Key' = 'YOUR_ADMIN_API_KEY' }
Invoke-RestMethod -Method Delete -Uri 'http://localhost:8011/api/vessels/IMO_NUMBER' -Headers $headers
```

## Optional Docker deployment

Docker is not required. If preferred later, configure `.env` and run:

```powershell
docker compose up -d --build
docker compose ps
```

Compose overrides `DATABASE_PATH` so SQLite data is kept in its persistent Docker volume.

## Production notes

- Protect the dashboard with the DRUMS login or an authenticated reverse proxy before internet exposure.
- Use HTTPS for remote access.
- Do not present AIS positions as guaranteed real-time navigation data.
- OpenStreetMap public tiles are appropriate for light usage; review its tile policy before significant production traffic.
