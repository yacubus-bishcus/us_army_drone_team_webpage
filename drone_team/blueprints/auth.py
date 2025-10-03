#drone_team/blueprints/auth.py
from flask import Blueprint, render_template, request, redirect, url_for, current_app, flash
from flask_login import login_user, logout_user, current_user
from werkzeug.security import check_password_hash
from sqlalchemy import text
from datetime import datetime
from ..db import (
    get_user_by_username,
    get_user_by_email,
    get_engine,
    create_password_reset_token,
    get_password_reset_request,
    mark_password_reset_used,
    update_user_password,
)
from ..mailer import (
    send_admin_email,
    send_admin_email_sendgrid,
    send_email,
    send_email_sendgrid,
)
import secrets
import threading
import os

bp = Blueprint("auth", __name__)


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        identifier = (request.form.get("identifier") or "").strip()
        if not identifier:
            flash("Please enter your username or email address.", "error")
            return redirect(url_for("auth.forgot_password"))

        user = get_user_by_username(current_app, identifier)
        if user is None and "@" in identifier:
            user = get_user_by_email(current_app, identifier)

        # Always show the generic message to avoid leaking which accounts exist
        generic_message = (
            "If an account matches the details provided, a password reset email "
            "has been sent with further instructions."
        )

        if not user:
            flash(generic_message, "info")
            return redirect(url_for("auth.forgot_password"))

        if not getattr(user, "email", None):
            flash(
                "We do not have an email address on file for this account. Please contact an administrator.",
                "error",
            )
            return redirect(url_for("auth.forgot_password"))

        token = create_password_reset_token(current_app, user.id)
        reset_url = url_for("auth.reset_password", token=token, _external=True)
        subject = "[drone_team DB] Password reset instructions"
        body = (
            f"Hello {user.username},\n\n"
            "A request was received to reset the password for your drone_team account.\n\n"
            f"Use the link below to set a new password. This link will expire in one hour.\n{reset_url}\n\n"
            "If you did not request this change, you can safely ignore this email."
        )

        def _send_user_email(app, to_email, subject, body):
            with app.app_context():
                try:
                    if os.environ.get("EMAIL_AVAILABLE"):
                        send_email(app, to_email, subject, body)
                    else:
                        send_email_sendgrid(app, to_email, subject, body)
                except Exception as exc:
                    app.logger.error("MAIL: Failed to send password reset email: %s", exc, exc_info=True)

        threading.Thread(
            target=_send_user_email,
            args=(current_app._get_current_object(), user.email, subject, body),
            daemon=True,
        ).start()

        flash(generic_message, "info")
        return redirect(url_for("auth.forgot_password"))

    return render_template("auth_forgot_password.html")


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    record = get_password_reset_request(current_app, token)
    now = datetime.utcnow()
    invalid_reason = None

    if not record:
        invalid_reason = "Invalid password reset link."
    else:
        expires_at = record.get("expires_at")
        used_at = record.get("used_at")
        if not expires_at or expires_at < now:
            invalid_reason = "This password reset link has expired."
        elif used_at is not None:
            invalid_reason = "This password reset link has already been used."

    if request.method == "POST" and not invalid_reason:
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm_password") or ""

        if len(password) < 8:
            flash("Passwords must be at least 8 characters long.", "error")
        elif password != confirm:
            flash("Passwords do not match.", "error")
        else:
            update_user_password(current_app, record["user_id"], password)
            mark_password_reset_used(current_app, token)
            flash("Your password has been updated. You can now sign in with the new password.", "info")
            return redirect(url_for("auth.login_page"))

    return render_template(
        "auth_reset_password.html",
        invalid_reason=invalid_reason,
    )


def _async_send(app, subject, body):
    # Ensure app context for logging / config
    with app.app_context():
        ok = send_admin_email(app, subject, body)
        if not ok:
            app.logger.error("MAIL: send_admin_email returned False (email not sent).")

def _async_send_sendgrid(app, subject, body):
    with app.app_context():
        ok = send_admin_email_sendgrid(app, subject, body)
        if not ok:
            app.logger.error("SendGrid mail failed (returned False).")


@bp.route("/login", methods=["GET","POST"])
def login_page():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = get_user_by_username(current_app, username)
        if not user or not check_password_hash(user.password_hash, password):
            return redirect(url_for("auth.login_page", error="Invalid credentials."))
        login_user(user, remember=True)
        if getattr(user, "must_change_password", False):
            return redirect(
                url_for(
                    "profile.view",
                    force_password_change=1,
                    message="Temporary password detected. Please update it now.",
                )
            )
        return redirect(request.args.get("next") or url_for("core.home", message=f"Welcome, {user.username}!"))
    return render_template("auth_login.html",
                           error=request.args.get("error",""),
                           message=request.args.get("message",""))

@bp.route("/logout")
def logout_page():
    if current_user.is_authenticated:
        logout_user()
    return redirect(url_for("core.home", message="Signed out."))

@bp.route("/register", methods=["GET","POST"])
def register_page():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip()
        sponsor_email = (request.form.get("sponsor_email") or "").strip() 
        sponsor_email_lc = sponsor_email.lower() 
        email_lc = email.lower() 
        allowed = current_app.config.get("ALLOWED_SIGNUP_DOMAINS", ["army.mil"])
        if not (
            any(email_lc.endswith(f"@{d.lower()}") for d in allowed) or 
            any(sponsor_email_lc.endswith(f"@{d.lower()}") for d in allowed)
        ):
            flash("Either primary email or sponsor email must have army.mil domain.", "error")
            return redirect(url_for("auth.register_page"))

        if not username or not email:
            return redirect(url_for("auth.register_page", error="Username and email are required."))
        if get_user_by_username(current_app, username):
            return redirect(url_for("auth.login_page", message="Account already exists. Please sign in."))
        token = secrets.token_urlsafe(24)

        engine = get_engine(current_app)
        sql = text("SELECT id, username, email, sponsor_email, token, status, created_at, decided_at FROM pending_users WHERE token = :t")
        with engine.connect() as con:
            row = con.execute(sql, {"t": token}).mappings().first()

        # INSERT
        with engine.begin() as con:
            con.execute(
                text("""
                    INSERT INTO pending_users (username, email, sponsor_email, token, status, created_at)
                    VALUES (:u, :e, :s, :t, 'pending', CURRENT_TIMESTAMP)
                    ON CONFLICT (username)
                    DO UPDATE SET
                        email = EXCLUDED.email,
                        sponsor_email = EXCLUDED.sponsor_email,
                        token = EXCLUDED.token,
                        status = 'pending',
                        created_at = CURRENT_TIMESTAMP,
                        decided_at = NULL
                """),
                {"u": username, "e": email, "s": sponsor_email, "t": token}
            )


            flash("Your registration request has been updated. Please check your email for approval instructions.", "info")

        approve_url = url_for("admin.approve_user", token=token, _external=True)
        deny_url    = url_for("admin.deny_user", token=token, _external=True)
        subject = f"[drone_team DB] Access request: {username}"
        body = (f"User requested access.\n\nUsername: {username}\nEmail: {email}\nSponsor Email:\n{sponsor_email}\n\n"
                f"Approve: {approve_url}\nDeny: {deny_url}\n\n(You must be signed in as an admin to use these links.)")
        
        # Fire off email in the background 
        if os.environ.get('EMAIL_AVAILABLE'):
            threading.Thread(target=_async_send, args=(current_app._get_current_object(), subject, body), daemon=True).start() 
        else:
            threading.Thread(target=_async_send_sendgrid, args=(current_app._get_current_object(), subject, body), daemon=True).start() 

        return redirect(url_for("auth.login_page", message="Request submitted. The admin will review your request."))
    return render_template("auth_request_access.html", error=request.args.get("error",""))