# drone_team/db.py
# Handles Users 
import sqlite3
from pathlib import Path
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

class User(UserMixin):
    def __init__(self, id, username, password_hash, role="user"):
        self.id = id
        self.username = username
        self.password_hash = password_hash
        self.role = role

def _db(app):
    con = sqlite3.connect(Path(app.config["DATA_DIR"]) / "users.db")
    con.row_factory = sqlite3.Row
    return con

def init_users_db(app):
    con = _db(app)
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
                sponsor_email TEXT,
                token TEXT UNIQUE NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                decided_at TEXT
            )
        """)
    con.close()

def get_user_by_username(app, username):
    con = _db(app)
    row = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    con.close()
    return User(row["id"], row["username"], row["password_hash"], row["role"]) if row else None

def get_user_by_id(app, uid):
    con = _db(app)
    row = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    con.close()
    return User(row["id"], row["username"], row["password_hash"], row["role"]) if row else None

def create_user(app, username, password, role="user"):
    if get_user_by_username(app, username):
        raise ValueError("Username already exists.")
    pwd_hash = generate_password_hash(password)
    con = _db(app)
    with con:
        con.execute(
            "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, datetime('now'))",
            (username, pwd_hash, role),
        )
    con.close()
    return get_user_by_username(app, username)

def seed_admin_user(app):
    admin = get_user_by_username(app, app.config["ADMIN_USERNAME"])
    if not admin:
        create_user(app, app.config["ADMIN_USERNAME"], app.config["ADMIN_INITIAL_PASSWORD"], role="admin")
        print(f"[INIT] Admin created: {app.config['ADMIN_USERNAME']} (set ADMIN_INITIAL_PASSWORD env)")

def update_user_password(app, user_id: int, new_plain_password: str):
    """Hash and store a new password for the given user id."""
    pwd_hash = generate_password_hash(new_plain_password)
    con = _db(app)
    with con:
        con.execute("UPDATE users SET password_hash=? WHERE id=?", (pwd_hash, user_id))
    con.close()

def get_user_count(app):
    con = _db(app)
    row = con.execute("SELECT COUNT(*) FROM users").fetchone()
    con.close()
    return row[0] if row else 0

    
# Flask-Login loader
from .extensions import login_manager
@login_manager.user_loader
def load_user(user_id):
    # We need app context to reach config; import here to avoid circular
    from flask import current_app
    try:
        return get_user_by_id(current_app, int(user_id))
    except Exception:
        return None
