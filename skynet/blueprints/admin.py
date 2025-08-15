from flask import Blueprint, render_template, current_app
from ..authz import roles_required
from ..db import _db, create_user

bp = Blueprint("admin", __name__)

@bp.route("/approve/<token>")
@roles_required("admin")
def approve_user(token):
    con = _db(current_app)
    row = con.execute("SELECT * FROM pending_users WHERE token=? AND status='pending'", (token,)).fetchone()
    if not row:
        con.close()
        return render_template("admin_message.html", title="Approve User", message="Invalid or already processed.", ok=False)
    username = row["username"]; email = row["email"]
    import secrets
    temp_password = secrets.token_urlsafe(8)
    try: create_user(current_app, username, temp_password, role="user")
    except ValueError: pass
    with con:
        con.execute("UPDATE pending_users SET status='approved', decided_at=datetime('now') WHERE id=?", (row["id"],))
    con.close()
    from ..mailer import send_admin_email
    send_admin_email(current_app, f"[Skynet DB] Approved: {username}",
                     f"User '{username}' approved.\nTemporary password: {temp_password}")
    return render_template("admin_message.html", title="Approve User",
                           message=f"Approved '{username}'. Temp password generated.", ok=True)

@bp.route("/deny/<token>")
@roles_required("admin")
def deny_user(token):
    con = _db(current_app)
    row = con.execute("SELECT * FROM pending_users WHERE token=? AND status='pending'", (token,)).fetchone()
    if not row:
        con.close()
        return render_template("admin_message.html", title="Deny User", message="Invalid or already processed.", ok=False)
    with con:
        con.execute("UPDATE pending_users SET status='denied', decided_at=datetime('now') WHERE id=?", (row["id"],))
    con.close()
    from ..mailer import send_admin_email
    send_admin_email(current_app, f"[Skynet DB] Denied: {row['username']}",
                     f"User '{row['username']}' denied.")
    return render_template("admin_message.html", title="Deny User",
                           message=f"Denied '{row['username']}'.", ok=True)
