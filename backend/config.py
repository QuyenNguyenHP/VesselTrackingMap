import json
import os
import tempfile
from pathlib import Path

CONFIG_PATH = Path(os.getenv("CONFIG_PATH", str(Path(__file__).resolve().parent.parent / "config.json")))


def load_config():
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("vessels"), list):
        raise ValueError("config.json must contain a vessels array")
    seen = set()
    for vessel in data["vessels"]:
        mmsi = vessel.get("mmsi") if isinstance(vessel, dict) else None
        if not isinstance(mmsi, str) or len(mmsi) != 9 or not mmsi.isascii() or not mmsi.isdigit():
            raise ValueError("Each vessel needs a nine-digit MMSI string")
        if mmsi in seen:
            raise ValueError("Duplicate MMSI in config.json")
        seen.add(mmsi)
    return data


def save_config(data):
    # Replace atomically so readers never see a partially written JSON file.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=CONFIG_PATH.parent, delete=False) as stream:
            temporary = stream.name
            json.dump(data, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, CONFIG_PATH)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
