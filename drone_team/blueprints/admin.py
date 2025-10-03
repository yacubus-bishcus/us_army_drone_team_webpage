#drone_team_blueprints/admin.py
from flask import Blueprint, render_template, current_app
from ..authz import roles_required
from ..db import (
    create_user,
    get_pending_by_token,   # new helper
    set_pending_status      # new helper
)

bp = Blueprint("admin", __name__)

@bp.route("/approve/<token>")
@roles_required("admin")
def approve_user(token):
    row = get_pending_by_token(current_app, token)
    if not row or row.get("status") != "pending":
        return render_template(
            "admin_message.html",
            title="Approve User",
            message="Invalid or already processed.",
            ok=False
        )

    username = row["username"]
    email = row["email"]
    sponsor_email = row.get("sponsor_email")

    import secrets
    temp_password = secrets.token_urlsafe(12)

    # Create user if missing (ignore if already exists)
    try:
        create_user(
            current_app,
            username,
            temp_password,
            role="user",
            must_change_password=True,
            email=email,
        )
    except ValueError:
        pass

    # Mark pending as approved
    set_pending_status(current_app, token, "approved")

    # Notify
    from ..mailer import send_email
    send_email(
        current_app,
        email,
        f"[drone_team DB] Approved: {username}",
        f"User '{username}' approved.\nTemporary password: {temp_password}\n\n"
        f"Upon sign in with temporary password you will be required to change password. Don't forget to Apply to the Team on the website at US Army Drone Team --> Apply"
    )
    if sponsor_email:
        send_email(
            current_app,
            sponsor_email,
            f"[drone_team DB] Approved: {username}",
            f"User '{username}' has been approved. No further action required."
        )

    return render_template(
        "admin_message.html",
        title="Approve User",
        message=f"Approved '{username}'. Temp password generated.",
        ok=True
    )


@bp.route("/deny/<token>")
@roles_required("admin")
def deny_user(token):
    row = get_pending_by_token(current_app, token)
    if not row or row.get("status") != "pending":
        return render_template(
            "admin_message.html",
            title="Deny User",
            message="Invalid or already processed.",
            ok=False
        )

    username = row["username"]
    email = row["email"]
    sponsor_email = row.get("sponsor_email")

    # Mark pending as denied
    set_pending_status(current_app, token, "denied")

    # Notify
    from ..mailer import send_admin_email, send_email
    send_admin_email(
        current_app,
        f"[drone_team DB] Denied: {username}",
        f"User '{username}' denied."
    )
    send_email(
        current_app,
        email,
        f"[drone_team DB] Denied: {username}",
        f"[drone_team DB] Denied: {username}"
    )
    if sponsor_email:
        send_email(
            current_app,
            sponsor_email,
            f"[drone_team DB] Denied: {username}",
            f"[drone_team DB] Denied: {username}"
        )

    return render_template(
        "admin_message.html",
        title="Deny User",
        message=f"Denied '{username}'.",
        ok=True
    )

