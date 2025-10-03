# drone_team/db.py
import os
from pathlib import Path
from flask_login import UserMixin
from werkzeug.security import generate_password_hash
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.engine import Engine
from typing import Dict, Any, Optional, List 

# --------------------
# User model (unchanged)
# --------------------
class User(UserMixin):
    def __init__(
        self,
        id,
        username,
        password_hash,
        role="user",
        must_change_password=False,
        email: str | None = None,
    ):
        self.id = id
        self.username = username
        self.password_hash = password_hash
        self.role = role
        self.must_change_password = must_change_password
        self.email = email

# --------------------
# Engine factory
# --------------------
_engine: Engine | None = None


def _strtobool(value: Optional[str], default: bool = False) -> bool:
    truthy = {"1", "true", "t", "yes", "y", "on"}
    falsy = {"0", "false", "f", "no", "n", "off"}
    if value is None:
        return default
    value = value.strip().lower()
    if value in truthy:
        return True
    if value in falsy:
        return False
    return default


def _sandbox_enabled(app) -> bool:
    if app is not None:
        return bool(app.config.get("SANDBOX_DATA_MODE", False))
    return _strtobool(os.getenv("SANDBOX_DATA_MODE"), default=False)


def _sandbox_sqlite_url(app) -> Optional[str]:
    if app is not None:
        url = app.config.get("SANDBOX_SQLITE_URL")
        if url:
            return url
    return os.getenv("SANDBOX_SQLITE_URL")

def _sqlite_url_from_app(app) -> str:
    data_dir = Path(app.config["DATA_DIR"])
    data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(data_dir / 'users.db').as_posix()}"

def get_engine(app=None) -> Engine:
    """Return a cached SQLAlchemy engine respecting sandbox mode."""

    global _engine

    sandbox_mode = _sandbox_enabled(app)

    if sandbox_mode:
        target_url = _sandbox_sqlite_url(app)
        if not target_url:
            if app is None:
                target_url = f"sqlite:///{(Path('data') / 'users.db').as_posix()}"
            else:
                target_url = _sqlite_url_from_app(app)
    else:
        target_url = os.getenv("DATABASE_URL")
        if not target_url:
            if app is None:
                target_url = f"sqlite:///{(Path('data') / 'users.db').as_posix()}"
            else:
                target_url = _sqlite_url_from_app(app)

    if _engine is not None and str(_engine.url) != str(target_url):
        _engine.dispose()
        _engine = None

    if _engine is None:
        _engine = create_engine(str(target_url), pool_pre_ping=True, future=True)

    return _engine

# --------------------
# Schema management
# --------------------
def _ddl_for(engine: Engine, table: str) -> str:
    """
    Return DDL string for a table, compatible with the engine's dialect.
    We keep it explicit to mirror your existing schema.
    """
    is_sqlite = engine.dialect.name == "sqlite"

    if table == "users":
        if is_sqlite:
            return """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                email TEXT,
                role TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                must_change_password INTEGER NOT NULL DEFAULT 0
            )
            """
        else:
            # Postgres
            return """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(255) UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                email VARCHAR(255),
                role VARCHAR(64) NOT NULL DEFAULT 'user',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                must_change_password BOOLEAN NOT NULL DEFAULT FALSE
            )
            """
    elif table == "pending_users":
        if is_sqlite:
            return """
            CREATE TABLE IF NOT EXISTS pending_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT NOT NULL,
                sponsor_email TEXT,
                token TEXT UNIQUE NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                decided_at TEXT
            )
            """
        else:
            # Postgres
            return """
            CREATE TABLE IF NOT EXISTS pending_users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(255) UNIQUE NOT NULL,
                email VARCHAR(255) NOT NULL,
                sponsor_email VARCHAR(255),
                token VARCHAR(255) UNIQUE NOT NULL,
                status VARCHAR(64) NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                decided_at TIMESTAMP
            )
            """
    elif table == "password_reset_tokens":
        if is_sqlite:
            return """
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                expires_at TEXT NOT NULL,
                used_at TEXT
            )
            """
        else:
            return """
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token VARCHAR(255) UNIQUE NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                used_at TIMESTAMP
            )
            """
    raise ValueError(f"Unknown table: {table}")

def init_users_db(app):
    """
    Idempotent: creates 'users' and 'pending_users' tables as needed on the active DB.
    """
    engine = get_engine(app)
    with engine.begin() as con:
        con.execute(text(_ddl_for(engine, "users")))
        con.execute(text(_ddl_for(engine, "pending_users")))
        con.execute(text(_ddl_for(engine, "password_reset_tokens")))

    # Ensure legacy databases pick up the must_change_password column
    inspector = inspect(engine)
    user_columns = {col["name"] for col in inspector.get_columns("users")}
    if "must_change_password" not in user_columns:
        column_def = "BOOLEAN NOT NULL DEFAULT FALSE"
        if engine.dialect.name == "sqlite":
            column_def = "INTEGER NOT NULL DEFAULT 0"
        with engine.begin() as con:
            con.execute(text(f"ALTER TABLE users ADD COLUMN must_change_password {column_def}"))
    if "email" not in user_columns:
        column_def = "VARCHAR(255)"
        if engine.dialect.name == "sqlite":
            column_def = "TEXT"
        with engine.begin() as con:
            con.execute(text(f"ALTER TABLE users ADD COLUMN email {column_def}"))

def init_team_applications(app):
    engine = get_engine(app)
    is_sqlite = engine.dialect.name == "sqlite"

    ddl = f"""
    CREATE TABLE IF NOT EXISTS team_applications (
        id {"INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"},
        app_id VARCHAR(64) UNIQUE NOT NULL,
        username VARCHAR(255),
        name VARCHAR(255),
        grade VARCHAR(64),
        unit VARCHAR(255),
        callsign VARCHAR(255),
        email VARCHAR(255),
        phone VARCHAR(64),
        years_experience VARCHAR(64),
        primary_platforms TEXT,
        skills TEXT,
        deploying_12mo VARCHAR(16),
        parental_leave_12mo VARCHAR(16),
        tdy_restrictions TEXT,
        statement TEXT,
        video_path TEXT,
        status VARCHAR(32) NOT NULL DEFAULT 'submitted',
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """
    with engine.begin() as con:
        con.execute(text(ddl))


def insert_team_application(app, data: dict) -> int:
    engine = get_engine(app)
    allowed = {
        "app_id", "username", "name", "grade", "unit", "callsign", "email", "phone",
        "years_experience", "primary_platforms", "skills",
        "deploying_12mo", "parental_leave_12mo", "tdy_restrictions", "statement",
        "video_path", "status"
    }
    payload = {k: v for k, v in data.items() if k in allowed and v is not None}

    payload.setdefault("status", "submitted")

    cols = ", ".join(payload.keys())
    vals = ", ".join([f":{k}" for k in payload.keys()])
    sql = text(f"INSERT INTO team_applications ({cols}) VALUES ({vals}) RETURNING id")

    with engine.begin() as con:
        try:
            row = con.execute(sql, payload).mappings().first()
            return int(row["id"]) if row and "id" in row else 0
        except Exception:
            # SQLite fallback (no RETURNING)
            con.execute(text(f"INSERT INTO team_applications ({cols}) VALUES ({vals})"), payload)
            if engine.dialect.name == "sqlite":
                return con.execute(text("SELECT last_insert_rowid()")).scalar()
            return 0


# --------------------
# Query helpers
# --------------------
def _row_to_user(row) -> User | None:
    if row is None:
        return None
    return User(
        row.id,
        row.username,
        row.password_hash,
        getattr(row, "role", "user"),
        bool(getattr(row, "must_change_password", False)),
        getattr(row, "email", None),
    )

def get_user_by_username(app, username: str) -> User | None:
    engine = get_engine(app)
    sql = text(
        "SELECT id, username, password_hash, role, must_change_password, email "
        "FROM users WHERE username = :u LIMIT 1"
    )
    with engine.connect() as con:
        row = con.execute(sql, {"u": username}).mappings().first()
    return _row_to_user(row)

def get_user_by_id(app, uid: int) -> User | None:
    engine = get_engine(app)
    sql = text(
        "SELECT id, username, password_hash, role, must_change_password, email "
        "FROM users WHERE id = :i LIMIT 1"
    )
    with engine.connect() as con:
        row = con.execute(sql, {"i": uid}).mappings().first()
    return _row_to_user(row)

def get_user_by_email(app, email: str) -> User | None:
    engine = get_engine(app)
    sql = text(
        "SELECT id, username, password_hash, role, must_change_password, email "
        "FROM users WHERE lower(email) = lower(:e) LIMIT 1"
    )
    with engine.connect() as con:
        row = con.execute(sql, {"e": email}).mappings().first()
    return _row_to_user(row)


def create_user(
    app,
    username: str,
    password: str,
    role: str = "user",
    *,
    must_change_password: bool = False,
    email: str | None = None,
) -> User:
    existing = get_user_by_username(app, username)
    if existing:
        if email and getattr(existing, "email", None) != email:
            update_user_email(app, existing.id, email)
        raise ValueError("Username already exists.")
    pwd_hash = generate_password_hash(password)
    engine = get_engine(app)
    sql = text("""
        INSERT INTO users (username, password_hash, role, created_at, must_change_password, email)
        VALUES (:u, :p, :r, CURRENT_TIMESTAMP, :m, :e)
        RETURNING id, username, password_hash, role, must_change_password, email
    """)
    # SQLite before 3.35 doesn't support RETURNING. We fallback if needed.
    with engine.begin() as con:
        try:
            row = con.execute(
                sql,
                {
                    "u": username,
                    "p": pwd_hash,
                    "r": role,
                    "m": must_change_password,
                    "e": email,
                },
            ).mappings().first()
            if row:
                return _row_to_user(row)
        except Exception:
            # Fallback for SQLite: do regular insert then select
            con.execute(
                text(
                    "INSERT INTO users (username, password_hash, role, created_at, must_change_password, email) "
                    "VALUES (:u, :p, :r, CURRENT_TIMESTAMP, :m, :e)"
                ),
                {
                    "u": username,
                    "p": pwd_hash,
                    "r": role,
                    "m": int(must_change_password),
                    "e": email,
                },
            )
    return get_user_by_username(app, username)

def seed_admin_user(app):
    admin_username = app.config["ADMIN_USERNAME"]
    admin = get_user_by_username(app, admin_username)
    if not admin:
        create_user(
            app,
            admin_username,
            app.config["ADMIN_INITIAL_PASSWORD"],
            role="admin",
            email=app.config.get("ADMIN_EMAIL"),
        )
        print(f"[INIT] Admin created: {admin_username} (set ADMIN_INITIAL_PASSWORD env)")


def update_user_email(app, user_id: int, email: str | None):
    engine = get_engine(app)
    with engine.begin() as con:
        con.execute(
            text("UPDATE users SET email = :e WHERE id = :i"),
            {"e": email, "i": user_id},
        )

def update_user_password(app, user_id: int, new_plain_password: str, *, clear_must_change: bool = True):
    engine = get_engine(app)
    pwd_hash = generate_password_hash(new_plain_password)
    with engine.begin() as con:
        params = {"p": pwd_hash, "i": user_id}
        if clear_must_change:
            params["m"] = False
            con.execute(
                text(
                    "UPDATE users SET password_hash = :p, must_change_password = :m WHERE id = :i"
                ),
                params,
            )
        else:
            con.execute(
                text("UPDATE users SET password_hash = :p WHERE id = :i"),
                params,
            )

def get_user_count(app) -> int:
    engine = get_engine(app)
    with engine.connect() as con:
        return int(con.execute(text("SELECT COUNT(*) FROM users")).scalar_one() or 0)

def list_users(app, limit: int = 200, offset: int = 0) -> List[Dict[str, Any]]:
    engine = get_engine(app)
    sql = text("""
        SELECT id, username, role, created_at
          FROM users
         ORDER BY created_at DESC, id DESC
         LIMIT :lim OFFSET :off
    """)
    with engine.connect() as con:
        rows = con.execute(sql, {"lim": limit, "off": offset}).mappings().all()
    return [dict(r) for r in rows]


def _parse_dt(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = value.replace("Z", "+00:00")
        try:
            from datetime import datetime

            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return value


def create_password_reset_token(app, user_id: int, *, expires_minutes: int = 60) -> str:
    from datetime import datetime, timedelta
    import secrets

    engine = get_engine(app)
    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(minutes=expires_minutes)
    expires_str = expires_at.replace(microsecond=0).isoformat()

    with engine.begin() as con:
        # Invalidate any older tokens for this user
        con.execute(
            text(
                "UPDATE password_reset_tokens SET used_at = CURRENT_TIMESTAMP "
                "WHERE user_id = :u AND used_at IS NULL"
            ),
            {"u": user_id},
        )
        # Remove expired tokens to keep table tidy
        con.execute(
            text(
                "DELETE FROM password_reset_tokens WHERE used_at IS NULL AND expires_at < :now"
            ),
            {"now": datetime.utcnow().replace(microsecond=0).isoformat()},
        )
        con.execute(
            text(
                "INSERT INTO password_reset_tokens (user_id, token, expires_at) "
                "VALUES (:u, :t, :e)"
            ),
            {"u": user_id, "t": token, "e": expires_str},
        )
    return token


def get_password_reset_request(app, token: str) -> Dict[str, Any] | None:
    engine = get_engine(app)
    sql = text(
        """
        SELECT prt.id, prt.user_id, prt.token, prt.created_at, prt.expires_at, prt.used_at,
               u.username, u.email
          FROM password_reset_tokens prt
          JOIN users u ON u.id = prt.user_id
         WHERE prt.token = :t
         LIMIT 1
        """
    )
    with engine.connect() as con:
        row = con.execute(sql, {"t": token}).mappings().first()
    if not row:
        return None
    data = dict(row)
    data["expires_at"] = _parse_dt(data.get("expires_at"))
    data["created_at"] = _parse_dt(data.get("created_at"))
    data["used_at"] = _parse_dt(data.get("used_at"))
    return data


def mark_password_reset_used(app, token: str):
    engine = get_engine(app)
    with engine.begin() as con:
        con.execute(
            text(
                "UPDATE password_reset_tokens SET used_at = CURRENT_TIMESTAMP "
                "WHERE token = :t"
            ),
            {"t": token},
        )

def set_user_role(app, user_id: int, role: str) -> int:
    engine = get_engine(app)
    with engine.begin() as con:
        res = con.execute(text("UPDATE users SET role = :r WHERE id = :i"),
                          {"r": role, "i": user_id})
    return res.rowcount or 0

def delete_user(app, user_id: int) -> int:
    engine = get_engine(app)
    with engine.begin() as con:
        res = con.execute(text("DELETE FROM users WHERE id = :i"), {"i": user_id})
    return res.rowcount or 0

# Pending user helpers (if admin.py moderates pending approvals)
def list_pending(app, limit: int = 200, offset: int = 0) -> List[Dict[str, Any]]:
    engine = get_engine(app)
    sql = text("""
        SELECT id, username, email, sponsor_email, token, status, created_at, decided_at
          FROM pending_users
         ORDER BY created_at DESC, id DESC
         LIMIT :lim OFFSET :off
    """)
    with engine.connect() as con:
        rows = con.execute(sql, {"lim": limit, "off": offset}).mappings().all()
    return [dict(r) for r in rows]

def get_pending_by_token(app, token: str) -> Optional[Dict[str, Any]]:
    engine = get_engine(app)
    with engine.connect() as con:
        row = con.execute(
            text("""
                SELECT id, username, email, sponsor_email, token, status, created_at, decided_at
                  FROM pending_users
                 WHERE token = :t
                 LIMIT 1
            """),
            {"t": token},
        ).mappings().first()
        return dict(row) if row else None

def set_pending_status(app, token: str, status: str) -> int:
    engine = get_engine(app)
    with engine.begin() as con:
        res = con.execute(
            text("""
                UPDATE pending_users
                   SET status = :st, decided_at = CURRENT_TIMESTAMP
                 WHERE token = :t
            """),
            {"st": status, "t": token},
        )
        return res.rowcount or 0


# Flask-Login loader
from .extensions import login_manager
@login_manager.user_loader
def load_user(user_id):
    from flask import current_app
    try:
        return get_user_by_id(current_app, int(user_id))
    except Exception:
        return None

