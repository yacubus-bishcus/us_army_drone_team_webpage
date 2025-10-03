#drone_team/blueprints/profile.py
from flask import Blueprint, render_template, request, redirect, url_for, current_app
from flask_login import login_required, current_user
from werkzeug.security import check_password_hash
from ..db import update_user_password
from ..services import aars as aars_svc

bp = Blueprint("profile", __name__)

@bp.route("/profile", methods=["GET", "POST"])
@login_required
def view():
    message = request.args.get("message", "")
    error   = request.args.get("error", "")
    raw_force_change = request.args.get("force_password_change")
    force_change = str(raw_force_change).lower() in {"1", "true", "yes", "on"}

    # Quick stats (no schema changes): number of AARs authored
    df = aars_svc.load_df(current_app)
    my_count = 0
    if "username" in df.columns:
        my_count = int((df["username"].astype(str) == current_user.username).sum())

    if request.method == "POST":
        # Change password flow
        curr = request.form.get("current_password", "") or ""
        new  = request.form.get("new_password", "") or ""
        conf = request.form.get("confirm_password", "") or ""

        # Basic validations
        if not curr or not new or not conf:
            return redirect(url_for("profile.view", error="All password fields are required."))
        if new != conf:
            return redirect(url_for("profile.view", error="New passwords do not match."))
        if len(new) < 8:
            return redirect(url_for("profile.view", error="New password must be at least 8 characters."))

        # Verify current password
        if not check_password_hash(current_user.password_hash, curr):
            return redirect(url_for("profile.view", error="Current password is incorrect."))

        # Update password in DB + in-memory user
        update_user_password(current_app, current_user.id, new)
        # Refresh in-memory password hash so future checks use the new one
        from ..db import get_user_by_id
        refreshed = get_user_by_id(current_app, current_user.id)
        current_user.password_hash = refreshed.password_hash  # update session model
        current_user.must_change_password = refreshed.must_change_password

        return redirect(url_for("profile.view", message="Password updated successfully."))

    if getattr(current_user, "must_change_password", False) and not force_change:
        force_change = True
        if not message:
            message = "Please change your temporary password before continuing."

    return render_template(
        "profile.html",
        message=message,
        error=error,
        username=current_user.username,
        my_aar_count=my_count,
        force_password_change=force_change,
    )
