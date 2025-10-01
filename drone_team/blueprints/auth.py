#drone_team/blueprints/auth.py
from flask import Blueprint, render_template, request, redirect, url_for, current_app, flash
from flask_login import login_user, logout_user, current_user
from werkzeug.security import check_password_hash
from sqlalchemy import text 
from ..db import get_user_by_username, get_engine
from ..mailer import send_admin_email
import secrets

bp = Blueprint("auth", __name__)

@bp.route("/login", methods=["GET","POST"])
def login_page():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = get_user_by_username(current_app, username)
        if not user or not check_password_hash(user.password_hash, password):
            return redirect(url_for("auth.login_page", error="Invalid credentials."))
        login_user(user, remember=True)
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
                """),
                {"u": username, "e": email, "s": sponsor_email, "t": token},
            )

        # UPDATE status
        with engine.begin() as con:
            con.execute(
                text("""
                    UPDATE pending_users
                    SET status = :st, decided_at = CURRENT_TIMESTAMP
                    WHERE token = :t
                """),
                {"st": "approved", "t": token},
            )
        

        approve_url = url_for("admin.approve_user", token=token, _external=True)
        deny_url    = url_for("admin.deny_user", token=token, _external=True)
        subject = f"[drone_team DB] Access request: {username}"
        body = (f"User requested access.\n\nUsername: {username}\nEmail: {email}\nSponsor Email:\n{sponsor_email}\n\n"
                f"Approve: {approve_url}\nDeny: {deny_url}\n\n(You must be signed in as an admin to use these links.)")
        send_admin_email(current_app, subject, body)
        return redirect(url_for("auth.login_page", message="Request submitted. The admin will review your request."))
    return render_template("auth_request_access.html", error=request.args.get("error",""))