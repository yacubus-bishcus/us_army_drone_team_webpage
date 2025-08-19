from pathlib import Path
import pandas as pd
import re

# canonical schema used by the app
COLUMNS = [
    "name",
    "manufacturer",
    "country",
    "price",
    "range_km",
    "endurance_min",
    "speed_mph",
    "weight_lbs",
    "ceiling_ft",
    "payload_kg",
    "camera_system",
    "blue_list",
    "blue_list_select",
    "webpage",
    "picture",
    "open_software",
    "software",
    "date_added",
    "mission",
    "launch_rate_min",
    "connect",
    "op_temp",
    "processor"
]

NUMERIC_FIELDS = [
    "price",
    "range_km",
    "endurance_min",
    "speed_mph",
    "weight_lbs",
    "ceiling_ft",
    "payload_kg",
    "launch_rate_min"
]

# map *lowercased csv headers --> canonical names 
COLUMN_ALIASES = {
    "drone": "name",
    "manufacturer": "manufacturer",
    "country": "country",
    "cost ($)": "price",
    "range (km)": "range_km",
    "endurance (min)": "endurance_min",
    "speed (mph)": "speed_mph",
    "weight (lbs)": "weight_lbs",
    "ceiling (ft)": "ceiling_ft",
    "payload (kg)": "payload_kg",
    "camera": "camera_system",
    "blue list": "blue_list",
    "blue list select": "blue_list_select",
    "webpage link": "webpage",
    "image link": "picture",
    "open software": "open_software",
    "software": "software",
    "date added to blue list": "date_added",
    "mission": "mission",
    "launch rate (min)": "launch_rate_min",
    "connectivity": "connect",
    "operating temperature": "op_temp",
    "processor": "processor"
}


def data_dir(app): return Path(app.config["DATA_DIR"])
def data_path(app): return data_dir(app) / "blue_list_data.csv"

def create_csv_if_missing(app):
    p = data_path(app)
    if not p.exists():
        data_dir(app).mkdir(exist_ok=True, parents=True)
        seed = [
            {"name":"MQ-1C Gray Eagle","range_km":400,"endurance_hr":25,"ceiling_m":8850,"payload_kg":261},
            {"name":"RQ-7B Shadow","range_km":125,"endurance_hr":9,"ceiling_m":4500,"payload_kg":27},
            {"name":"Switchblade 300","range_km":10,"endurance_hr":0.5,"ceiling_m":450,"payload_kg":2.5},
            {"name":"Bayraktar TB2","range_km":150,"endurance_hr":27,"ceiling_m":7500,"payload_kg":150},
            {"name":"RQ-11 Raven","range_km":10,"endurance_hr":1.5,"ceiling_m":150,"payload_kg":1.9},
        ]
        pd.DataFrame(seed)[COLUMNS].to_csv(p, index=False)

def load_uas(app):
    import pandas as pd
    from pathlib import Path

    p = Path(app.config.get("DATA_DIR", app.instance_path)) / "blue_list_data.csv"
    df = pd.read_csv(p)

    # normalize headers
    rename_map = {}
    for c in df.columns:
        key = c.strip().lower()
        if key in COLUMN_ALIASES:
            rename_map[c] = COLUMN_ALIASES[key]
    df = df.rename(columns=rename_map)

    # make sure all expected columns exist
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA

    # convert numeric fields
    for col in NUMERIC_FIELDS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def append_uas(app, row: dict):
    create_csv_if_missing(app)
    p = data_path(app)
    cleaned = {
        "name": str(row.get("name", "")).strip(),
        "range_km": float(row.get("range_km", 0) or 0),
        "endurance_hr": float(row.get("endurance_hr", 0) or 0),
        "ceiling_m": float(row.get("ceiling_m", 0) or 0),
        "payload_kg": float(row.get("payload_kg", 0) or 0),
    }
    if not cleaned["name"]:
        raise ValueError("Name is required")
    if p.exists():
        existing = pd.read_csv(p)
        if not existing.empty and "name" in existing.columns:
            names_lower = existing["name"].astype(str).str.lower()
            if cleaned["name"].lower() in set(names_lower):
                raise ValueError(f"'{cleaned['name']}' already exists")
    else:
        existing = pd.DataFrame(columns=COLUMNS)
    df_new = pd.DataFrame([cleaned])[COLUMNS]
    write_header = (not p.exists()) or existing.empty
    df_new.to_csv(p, mode="a", header=write_header, index=False)

def delete_uas(app, name: str):
    p = data_path(app)
    if not p.exists(): raise ValueError("No data file to modify")
    df = pd.read_csv(p)
    if df.empty or "name" not in df.columns: raise ValueError("No UAS entries to delete")
    mask = df["name"].astype(str).str.lower() != str(name).strip().lower()
    if mask.all(): raise ValueError(f"'{name}' not found")
    df[mask].to_csv(p, index=False)

# Search helpers (basic + advanced)
from .filters import cast_numeric
_OP_RE = re.compile(r"^\s*(?P<col>[A-Za-z0-9_]+)\s*(?P<op>>=|<=|>|<|=|~|:)\s*(?P<val>.+?)\s*$")

def apply_basic_filters(df, filters):
    if filters.get("name"):
        df = df[df["name"].astype(str).str.contains(filters["name"], case=False, na=False)]
    for c in NUMERIC_FIELDS:
        lo, hi = filters.get(f"{c}_min"), filters.get(f"{c}_max")
        if lo:
            try: df = df[df[c] >= float(lo)]
            except ValueError: pass
        if hi:
            try: df = df[df[c] <= float(hi)]
            except ValueError: pass
    return df

def apply_advanced_query(df, query):
    if not query: return df
    for part in [p.strip() for p in query.split(",") if p.strip()]:
        m = _OP_RE.match(part)
        if not m or m.group("col") not in df.columns: continue
        col, op, val = m.group("col"), m.group("op"), m.group("val")
        if (".." in val) and (op in ("=", ":")):
            lo, hi = [v.strip() for v in val.split("..", 1)]
            cast_numeric(df, NUMERIC_FIELDS + [col])
            if lo: df = df[df[col] >= float(lo)]
            if hi: df = df[df[col] <= float(hi)]
            continue
        if op == "~":
            df = df[df[col].astype(str).str.contains(val, case=False, na=False)]
        elif op == "=":
            try:
                v = float(val); cast_numeric(df, NUMERIC_FIELDS + [col]); df = df[df[col] == v]
            except ValueError:
                df = df[df[col].astype(str).str.lower() == val.lower()]
        else:
            try: v = float(val)
            except ValueError: continue
            cast_numeric(df, NUMERIC_FIELDS + [col])
            if op == ">":  df = df[df[col] >  v]
            if op == ">=": df = df[df[col] >= v]
            if op == "<":  df = df[df[col] <  v]
            if op == "<=": df = df[df[col] <= v]
    return df
