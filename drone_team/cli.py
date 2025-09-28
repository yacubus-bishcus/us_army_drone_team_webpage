# drone_team/cli.py
import click
import sqlite3
from pathlib import Path
from werkzeug.security import generate_password_hash

def register_cli(app):
    @app.cli.command("reset-admin")
    @click.option("--identifier", prompt="Admin username or email")
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def reset_admin(identifier, password):
        """Reset admin password by username or email (SQLite backend)."""
        # Figure out DB path — prefer explicit config, else default to instance/users.db
        db_path = app.config.get("USERS_DB_PATH")
        if not db_path:
            db_path = Path(app.instance_path) / "users.db"

        if not Path(db_path).exists():
            click.echo(f"Users DB not found at {db_path}")
            raise SystemExit(1)

        pwd_hash = generate_password_hash(password)

        conn = sqlite3.connect(str(db_path))
        try:
            cur = conn.cursor()
            # Try username first; if not found, try email
            cur.execute("""
                UPDATE users
                   SET password_hash = ?
                 WHERE lower(username) = lower(?)
                    OR lower(email)    = lower(?)
            """, (pwd_hash, identifier, identifier))
            if cur.rowcount == 0:
                click.echo("No matching user by username/email.")
                raise SystemExit(1)

            # Optional safety: ensure the user is actually admin
            cur.execute("""
                SELECT role FROM users
                 WHERE lower(username) = lower(?)
                    OR lower(email)    = lower(?)
                 LIMIT 1
            """, (identifier, identifier))
            row = cur.fetchone()
            if not row or (row[0] or "").lower() != "admin":
                click.echo("Matched user is not 'admin' role (password still updated).")
            conn.commit()
            click.echo("Admin password updated.")
        finally:
            conn.close()
