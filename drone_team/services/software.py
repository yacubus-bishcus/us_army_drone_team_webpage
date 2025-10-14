# drone_team/services/software.py
from pathlib import Path
import csv
from typing import List, Dict, Any  # <-- add this

CAD_HEADERS = [
    "id", "display_name", "category", "tags", "description",
    "stored_filename", "ext", "size_bytes",
    "uploaded_by", "uploaded_at"
]

def _data_dir(app) -> Path:
    base = Path(app.config.get("DATA_DIR", app.instance_path)) / "data"
    base.mkdir(parents=True, exist_ok=True)
    return base

def _files_root(app) -> Path:
    root = Path(app.config.get("DATA_DIR", app.instance_path)) / "files"
    root.mkdir(parents=True, exist_ok=True)
    return root

def cad_dir(app) -> Path:
    d = _files_root(app) / "cad"
    d.mkdir(parents=True, exist_ok=True)
    return d

def cad_csv(app) -> Path:
    p = _data_dir(app) / "cad_library.csv"
    if not p.exists():
        with p.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(CAD_HEADERS)
    return p

def list_cad(app) -> List[Dict[str, Any]]:   # <-- changed from list[dict]
    p = cad_csv(app)
    out: List[Dict[str, Any]] = []
    with p.open("r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            out.append(row)
    out.sort(key=lambda x: x.get("uploaded_at", ""), reverse=True)
    return out

def add_cad_row(app, row: Dict[str, Any]) -> Dict[str, Any]:  # <-- typing version
    p = cad_csv(app)
    with p.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAD_HEADERS)
        w.writerow(row)
    return row

def delete_cad(app, file_id: str) -> bool:
    rows = list_cad(app)
    kept = [r for r in rows if r["id"] != file_id]
    if len(kept) == len(rows):
        return False
    p = cad_csv(app)
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAD_HEADERS)
        w.writeheader()
        for r in kept:
            w.writerow(r)
    return True
