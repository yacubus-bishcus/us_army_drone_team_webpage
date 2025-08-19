import csv
from pathlib import Path

DATA_FILE = Path.cwd() / "instance" / "uas.csv"

def _norm(row):
    # Map CSV headers -> template keys
    return {
        "id": row.get("id") or row.get("ID"),
        "name": row.get("drone name") or row.get("name") or row.get("UAS Name"),
        "company": row.get("drone company") or row.get("company"),
        "range": row.get("range"),
        "endurance": row.get("endurance"),
        "ceiling": row.get("ceiling"),
        "payload_capacity": row.get("payload capacity") or row.get("payload"),
        "camera_system": row.get("camera system") or row.get("camera"),
        "max_speed": row.get("max speed") or row.get("speed"),
        "weight": row.get("weight"),
        "price": row.get("price") or row.get("price per unit"),
        "notes": row.get("notes") or "",
    }

def get_all_uas():
    with open(DATA_FILE, newline="", encoding="utf-8") as f:
        return [_norm(r) for r in csv.DictReader(f)]

def get_uas_by_ids(ids):
    ids = set(ids or [])
    return [u for u in get_all_uas() if u["id"] in ids]
