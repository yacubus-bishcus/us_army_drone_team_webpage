#skynet_database.py

from flask import Flask, render_template, request, redirect, url_for, Response, send_from_directory, session
from werkzeug.utils import secure_filename 
import pandas as pd
from pathlib import Path
import webbrowser
from threading import Timer
import io, re, uuid, os, smtplib, sqlite3, secrets, datetime as dt 
from email.message import EmailMessage 
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user 
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps 
# --- CONFIG ---
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "you@example.com")

MAIL_SERVER   = os.getenv("MAIL_SERVER", "smtp.gmail.com")
MAIL_PORT     = int(os.getenv("MAIL_PORT", "587"))
MAIL_USE_TLS  = os.getenv("MAIL_USE_TLS", "1") == "1"
MAIL_USERNAME = os.getenv("MAIL_USERNAME", "your_smtp_username")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "your_smtp_app_password")
app = Flask(__name__)
app.secret_key = "change-me-please"  # required for session

def send_admin_email(subject: str, body: str):
    try:
        msg = EmailMessage()
        msg["From"] = MAIL_USERNAME
        msg["To"] = ADMIN_EMAIL
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as s:
            if MAIL_USE_TLS:
                s.starttls()
            if MAIL_USERNAME and MAIL_PASSWORD:
                s.login(MAIL_USERNAME, MAIL_PASSWORD)
            s.send_message(msg)
        print("[MAIL] Admin email sent.")
    except Exception as e:
        # Fallback so you still see the approve/deny URLs during dev
        print("[MAIL ERROR]", e)
        print("Subject:", subject)
        print("Body:\n", body)

# ---- Auth setup ----
login_manager = LoginManager()
login_manager.login_view = "login_page"   # route name (not path)
login_manager.init_app(app)

USERS_DB = Path(__file__).parent / "data" / "users.db"
USERS_DB.parent.mkdir(parents=True, exist_ok=True)

UPLOAD_DIR = Path(__file__).parent / "data" / "aar_files"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_EXTENSIONS = {"pdf", "txt", "docx", "png", "jpg", "jpeg"}

# CSV path inside ./data
DATA_DIR = Path(__file__).parent / "data"
DATA_PATH = DATA_DIR / "uas_data.csv"

COLUMNS = ["name", "range_km", "endurance_hr", "ceiling_m", "payload_kg"]  # keep a consistent order
NUMERIC_FIELDS = ["range_km", "endurance_hr", "ceiling_m", "payload_kg"]

# AAR CONSTANTS 
AAR_DIR = Path(__file__).parent / "data"
AAR_PATH = AAR_DIR / "aar.csv"
AAR_COLUMNS = [
    "id", "created_at", "username", "unit", "drones",
    "training_date", "tags", "report", "summary", "attachment"
]

# AAR HELPER FUNCTIONS 
def create_aar_csv_if_missing():
    if not AAR_PATH.exists():
        AAR_DIR.mkdir(exist_ok=True)
        pd.DataFrame(columns=AAR_COLUMNS).to_csv(AAR_PATH, index=False)
        print(f"Created AAR CSV at {AAR_PATH}")

def _summarize_report(text: str, max_chars: int = 240, max_sentences: int = 3) -> str:
    if not text:
        return ""
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    if not parts:
        return text[:max_chars]
    summary = " ".join(parts[:max_sentences])
    if len(summary) > max_chars:
        summary = summary[:max_chars].rstrip() + "…"
    return summary

def _normalize_tags(s: str) -> str:
    if not s:
        return ""
    tags = [t.strip() for t in re.split(r"[;,]", s) if t.strip()]
    # lower + dedupe preserving order
    seen = set()
    norm = []
    for t in tags:
        lt = t.lower()
        if lt not in seen:
            seen.add(lt)
            norm.append(lt)
    return ", ".join(norm)

def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def load_aars_df():
    create_aar_csv_if_missing()
    df = pd.read_csv(AAR_PATH)
    for col in AAR_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    with pd.option_context('mode.chained_assignment', None):
        df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    return df

def load_aars():
    df = load_aars_df()
    df = df.sort_values("created_at", ascending=False)
    return df[AAR_COLUMNS].to_dict(orient="records")

def append_aar(unit: str, drones: str, training_date: str, tags: str, report: str, file_storage):
    create_aar_csv_if_missing()
    username = session.get("username", "anonymous")
    attachment_name = ""

    # Save attachment if provided and allowed
    if file_storage and getattr(file_storage, "filename", ""):
        fname = secure_filename(file_storage.filename)
        if not _allowed_file(fname):
            raise ValueError(f"Attachment type not allowed: {fname}")
        # Make filename unique
        ext = fname.rsplit(".", 1)[1].lower()
        uname = Path(fname).stem
        unique_name = f"{uname}-{uuid.uuid4().hex[:8]}.{ext}"
        file_storage.save(UPLOAD_DIR / unique_name)
        attachment_name = unique_name

    row = {
        "id": str(uuid.uuid4()),
        "created_at": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "username": username,
        "unit": (unit or "").strip(),
        "drones": (drones or "").strip(),
        "training_date": (training_date or "").strip(),
        "tags": _normalize_tags(tags or ""),
        "report": (report or "").strip(),
        "summary": _summarize_report(report or ""),
        "attachment": attachment_name,
    }
    if not row["unit"] or not row["report"]:
        raise ValueError("Unit and Report are required.")

    header_needed = (not AAR_PATH.exists()) or pd.read_csv(AAR_PATH).empty
    pd.DataFrame([row])[AAR_COLUMNS].to_csv(AAR_PATH, mode="a", header=header_needed, index=False)

# AAR FILTER & EXPORT HELPERS 
def filter_aars(df, filters):
    # text contains (case-insensitive)
    for key in ["unit", "drones", "tags", "username"]:
        val = (filters.get(key) or "").strip()
        if val:
            df = df[df[key].astype(str).str.contains(val, case=False, na=False)]
    # date range on training_date (YYYY-MM-DD)
    df["training_date"] = pd.to_datetime(df["training_date"], errors="coerce")
    dfrom = (filters.get("date_from") or "").strip()
    dto   = (filters.get("date_to") or "").strip()
    if dfrom:
        try:
            df = df[df["training_date"] >= pd.to_datetime(dfrom)]
        except Exception:
            pass
    if dto:
        try:
            df = df[df["training_date"] <= pd.to_datetime(dto)]
        except Exception:
            pass
    # Mine only
    if (filters.get("mine_only") or "").lower() in ("1", "true", "on"):
        df = df[df["username"] == session.get("username", "anonymous")]
    return df

def export_aars_csv(df) -> str:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


@app.route("/files/aar/<path:filename>")
@login_required
def aar_file(filename):
    return send_from_directory(UPLOAD_DIR, filename, as_attachment=True)

# COMPARISON TOOL HELPERS
def _cast_numeric(df):
    for col in NUMERIC_FIELDS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df

def apply_basic_filters(df, filters):
    # Text filter on name (contains, case-insensitive)
    if filters.get("name"):
        df = df[df["name"].astype(str).str.contains(filters["name"], case=False, na=False)]
    # Numeric ranges
    for col in NUMERIC_FIELDS:
        min_key, max_key = f"{col}_min", f"{col}_max"
        if filters.get(min_key):
            try: df = df[df[col] >= float(filters[min_key])]
            except ValueError: pass
        if filters.get(max_key):
            try: df = df[df[col] <= float(filters[max_key])]
            except ValueError: pass
    return df

_OP_RE = re.compile(r"""
    ^\s*
    (?P<col>[A-Za-z0-9_]+)         # column
    \s*(?P<op>>=|<=|>|<|=|~|:)     # operator; ':' allowed to indicate range 'col:100..500'
    \s*(?P<val>.+?)\s*$
""", re.VERBOSE)

def apply_advanced_query(df, query):
    """
    Supports comma-separated clauses like:
      name~raven, range_km>=100, endurance_hr=10..30, payload_kg<50, ceiling_m=12000
    Operators:
      ~  contains (case-insensitive) for string columns
      =  equals (numeric exact or string case-insensitive)
      >, >=, <, <= numeric comparisons
      Range: `=` or `:` with `min..max` (inclusive), e.g., range_km=100..500  or  range_km:100..500
    """
    if not query:
        return df
    parts = [p.strip() for p in query.split(",") if p.strip()]
    for part in parts:
        m = _OP_RE.match(part)
        if not m:  # ignore malformed piece
            continue
        col, op, val = m.group("col"), m.group("op"), m.group("val")
        if col not in df.columns:
            continue

        # Range like 100..500
        if (".." in val) and (op in ("=", ":")):
            lo, hi = [v.strip() for v in val.split("..", 1)]
            try:
                lo_f = float(lo) if lo else None
                hi_f = float(hi) if hi else None
            except ValueError:
                continue
            df = _cast_numeric(df)
            if lo_f is not None:
                df = df[df[col] >= lo_f]
            if hi_f is not None:
                df = df[df[col] <= hi_f]
            continue

        # Single value comparisons
        if op == "~":
            df = df[df[col].astype(str).str.contains(val, case=False, na=False)]
        elif op == "=":
            # numeric equality if possible, else case-insensitive string match
            try:
                v = float(val)
                df = _cast_numeric(df)
                df = df[df[col] == v]
            except ValueError:
                df = df[df[col].astype(str).str.lower() == val.lower()]
        elif op in (">", ">=", "<", "<="):
            try:
                v = float(val)
            except ValueError:
                continue
            df = _cast_numeric(df)
            if op == ">":  df = df[df[col] >  v]
            if op == ">=": df = df[df[col] >= v]
            if op == "<":  df = df[df[col] <  v]
            if op == "<=": df = df[df[col] <= v]
    return df

def create_csv_if_missing():
    """Create a starter CSV if it doesn't exist yet."""
    if not DATA_PATH.exists():
        DATA_DIR.mkdir(exist_ok=True)
        data = [
            {"name": "MQ-1C Gray Eagle", "range_km": 400, "endurance_hr": 25, "ceiling_m": 8850, "payload_kg": 261},
            {"name": "RQ-7B Shadow", "range_km": 125, "endurance_hr": 9, "ceiling_m": 4500, "payload_kg": 27},
            {"name": "Switchblade 300", "range_km": 10, "endurance_hr": 0.5, "ceiling_m": 450, "payload_kg": 2.5},
            {"name": "Bayraktar TB2", "range_km": 150, "endurance_hr": 27, "ceiling_m": 7500, "payload_kg": 150},
            {"name": "RQ-11 Raven", "range_km": 10, "endurance_hr": 1.5, "ceiling_m": 150, "payload_kg": 1.9},
        ]
        pd.DataFrame(data)[COLUMNS].to_csv(DATA_PATH, index=False)
        print(f"Created starter CSV at {DATA_PATH}")

def load_uas():
    """Load UAS data from CSV into a list of dicts."""
    if not DATA_PATH.exists():
        create_csv_if_missing()
    df = pd.read_csv(DATA_PATH)
    # Enforce column order in case CSV was externally edited
    df = df[[c for c in COLUMNS if c in df.columns]]
    return df.to_dict(orient="records")

def append_uas(row: dict):
    """Append a single UAS row to the CSV. Creates CSV if missing."""
    create_csv_if_missing()

    # Normalize + type cast
    cleaned = {
        "name": str(row.get("name", "")).strip(),
        "range_km": float(row.get("range_km", 0) or 0),
        "endurance_hr": float(row.get("endurance_hr", 0) or 0),
        "ceiling_m": float(row.get("ceiling_m", 0) or 0),
        "payload_kg": float(row.get("payload_kg", 0) or 0),
    }
    if not cleaned["name"]:
        raise ValueError("Name is required")

    # Prevent duplicate by name (case-insensitive)
    if DATA_PATH.exists():
        existing = pd.read_csv(DATA_PATH)
        if not existing.empty and "name" in existing.columns:
            names_lower = existing["name"].astype(str).str.lower()
            if cleaned["name"].lower() in set(names_lower):
                raise ValueError(f"'{cleaned['name']}' already exists")
    else:
        existing = pd.DataFrame(columns=COLUMNS)

    # Append safely, writing headers only if file is missing or empty
    df_new = pd.DataFrame([cleaned])[COLUMNS]
    write_header = (not DATA_PATH.exists()) or existing.empty
    df_new.to_csv(DATA_PATH, mode="a", header=write_header, index=False)


def delete_uas(name: str):
    """Delete a UAS row by name (case-insensitive)."""
    if not DATA_PATH.exists():
        raise ValueError("No data file to modify")

    df = pd.read_csv(DATA_PATH)
    if df.empty or "name" not in df.columns:
        raise ValueError("No UAS entries to delete")

    mask = df["name"].astype(str).str.lower() != str(name).strip().lower()
    if mask.all():
        raise ValueError(f"'{name}' not found")

    df_filtered = df[mask]
    df_filtered.to_csv(DATA_PATH, index=False)


@app.route("/delete", methods=["POST"])
@login_required
def delete():
    try:
        name = request.form.get("name", "")
        if not name:
            raise ValueError("Missing name")
        delete_uas(name)
        return redirect(url_for("index", message=f"Deleted '{name}'"))
    except Exception as e:
        return redirect(url_for("index", error=str(e)))


@app.route("/add", methods=["POST"])
@login_required
def add():
    try:
        form = request.form
        append_uas({
            "name": form.get("name", ""),
            "range_km": form.get("range_km", ""),
            "endurance_hr": form.get("endurance_hr", ""),
            "ceiling_m": form.get("ceiling_m", ""),
            "payload_kg": form.get("payload_kg", ""),
        })
        return redirect(url_for("index", message="UAS added successfully"))
    except Exception as e:
        return redirect(url_for("index", error=str(e)))

#####################################################################################
## MENU ROUTES 
#####################################################################################
# ---------- Auth routes ----------
@app.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = get_user_by_username(username)
        if not user or not check_password_hash(user.password_hash, password):
            return redirect(url_for("login_page", error="Invalid credentials."))
        login_user(user, remember=True)
        return redirect(request.args.get("next") or url_for("home", message=f"Welcome, {user.username}!"))
    # GET
    return render_template("auth_login.html",
                           error=request.args.get("error", ""),
                           message=request.args.get("message", ""))

@app.route("/register", methods=["GET", "POST"])
def register_page():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email    = (request.form.get("email") or "").strip()
        reason   = (request.form.get("reason") or "").strip()

        if not username or not email:
            return redirect(url_for("register_page", error="Username and email are required."))

        # Already a real user?
        if get_user_by_username(username):
            return redirect(url_for("login_page", message="Account already exists. Please sign in."))

        # Create/replace pending request
        token = secrets.token_urlsafe(24)
        con = _db()
        with con:
            con.execute("""
                INSERT INTO pending_users (username, email, reason, token, status, created_at)
                VALUES (?, ?, ?, ?, 'pending', datetime('now'))
                ON CONFLICT(username) DO UPDATE SET
                    email=excluded.email, reason=excluded.reason, token=excluded.token,
                    status='pending', created_at=datetime('now'), decided_at=NULL
            """, (username, email, reason, token))
        con.close()

        approve_url = url_for("admin_approve_user", token=token, _external=True)
        deny_url    = url_for("admin_deny_user", token=token, _external=True)

        subject = f"[Skynet DB] Access request: {username}"
        body = (
            f"User requested access.\n\n"
            f"Username: {username}\nEmail: {email}\nReason:\n{reason}\n\n"
            f"Approve: {approve_url}\nDeny: {deny_url}\n\n"
            f"(You must be signed in as an admin to use these links.)"
        )
        send_admin_email(subject, body)

        return redirect(url_for("login_page", message="Request submitted. We'll email the admin for approval."))

    # GET
    return render_template("auth_request_access.html",
                           error=request.args.get("error", ""))


@app.route("/logout")
@login_required
def logout_page():
    logout_user()
    return redirect(url_for("home", message="Signed out."))



@app.route("/")
@app.route("/home")
def home():
    """Landing page."""
    message = request.args.get("message", "")
    error = request.args.get("error", "")
    return render_template("home.html", message=message, error=error)


@app.route("/compare")
@login_required
def compare():
    """Comparison Tool page (moved from old index)."""
    uas_list = load_uas()
    headers = COLUMNS if uas_list else COLUMNS
    message = request.args.get("message", "")
    error = request.args.get("error", "")
    return render_template("compare.html", headers=headers, uas_list=uas_list, message=message, error=error)


@app.route("/search", methods=["GET"])
@login_required
def search():
    # Load CSV
    total = 0
    if DATA_PATH.exists():
        df = pd.read_csv(DATA_PATH)
    else:
        df = pd.DataFrame(columns=COLUMNS)

    df = _cast_numeric(df)
    total = len(df)

    # Collect filters
    filters = {
        "name": request.args.get("name", "").strip(),
        "range_km_min": request.args.get("range_km_min", "").strip(),
        "range_km_max": request.args.get("range_km_max", "").strip(),
        "endurance_hr_min": request.args.get("endurance_hr_min", "").strip(),
        "endurance_hr_max": request.args.get("endurance_hr_max", "").strip(),
        "ceiling_m_min": request.args.get("ceiling_m_min", "").strip(),
        "ceiling_m_max": request.args.get("ceiling_m_max", "").strip(),
        "payload_kg_min": request.args.get("payload_kg_min", "").strip(),
        "payload_kg_max": request.args.get("payload_kg_max", "").strip(),
    }
    advanced = request.args.get("advanced", "").strip()

    # Column selection (default: all)
    selected_columns = request.args.getlist("columns")
    if not selected_columns:
        selected_columns = COLUMNS[:]  # all

    # Apply filters
    df_filtered = apply_basic_filters(df.copy(), filters)
    df_filtered = apply_advanced_query(df_filtered, advanced)

    # Ensure selected columns exist
    display_cols = [c for c in selected_columns if c in df_filtered.columns]
    if not display_cols:
        display_cols = COLUMNS[:]

    results = df_filtered[display_cols].to_dict(orient="records")

    # Build export URL preserving the current query string
    qs = request.query_string.decode()
    export_url = url_for("search_export") + (f"?{qs}" if qs else "")

    return render_template(
        "search.html",
        headers=display_cols,
        results=results,
        total=total,
        filters=filters,
        advanced=advanced,
        all_columns=COLUMNS,
        selected_columns=set(display_cols),
        export_url=export_url,
    )


@app.route("/search/export", methods=["GET"])
@login_required
def search_export():
    # Reuse the same logic as /search to produce the filtered DataFrame
    if DATA_PATH.exists():
        df = pd.read_csv(DATA_PATH)
    else:
        df = pd.DataFrame(columns=COLUMNS)

    df = _cast_numeric(df)

    filters = {
        "name": request.args.get("name", "").strip(),
        "range_km_min": request.args.get("range_km_min", "").strip(),
        "range_km_max": request.args.get("range_km_max", "").strip(),
        "endurance_hr_min": request.args.get("endurance_hr_min", "").strip(),
        "endurance_hr_max": request.args.get("endurance_hr_max", "").strip(),
        "ceiling_m_min": request.args.get("ceiling_m_min", "").strip(),
        "ceiling_m_max": request.args.get("ceiling_m_max", "").strip(),
        "payload_kg_min": request.args.get("payload_kg_min", "").strip(),
        "payload_kg_max": request.args.get("payload_kg_max", "").strip(),
    }
    advanced = request.args.get("advanced", "").strip()
    selected_columns = request.args.getlist("columns")
    if not selected_columns:
        selected_columns = COLUMNS[:]

    df_filtered = apply_basic_filters(df.copy(), filters)
    df_filtered = apply_advanced_query(df_filtered, advanced)

    # Only export selected columns (and ensure they exist)
    export_cols = [c for c in selected_columns if c in df_filtered.columns]
    if not export_cols:
        export_cols = COLUMNS[:]

    buf = io.StringIO()
    df_filtered[export_cols].to_csv(buf, index=False)
    csv_bytes = buf.getvalue()

    return Response(
        csv_bytes,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=skynet_search_export.csv"}
    )


@app.route("/submit-aar", methods=["GET", "POST"])
@login_required
def submit_aar():
    if request.method == "POST":
        try:
            unit = request.form.get("unit", "")
            drones = request.form.get("drones", "")
            training_date = request.form.get("training_date", "")
            tags = request.form.get("tags", "")
            report = request.form.get("report", "")
            file_storage = request.files.get("attachment")
            append_aar(unit, drones, training_date, tags, report, file_storage)
            return redirect(url_for("submit_aar", message="AAR submitted successfully"))
        except Exception as e:
            return redirect(url_for("submit_aar", error=str(e)))

    # GET with filters
    message = request.args.get("message", "")
    error = request.args.get("error", "")
    filters = {
        "unit": request.args.get("unit", ""),
        "drones": request.args.get("drones", ""),
        "tags": request.args.get("tags", ""),
        "username": request.args.get("username", ""),
        "date_from": request.args.get("date_from", ""),
        "date_to": request.args.get("date_to", ""),
        "mine_only": request.args.get("mine_only", ""),
    }
    df = load_aars_df()
    df = filter_aars(df, filters)
    df = df.sort_values("created_at", ascending=False)
    aars = df[AAR_COLUMNS].to_dict(orient="records")

    # Export URL preserves query
    qs = request.query_string.decode()
    export_url = url_for("submit_aar_export") + (f"?{qs}" if qs else "")

    return render_template("submit_aar.html",
                           message=message, error=error, aars=aars,
                           filters=filters, export_url=export_url,
                           logged_in=session.get("username"))


@app.route("/submit-aar/export", methods=["GET"])
@login_required
def submit_aar_export():
    filters = {
        "unit": request.args.get("unit", ""),
        "drones": request.args.get("drones", ""),
        "tags": request.args.get("tags", ""),
        "username": request.args.get("username", ""),
        "date_from": request.args.get("date_from", ""),
        "date_to": request.args.get("date_to", ""),
        "mine_only": request.args.get("mine_only", ""),
    }
    df = load_aars_df()
    df = filter_aars(df, filters)
    csv_text = export_aars_csv(df[AAR_COLUMNS])
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=aars_export.csv"}
    )


@app.route("/submit-recommendations")
@login_required
def submit_recommendations():
    return render_template("placeholder.html",
                           title="Submit Recommendations",
                           lead="Propose improvements or feature requests (coming soon).")


@app.route("/profile")
@login_required
def profile():
    return render_template("placeholder.html",
                           title="Profile",
                           lead="Manage your profile and preferences (coming soon).")

# LOGIN HELPERS 
# ---- Users (SQLite, no ORM) ----
class User(UserMixin):
    def __init__(self, id, username, password_hash, role="user"):
        self.id = id
        self.username = username
        self.password_hash = password_hash
        self.role = role

def _db():
    con = sqlite3.connect(USERS_DB)
    con.row_factory = sqlite3.Row
    return con

def init_users_db():
    con = _db()
    with con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS pending_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT NOT NULL,
                reason TEXT,
                token TEXT UNIQUE NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', -- pending|approved|denied
                created_at TEXT NOT NULL,
                decided_at TEXT
            )
        """)
    con.close()

def seed_admin_user():
    """Create an initial admin if missing."""
    admin_username = os.getenv("ADMIN_USERNAME", "admin")
    admin_password = os.getenv("ADMIN_INITIAL_PASSWORD", "change_me_now")
    u = get_user_by_username(admin_username)
    if not u:
        create_user(admin_username, admin_password, role="admin")
        print(f"[INIT] Admin user created: {admin_username} / (set ADMIN_INITIAL_PASSWORD env)")


def get_user_by_username(username: str):
    con = _db()
    cur = con.execute("SELECT * FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    con.close()
    if row:
        return User(row["id"], row["username"], row["password_hash"], row["role"])
    return None

def get_user_by_id(uid: int):
    con = _db()
    cur = con.execute("SELECT * FROM users WHERE id = ?", (uid,))
    row = cur.fetchone()
    con.close()
    if row:
        return User(row["id"], row["username"], row["password_hash"], row["role"])
    return None

def create_user(username: str, password: str, role: str = "user"):
    if get_user_by_username(username) is not None:
        raise ValueError("Username already exists.")
    pwd_hash = generate_password_hash(password)
    con = _db()
    with con:
        con.execute(
            "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, datetime('now'))",
            (username, pwd_hash, role),
        )
    con.close()
    return get_user_by_username(username)

@login_manager.user_loader
def load_user(user_id):
    try:
        return get_user_by_id(int(user_id))
    except Exception:
        return None

@app.before_request
def require_login_for_everything_except_home_and_auth():
    # Endpoints allowed without auth
    public_endpoints = {"home", "login_page", "register_page", "static"}
    # If endpoint is unknown (e.g., 404) skip
    if request.endpoint and request.endpoint not in public_endpoints:
        if not current_user.is_authenticated:
            return login_manager.unauthorized()  # triggers redirect to login_view

def roles_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in roles:
                # Send to login, then you bounce back
                return login_manager.unauthorized()
            return fn(*args, **kwargs)
        return wrapper
    return deco

@app.route("/admin/approve/<token>")
@roles_required("admin")
def admin_approve_user(token):
    # Lookup pending
    con = _db()
    cur = con.execute("SELECT * FROM pending_users WHERE token=? AND status='pending'", (token,))
    row = cur.fetchone()
    if not row:
        con.close()
        return render_template("admin_message.html", title="Approve User", message="Invalid or already processed.", ok=False)

    username = row["username"]
    email    = row["email"]
    # Create user with a temporary password, email admin display (or send to user if desired)
    temp_password = secrets.token_urlsafe(8)
    try:
        create_user(username, temp_password, role="user")
    except ValueError:
        pass  # already exists

    with con:
        con.execute("UPDATE pending_users SET status='approved', decided_at=datetime('now') WHERE id=?", (row["id"],))
    con.close()

    # Notify admin (optionally email the user here instead)
    send_admin_email(
        subject=f"[Skynet DB] Approved: {username}",
        body=f"User '{username}' has been approved.\nTemporary password: {temp_password}\n\nYou can share these credentials securely."
    )

    return render_template("admin_message.html", title="Approve User",
                           message=f"Approved '{username}'. Temp password generated.", ok=True)

@app.route("/admin/deny/<token>")
@roles_required("admin")
def admin_deny_user(token):
    con = _db()
    cur = con.execute("SELECT * FROM pending_users WHERE token=? AND status='pending'", (token,))
    row = cur.fetchone()
    if not row:
        con.close()
        return render_template("admin_message.html", title="Deny User", message="Invalid or already processed.", ok=False)
    with con:
        con.execute("UPDATE pending_users SET status='denied', decided_at=datetime('now') WHERE id=?", (row["id"],))
    con.close()
    send_admin_email(subject=f"[Skynet DB] Denied: {row['username']}",
                     body=f"User '{row['username']}' was denied.")
    return render_template("admin_message.html", title="Deny User",
                           message=f"Denied '{row['username']}'.", ok=True)

#####################################################################################
#####################################################################################
#####################################################################################
if __name__ == "__main__":
    init_users_db()
    seed_admin_user()
    create_csv_if_missing()
     # Automatically open the browser after the server starts
    def open_browser():
        webbrowser.open_new("http://127.0.0.1:5000")

    # Wait 1 second to ensure Flask starts before opening browser
    Timer(1, open_browser).start()
    app.run(debug=True, use_reloader=False)