#/drone_team/blueprints/team/routes.py
import uuid, os, threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from werkzeug.utils import secure_filename
from flask import render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user

from . import team_bp
from ...services import team as svc
from ...services import sheets as sheets_svc
from drone_team import mailer
from ...db import insert_team_application, get_latest_team_application_by_username

ALLOWED_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv"}

def _async_send(app, to, subject, body):
    # Ensure app context for logging / config
    with app.app_context():
        ok = mailer.send_email(app, to, subject, body)
        if not ok:
            app.logger.error("MAIL: send_email returned False (email not sent).")

def _async_send_sendgrid(app, to, subject, body):
    with app.app_context():
        ok = mailer.send_email_sendgrid(app, to, subject, body)
        if not ok:
            app.logger.error("SendGrid mail failed (returned False).")

# --- LANDING PAGE ("/") ---
_PASSCODE_RELEASE = datetime(2025, 10, 15, 9, 0, tzinfo=ZoneInfo("America/New_York"))


def _is_passcode_released(now: datetime | None = None) -> bool:
    tz = ZoneInfo("America/New_York")
    current = now.astimezone(tz) if now else datetime.now(tz)
    return current >= _PASSCODE_RELEASE


def _get_user_callsign(app, user) -> str:
    if not getattr(user, "is_authenticated", False):
        return ""

    username = getattr(user, "username", "")
    if not username:
        return ""

    try:
        row = get_latest_team_application_by_username(app, username)
    except Exception as exc:
        app.logger.exception("Failed to load team application for %s: %s", username, exc)
        return ""

    if not row:
        return ""

    return (row.get("callsign") or "").strip()


@team_bp.route("/", methods=["GET"])
@login_required
def index():
    summary = (
        "The US Army Drone Team drives unmanned aerial systems (UAS) innovation to ensure technological "
        "and operational dominance in modern warfare through national and international competitions. "
        "By recruiting and training the next generation of drone operators, the Army Drone Team advances "
        "tactical and technical capabilities aligned with the Army's Continuous Transformation Initiative. "
        "Apply now below to receive instructions on the Velocidrone closed track competition. Track password will be distributed no earlier than 15 October 2025."
        ' The official team SharePoint page can be found '
        '<a href="https://armyeitaas.sharepoint-mil.us/:u:/t/USArmyGoldenHawks/EZDhwGB7X9pNnu3rUfrio30BHdELBnK-iSsySi7YV4RwoQ?e=Sbwk9y" target="_blank">here</a>.'
    )

    hierarchy = {
        "OIC": ["CPT Bickus"],
        "NCOIC": ["SSG Smith"]
    }

    operators = [
        "SFC Aaron Teran", "Tyler Booth", "SGT Cantu",
        "CPT Ryan Johnson", "SSG Brandon Schiller", "SSG Stephen Ringsmuth", "SGT Jacob Loyd"
    ]

    # Pass calendar config to the template for the iframe embed
    cal_id = current_app.config.get("GOOGLE_CALENDAR_ID", "").strip()
    tz = current_app.config.get("TIMEZONE", "America/New_York").strip()

    user_callsign = _get_user_callsign(current_app, current_user)

    passcode_released = _is_passcode_released()
    velocidrone_passcode = ""
    if passcode_released:
        try:
            velocidrone_passcode = os.environ.get('VELOCIDRONE_PASSCODE', "PASSCODE Unavailable")
        except:
            current_app.logger.error("Velocidrone passcode unavailable.")

    return render_template(
        "team_index.html",
        summary=summary,
        hierarchy=hierarchy,
        operators=operators,
        cal_id=cal_id,
        tz=tz,
        user_callsign=user_callsign,
        passcode_released=passcode_released,
        velocidrone_passcode=velocidrone_passcode,
    )

    
# --- FULL CALENDAR PAGE ---
@team_bp.route("/calendar", methods=["GET"])
@login_required
def calendar():
    cal_id = current_app.config.get("GOOGLE_CALENDAR_ID", "").strip()
    tz = current_app.config.get("TIMEZONE", "America/New_York").strip()
    return render_template("team_calendar.html", cal_id=cal_id, tz=tz)


@team_bp.route("/faq", methods=["GET"])
@login_required
def faq():
    faqs = [
        {
            "question": "Will joining the US Army Drone Team be A Permanent Change of Station (PCS)?",
            "answer": (
                "No. The US Army Drone Team does not have TDA slots. Currently all team members are "
                'considered "At Large" members where any training and competition will be a TDY.'
            ),
        },
        {
            "question": "How many Soldiers will be selected to the US Army Drone Team? Will there be alternates?",
            "answer": (
                "20 Soldiers will be selected as primaries for the US Army Drone Team. There will be alternates, "
                "but only the 20 primaries will have training funded quarterly."
            ),
        },
        {
            "question": "How often will the Drone Team meet for training and competitions?",
            "answer": "The goal is to meet twice quarterly for training and competitions.",
        },
        {
            "question": "Is selection to the Drone Team only based on Velocidrone track performance?",
            "answer": (
                "No. While the track performance will be heavily weighted for consideration, other factors such as "
                "AFT score, Soldier Talent Profile, Interview answers, etc will be considered."
            ),
        },
    ]

    return render_template("team_faq.html", faqs=faqs)

# --- APPLICATION FORM ("/apply") ---
@team_bp.route("/apply", methods=["GET", "POST"], endpoint="apply")
@login_required
def apply():
    if request.method == "POST":
        data = {
            "app_id": str(uuid.uuid4()),
            "username": current_user.username if current_user.is_authenticated else "anonymous",
            "name": (request.form.get("name") or "").strip(),
            "grade": (request.form.get("grade") or "").strip(),
            "unit": (request.form.get("unit") or "").strip(),
            "callsign": (request.form.get("callsign") or "").strip(),
            "email": (request.form.get("email") or "").strip(),
            "phone": (request.form.get("phone") or "").strip(),
            "years_experience": (request.form.get("years_experience") or "").strip(),
            "primary_platforms": (request.form.get("primary_platforms") or "").strip(),
            "skills": (request.form.get("skills") or "").strip(),
            "deploying_12mo": (request.form.get("deploying_12mo", "N/A")),
            "parental_leave_12mo": (request.form.get("parental_leave_12mo", "N/A")),
            "tdy_restrictions": (request.form.get("tdy_restrictions") or "").strip(),
            "statement": (request.form.get("statement") or "").strip(),
        }

        # Basic validation
        missing = [k for k in ("name", "grade", "unit", "email", "callsign") if not data[k]]
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
        # Ensure we always pass a dict to the mailer
        row_for_email = saved if isinstance(saved, dict) else data 
        
        # Append data to google sheets 
        sheets_ok = True 
        try:
            sheets_svc.append_application_row(current_app, row_for_email)
        except Exception as e:
            sheets_ok = False 
            current_app.logger.exception("Failed to append to Google Sheet: %s", e)
            
        
        # 2) Write to Postgres (authoritative)
        db_ok = True
        try:
            insert_team_application(current_app, row_for_email)
        except Exception as e:
            db_ok = False
            current_app.logger.error("DB insert failed: %s", e)
            flash("We had trouble saving your application. Please try again.", "error")
            return render_template("team_apply.html", form=request.form)
        
        # UX messages based on dual-write result
        if db_ok and sheets_ok:
            flash("Application received!", "success")
        elif db_ok and not sheets_ok:
            flash("Application saved. (Sheet sync delayed—admin has your submission.)", "warning")
        else:
            # db_ok false path handled above with early return
            pass


        # --- Admin Email ---
        try:
            svc.email_application_via_mailer(current_app, row_for_email)
        except Exception as e:
            current_app.logger.exception("Failed to email application: %s", e)

        # --- Applicant confirmation email --- 
        subject_user = "US Army Drone Team -- Application Received"
        body_user = f"""Hi {data.get("name") or 'Applicant'},
        Thanks for applying to the US Army Drone Team. We've received your application and look
        forward to reviewing your Velocidrone performance. If you need help finding the track
        please refer to the information below or reach out to SSG Alwyne Smith with questions 
        at alwyne.a.smith2.mil@army.mil. The track will become available on 15 October 2025. You
        will received the track name and password no earlier than 150900OCT25.  
        
        Please check us out at our Microsoft Teams Sharepoint Page US Army Drone Team and 
        Channel with team code: 
        cy4otgm.

        v/r,
        US Army Drone Team
        """
        app = current_app._get_current_object() 
        if os.environ.get('EMAIL_AVAILABLE'):
            threading.Thread(target=_async_send, args=(app, data["email"], subject_user, body_user), daemon=True).start() 
        else:
            threading.Thread(target=_async_send_sendgrid, args=(app, data["email"], subject_user, body_user), daemon=True).start()

        flash("Application submitted. A confirmation email has been sent to you. Thank you!", "success")
        # return to team home page 
        return redirect(url_for("team.index"))

    # GET
    return render_template("team_apply.html")
