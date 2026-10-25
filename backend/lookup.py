import json
import math
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import HTTPException

from .collector import BASE_URL


def lookup_openwaters(identifier):
    if not re.fullmatch(r"[0-9]{9}", identifier):
        raise HTTPException(400, "Enter a 9-digit MMSI.")
    headers = {"Accept": "application/geo+json, application/json"}
    request = Request(f"{BASE_URL}/vessels/{identifier}", headers=headers)
    try:
        with urlopen(request, timeout=20) as response:
            feature = json.load(response)
    except HTTPError as exc:
        messages = {
            404: (404, "No vessel found in OpenWaters for this identifier."),
            401: (503, "OpenWaters lookup is temporarily unavailable."),
            403: (503, "OpenWaters lookup is temporarily unavailable."),
            429: (429, "OpenWaters request limit reached. Please try again shortly."),
        }
        status, detail = messages.get(exc.code, (502, "OpenWaters lookup is temporarily unavailable."))
        raise HTTPException(status, detail) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise HTTPException(503, "Cannot reach OpenWaters. Please try again shortly.") from exc
    except ValueError as exc:
        raise HTTPException(502, "OpenWaters returned an invalid response.") from exc

    if not isinstance(feature, dict) or feature.get("type") != "Feature":
        raise HTTPException(502, "OpenWaters returned an invalid vessel response.")
    properties = feature.get("properties") or {}
    mmsi = str(properties.get("mmsi", ""))
    if not re.fullmatch(r"[0-9]{9}", mmsi) or mmsi != identifier:
        raise HTTPException(502, "OpenWaters returned a different vessel identifier.")
    coordinates = (feature.get("geometry") or {}).get("coordinates") or []
    position = None
    if len(coordinates) >= 2:
        lon, lat = coordinates[:2]
        if all(not isinstance(n, bool) and isinstance(n, (int, float)) and math.isfinite(n) for n in (lat, lon)) and -90 <= lat <= 90 and -180 <= lon <= 180:
            position = {"latitude": lat, "longitude": lon, "speed": properties.get("sog"), "course": properties.get("cog"), "timestamp": properties.get("seen")}
    return {"mmsi": mmsi, "imo": properties.get("imo"), "name": properties.get("name"), "position": position, "lookup_source": "remote"}
