from flask import Blueprint, render_template, request, redirect, url_for, current_app
from flask_login import login_required, current_user
from ...mailer import send_admin_email

bp = Blueprint("recommendations", __name__, url_prefix="/recommendations")

@bp.route("/submit", methods=["GET", "POST"], endpoint="submit")
@login_required
def submit():
    if request.method == "POST":
        unit = (request.form.get("unit") or "").strip()
        subject = (request.form.get("subject") or "").strip()
        message = (request.form.get("message") or "").strip()

        if not subject or not message:
            return redirect(url_for("recommendations.submit",
                                    error="Subject and message are required."))

        # Compose the email to the admin
        email_subject = f"[Skynet DB] Recommendation from {current_user.username}: {subject}"
        email_body = (
            f"New recommendation submitted.\n\n"
            f"From user: {current_user.username}\n"
            f"Unit: {unit or '(not provided)'}\n\n"
            f"Subject: {subject}\n\n"
            f"Message:\n{message}\n"
        )

        # Send email (uses your SMTP settings in Config)
        send_admin_email(current_app, email_subject, email_body)

        # Show confirmation to the user
        return redirect(url_for("recommendations.submit",
                                message="Your recommendation was sent. Responses usually take 48–72 hours."))

    # GET
    return render_template("submit_recommendations.html",
                           error=request.args.get("error", ""),
                           message=request.args.get("message", ""))
