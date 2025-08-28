from flask import Blueprint, render_template, request, redirect, url_for, current_app, abort
from flask_login import login_user, logout_user, current_user
from werkzeug.security import check_password_hash
from ..db import get_user_by_username, create_user, _db
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
        email    = (request.form.get("email") or "").strip()
        reason   = (request.form.get("reason") or "").strip()
        if not username or not email:
            return redirect(url_for("auth.register_page", error="Username and email are required."))
        if get_user_by_username(current_app, username):
            return redirect(url_for("auth.login_page", message="Account already exists. Please sign in."))
        token = secrets.token_urlsafe(24)
        con = _db(current_app)
        with con:
            con.execute("""
                INSERT INTO pending_users (username,email,reason,token,status,created_at)
                VALUES (?, ?, ?, ?, 'pending', datetime('now'))
                ON CONFLICT(username) DO UPDATE SET
                    email=excluded.email, reason=excluded.reason, token=excluded.token,
                    status='pending', created_at=datetime('now'), decided_at=NULL
            """, (username, email, reason, token))
        con.close()
        approve_url = url_for("admin.approve_user", token=token, _external=True)
        deny_url    = url_for("admin.deny_user", token=token, _external=True)
        subject = f"[Skynet DB] Access request: {username}"
        body = (f"User requested access.\n\nUsername: {username}\nEmail: {email}\nReason:\n{reason}\n\n"
                f"Approve: {approve_url}\nDeny: {deny_url}\n\n(You must be signed in as an admin to use these links.)")
        send_admin_email(current_app, subject, body)
        return redirect(url_for("auth.login_page", message="Request submitted. The admin will review your request."))
    return render_template("auth_request_access.html", error=request.args.get("error",""))