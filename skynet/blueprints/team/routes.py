import uuid
from pathlib import Path
from werkzeug.utils import secure_filename
from flask import render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from . import team_bp
from ...services import team as svc

ALLOWED_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv"}

# --- LANDING PAGE ("/") ---
@team_bp.route("/", methods=["GET"])
@login_required
def index():
    summary = (
        "The US Army Drone Team advances small UAS tactics, training, and technology across the force. "
        "We evaluate platforms and software, run rapid experiments, publish TTPs, and support units with "
        "best practices for ISR, EW resilience, and swarming/attritable concepts."
    )

    hierarchy = {
        "Overseer": ["Col Ryan"],
        "Executive Officer": ["CPT Bickus"],
        "Team Captain": ["SSG Smith"],
        "Vice Captain": ["Tyler Booth"],
        "Team Leads": ["Sean Bradley", "Aaron Terran"],
    }

    operators = [
        "SSG Smith", "Tyler Booth", "SGT Cantu", "Joe Eason", "Sam Fox",
        "Ryan Johnson", "Jacob Loyd", "SSG Schiller", "SSG Ringsmuth"
    ]

    # Pass calendar config to the template for the iframe embed
    cal_id = current_app.config.get("GOOGLE_CALENDAR_ID", "").strip()
    tz = current_app.config.get("TIMEZONE", "America/New_York").strip()

    return render_template(
        "team_index.html",
        summary=summary,
        hierarchy=hierarchy,
        operators=operators,
        cal_id=cal_id,
        tz=tz,
    )

# --- FULL CALENDAR PAGE ---
@team_bp.route("/calendar", methods=["GET"])
@login_required
def calendar():
    cal_id = current_app.config.get("GOOGLE_CALENDAR_ID", "").strip()
    tz = current_app.config.get("TIMEZONE", "America/New_York").strip()
    return render_template("team_calendar.html", cal_id=cal_id, tz=tz)

# --- APPLICATION FORM ("/apply") ---
@team_bp.route("/apply", methods=["GET", "POST"], endpoint="apply")
@login_required
def apply():
    if request.method == "POST":
        data = {
            "app_id": str(uuid.uuid4()),
            "username": current_user.username if current_user.is_authenticated else "anonymous",
            "name": (request.form.get("name") or "").strip(),
            "unit": (request.form.get("unit") or "").strip(),
            "email": (request.form.get("email") or "").strip(),
            "phone": (request.form.get("phone") or "").strip(),
            "years_experience": (request.form.get("years_experience") or "").strip(),
            "primary_platforms": (request.form.get("primary_platforms") or "").strip(),
            "skills": (request.form.get("skills") or "").strip(),
            "availability": (request.form.get("availability") or "").strip(),
            "statement": (request.form.get("statement") or "").strip(),
        }

        # Basic validation
        missing = [k for k in ("name", "unit", "email") if not data[k]]
        if missing:
            flash(f"Missing required fields: {', '.join(missing)}", "error")
            return redirect(url_for("team.apply"))

        # Optional video upload
        video = request.files.get("video")
        saved_rel = ""
        if video and video.filename:
            ext = Path(video.filename).suffix.lower()
            if ext not in ALLOWED_VIDEO_EXTS:
                flash("Invalid video type. Allowed: mp4, mov, avi, mkv", "error")
                return redirect(url_for("team.apply"))

            vid_dir = svc.videos_dir(current_app)
            vid_dir.mkdir(parents=True, exist_ok=True)
            fname = f"{data['app_id']}_{secure_filename(video.filename)}"
            (vid_dir / fname).write_bytes(video.read())
            saved_rel = f"videos/{fname}"

        data["video_path"] = saved_rel

        # Save + email
        saved = svc.append_application(current_app, data)
        try:
            svc.email_application_via_mailer(current_app, saved)
        except Exception as e:
            current_app.logger.exception("Failed to email application: %s", e)

        flash("Application submitted. Thank you!", "success")
        return redirect(url_for("team.apply"))

    # GET
    return render_template("team_apply.html")
