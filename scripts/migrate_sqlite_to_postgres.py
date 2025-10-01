# scripts/migrate_sqlite_to_postgres.py
"""
Migrate data from your existing SQLite file (DATA_DIR/users.db) to Postgres (DATABASE_URL).
Usage:
  export DATA_DIR=/path/to/your/data
  export DATABASE_URL='postgresql+psycopg://user:pass@host:5432/dbname?sslmode=require'
  python scripts/migrate_sqlite_to_postgres.py
"""
import os
from pathlib import Path
from sqlalchemy import create_engine, text

PRESERVE_IDS = True  # keep original ids to avoid surprises in auth/session flows

def sqlite_url() -> str:
    data_dir = Path(os.getenv("DATA_DIR", "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(data_dir / 'users.db').as_posix()}"

def get_src_dst_engines():
    src = create_engine(sqlite_url(), future=True)
    dst_url = os.getenv("DATABASE_URL")
    if not dst_url:
        raise SystemExit("Set DATABASE_URL to your Postgres connection string")
    dst = create_engine(dst_url, pool_pre_ping=True, future=True)
    return src, dst

def ensure_dst_schema(dst):
    # Create tables if not present (Postgres flavor)
    ddl_users = """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,                         -- INTEGER so we can preserve ids
        username VARCHAR(255) UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role VARCHAR(64) NOT NULL DEFAULT 'user',
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """
    ddl_pending = """
    CREATE TABLE IF NOT EXISTS pending_users (
        id INTEGER PRIMARY KEY,
        username VARCHAR(255) UNIQUE NOT NULL,
        email VARCHAR(255) NOT NULL,
        sponsor_email VARCHAR(255),
        token VARCHAR(255) UNIQUE NOT NULL,
        status VARCHAR(64) NOT NULL DEFAULT 'pending',
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        decided_at TIMESTAMP
    )
    """
    with dst.begin() as dconn:
        dconn.execute(text(ddl_users))
        dconn.execute(text(ddl_pending))

def copy_table(src, dst, table_name, columns, unique_conflict_field=None):
    """
    Copy rows from src.table into dst.table.
    If unique_conflict_field is set (e.g., 'username'), skip duplicates gracefully.
    """
    src_cols = ", ".join(columns)
    placeholders = ", ".join([f":{c}" for c in columns])
    insert_sql = text(f"INSERT INTO {table_name} ({src_cols}) VALUES ({placeholders})")

    with src.connect() as sconn:
        rows = sconn.execute(text(f"SELECT {src_cols} FROM {table_name}")).mappings().all()

    copied, skipped = 0, 0
    with dst.begin() as dconn:
        for r in rows:
            try:
                dconn.execute(insert_sql, dict(r))
                copied += 1
            except Exception as e:
                # If it's a uniqueness violation, skip; otherwise re-raise
                msg = str(e).lower()
                if unique_conflict_field and ("unique" in msg or "duplicate" in msg):
                    skipped += 1
                else:
                    raise
    print(f"{table_name}: copied={copied}, skipped={skipped}")

def main():
    src, dst = get_src_dst_engines()
    ensure_dst_schema(dst)

    if PRESERVE_IDS:
        users_cols = ["id", "username", "password_hash", "role", "created_at"]
        pending_cols = ["id", "username", "email", "sponsor_email", "token", "status", "created_at", "decided_at"]
    else:
        # allow Postgres to autogenerate ids
        users_cols = ["username", "password_hash", "role", "created_at"]
        pending_cols = ["username", "email", "sponsor_email", "token", "status", "created_at", "decided_at"]

    copy_table(src, dst, "users", users_cols, unique_conflict_field="username")
    copy_table(src, dst, "pending_users", pending_cols, unique_conflict_field="username")

if __name__ == "__main__":
    main()
