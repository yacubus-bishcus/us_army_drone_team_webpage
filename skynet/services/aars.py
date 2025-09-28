# skynet/services/aars.py
from pathlib import Path
import pandas as pd, uuid, datetime as dt, re, csv, os
from werkzeug.utils import secure_filename

AAR_COLUMNS = ["id","created_at","username","unit","drones","training_date","tags","report","summary","attachment"]
ALLOWED_EXT = {"pdf","txt","docx","png","jpg","jpeg"}

def _data_dir(app): return Path(app.config.get("DATA_DIR", "data"))
def aar_path(app):  return Path(_data_dir(app)) / "aar.csv"
def files_dir(app): 
    d = _data_dir(app) / "aar_files"
    d.mkdir(parents=True, exist_ok=True)
    return d

def create_aar_csv_if_missing(app):
    p = aar_path(app)
    if not p.exists():
        _data_dir(app).mkdir(parents=True, exist_ok=True)
        Path(_data_dir(app)).mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=AAR_COLUMNS).to_csv(p, index=False)

def _summarize(text, max_chars=240, max_sentences=3):
    if not text: return ""
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    summary = " ".join(parts[:max_sentences]) if parts else text
    return (summary[:max_chars].rstrip()+"…") if len(summary) > max_chars else summary

def _normalize_tags(s):
    if not s: return ""
    seen, out = set(), []
    for t in re.split(r"[;,]", s):
        t = t.strip().lower()
        if t and t not in seen:
            seen.add(t); out.append(t)
    return ", ".join(out)

def load_df(app):
    create_aar_csv_if_missing(app)
    df = pd.read_csv(aar_path(app))
    for c in AAR_COLUMNS:
        if c not in df.columns: df[c] = ""

    # created_at: first try strict format, then fallback for any legacy rows
    df["created_at"] = pd.to_datetime(df["created_at"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    mask = df["created_at"].isna()
    if mask.any():
        df.loc[mask, "created_at"] = pd.to_datetime(df.loc[mask, "created_at"], errors="coerce")

    return df


def load_list(app):
    df = load_df(app).sort_values("created_at", ascending=False)
    return df[AAR_COLUMNS].to_dict(orient="records")


def append(app, username, unit, drones, training_date, tags, report, file_storage):
    created_at_utc = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    create_aar_csv_if_missing(app)
    attachment = ""
    if file_storage and getattr(file_storage, "filename", ""):
        fname = secure_filename(file_storage.filename)
        ext = fname.rsplit(".",1)[-1].lower()
        if ext not in ALLOWED_EXT: raise ValueError(f"Attachment type not allowed: {fname}")
        unique = f"{Path(fname).stem}-{uuid.uuid4().hex[:8]}.{ext}"
        file_storage.save(files_dir(app) / unique)
        attachment = unique
    # Normalize training_date (HTML date input is usually YYYY-MM-DD already)
    td = (training_date or "").strip()
    if td:
        # Parse leniently, then reformat strictly
        try:
            td = pd.to_datetime(td, errors="raise").strftime("%Y-%m-%d")
        except Exception:
            td = ""  # if user input was junk, store blank; UI will show "N/A"

    row = {
        "id": str(uuid.uuid4()),
        "created_at": created_at_utc,      # <-- fixed format
        "username": username or "anonymous",
        "unit": (unit or "").strip(),
        "drones": (drones or "").strip(),
        "training_date": td,               # <-- fixed format or ""
        "tags": _normalize_tags(tags or ""),
        "report": (report or "").strip(),
        "summary": _summarize(report or ""),
        "attachment": attachment,
    }

    if not row["unit"] or not row["report"]:
        raise ValueError("Unit and Report are required.")
    header_needed = (not aar_path(app).exists()) or pd.read_csv(aar_path(app)).empty
    pd.DataFrame([row])[AAR_COLUMNS].to_csv(aar_path(app), mode="a", header=header_needed, index=False)

def filter_df(df, filters, session_username=None):
    # contains filters
    for key in ["unit","drones","tags","username"]:
        val = (filters.get(key) or "").strip()
        if val:
            df = df[df[key].astype(str).str.contains(val, case=False, na=False)]
    # training_date as date range
    df["training_date"] = pd.to_datetime(df["training_date"], format="%Y-%m-%d", errors="coerce")
    mask = df["training_date"].isna()
    if mask.any():
        df.loc[mask, "training_date"] = pd.to_datetime(df.loc[mask, "training_date"], errors="coerce")

    dfrom = (filters.get("date_from") or "").strip()
    dto   = (filters.get("date_to") or "").strip()
    if dfrom:
        try: df = df[df["training_date"] >= pd.to_datetime(dfrom, format="%Y-%m-%d", errors="raise")]
        except Exception: pass
    if dto:
        try: df = df[df["training_date"] <= pd.to_datetime(dto,   format="%Y-%m-%d", errors="raise")]
        except Exception: pass
    
    return df

def normalize_aar_csv_formats(app):
    """One-time cleanup: rewrite created_at and training_date to strict formats."""
    p = aar_path(app)
    if not p.exists():
        return
    df = pd.read_csv(p)
    CREATED_AT_FMT = "%Y-%m-%d %H:%M:%S"
    TRAINING_DATE_FMT = "%Y-%m-%d"
    ca = pd.to_datetime(df.get("created_at"), format=CREATED_AT_FMT, errors="coerce")
    df["created_at"] = ca.dt.strftime("%Y-%m-%d %H:%M:%S")
    td = pd.to_datetime(df.get("training_date"), format=TRAINING_DATE_FMT, errors="coerce")
    df["training_date"] = td.dt.strftime("%Y-%m-%d")
    df.to_csv(p, index=False)

# --- ADD BELOW YOUR EXISTING IMPORTS ---
import csv, os, datetime
from collections import defaultdict

def _data_dir(app):
    # Reuse your DATA_DIR if you have it, else put under instance/data
    base = app.config.get("DATA_DIR") or os.path.join(app.instance_path, "data")
    os.makedirs(base, exist_ok=True)
    return base

def votes_csv_path(app):
    return os.path.join(_data_dir(app), "aars_votes.csv")

def comments_csv_path(app):
    return os.path.join(_data_dir(app), "aars_comments.csv")

def _ensure_votes_csv(app):
    path = votes_csv_path(app)
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["aar_id","username","value","created_at"])
    return path

def _ensure_comments_csv(app):
    path = comments_csv_path(app)
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["aar_id","username","body","created_at"])
    return path

def record_vote(app, aar_id, username: str, value: int):
    """
    Upsert a vote: unique by (aar_id, username). value in {-1,0,+1}.
    If value == 0, remove the user's vote (if present).
    """
    path = _ensure_votes_csv(app)
    rows = []
    found = False
    # Read existing
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            if row["aar_id"] == str(aar_id) and row["username"] == username:
                found = True
                if value == 0:
                    # Skip to delete
                    continue
                else:
                    row["value"] = str(int(value))
                    row["created_at"] = datetime.datetime.utcnow().isoformat()
            rows.append(row)
    # If not found and adding, append
    if not found and value != 0:
        rows.append({
            "aar_id": str(aar_id),
            "username": username,
            "value": str(int(value)),
            "created_at": datetime.datetime.utcnow().isoformat()
        })
    # Write back
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["aar_id","username","value","created_at"])
        w.writeheader(); w.writerows(rows)

def get_scores(app, aar_ids):
    """Return {aar_id: sum(value)} for provided ids."""
    path = _ensure_votes_csv(app)
    totals = defaultdict(int)
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        wanted = set(str(x) for x in aar_ids)
        for row in r:
            aid = row["aar_id"]
            if aid in wanted:
                totals[aid] += int(row["value"])
    # ensure all keys present
    for aid in aar_ids:
        totals[str(aid)] += 0
    return dict(totals)

def get_user_votes(app, username, aar_ids):
    """Return {aar_id: value or 0} for this user."""
    path = _ensure_votes_csv(app)
    out = {str(a): 0 for a in aar_ids}
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        wanted = set(str(x) for x in aar_ids)
        for row in r:
            if row["username"] != username:
                continue
            aid = row["aar_id"]
            if aid in wanted:
                out[aid] = int(row["value"])
    return out

def add_comment(app, aar_id, username: str, body: str):
    path = _ensure_comments_csv(app)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([str(aar_id), username, body, datetime.datetime.utcnow().isoformat()])

def get_comments(app, aar_ids):
    """Return {aar_id: [ {user, body, created_at}, ... ]}, oldest->newest."""
    path = _ensure_comments_csv(app)
    out = defaultdict(list)
    wanted = set(str(x) for x in aar_ids)
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            aid = row["aar_id"]
            if aid in wanted:
                out[aid].append({
                    "user": row["username"],
                    "body": row["body"],
                    "created_at": row["created_at"]
                })
    # sort each thread
    for aid in list(out.keys()):
        out[aid].sort(key=lambda x: x["created_at"])
    # ensure keys exist
    for aid in aar_ids:
        out[str(aid)]  # touch
    return dict(out)
