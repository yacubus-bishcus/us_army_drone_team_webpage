# drone_team/services/team.py 
import csv
from pathlib import Path
from datetime import datetime
from drone_team import mailer 
import mimetypes 

ATTACHMENT_HARD_LIMIT_MB = 20 # typical email caps 

HEADERS = [
    "app_id", "created_at", "username",
    "name", "unit", "email", "phone",
    "years_experience", "primary_platforms", "skills",
    "availability", "statement", "video_path"
]

def _data_dir(app) -> Path:
    base = Path(app.config.get("DATA_DIR", app.instance_path)) / "data"
    base.mkdir(parents=True, exist_ok=True)
    return base

def _files_dir(app) -> Path:
    base = Path(app.config.get("DATA_DIR", app.instance_path)) / "files"
    base.mkdir(parents=True, exist_ok=True)
    return base

def videos_dir(app) -> Path:
    # store under instance/data/files/videos
    return _files_dir(app) / "videos"

def apps_csv(app) -> Path:
    return _data_dir(app) / "drone_team_apps.csv"

def _ensure_csv(app):
    p = apps_csv(app)
    if not p.exists():
        with p.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(HEADERS)
    return p

def append_application(app, row: dict):
    p = _ensure_csv(app)
    row_out = {
        "app_id": row.get("app_id",""),
        "created_at": datetime.utcnow().isoformat(timespec="seconds"),
        "username": row.get("username",""),
        "name": row.get("name",""),
        "unit": row.get("unit",""),
        "email": row.get("email",""),
        "phone": row.get("phone",""),
        "years_experience": row.get("years_experience",""),
        "primary_platforms": row.get("primary_platforms",""),
        "skills": row.get("skills",""),
        "availability": row.get("availability",""),
        "statement": row.get("statement",""),
        "video_path": row.get("video_path",""),
    }
    with p.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HEADERS)
        w.writerow(row_out)

## EMAILS applications to drone team email 
def _format_app_email_body(row: dict) -> str:
    lines = [
        "New US Army Drone Team Application",
        "=================================",
        f"Submitted: {row.get('created_at','') or datetime.utcnow().isoformat(timespec='seconds')}",
        f"Applicant: {row.get('name','')} (user: {row.get('username','')})",
        f"Grade: {row.get('grade','')}",
        f"Unit: {row.get('unit','')}",
        f"Email: {row.get('email','')}",
        f"Phone: {row.get('phone','')}",
        f"Years Experience: {row.get('years_experience','')}",
        f"Primary Platforms: {row.get('primary_platforms','')}",
        f"Skills: {row.get('skills','')}",
        f"Availability (next 12 months):",
        f"  Deploying: {row.get('deploying_12mo','')}",
        f"  Paternity/Maternity Leave: {row.get('parental_leave_12mo')}",
        f"  TDY Availability / Restrictions: {row.get('tdy_restrictions') or 'None provided'}",
        "",
        "Statement:",
        row.get("statement","(none)"),
        "",
        f"Application ID: {row.get('app_id','')}",
    ]
    # Add note about video location if not attaching
    if row.get("video_path"):
        lines += ["", f"Video: {row['video_path']} (on server)"]
    return "\n".join(lines)

def _video_attachment_tuple(app, video_rel_path: str):
    """
    Return (filename, mimetype, bytes) for attaching to email,
    or (None, None, None) if file missing or too large.
    """
    if not video_rel_path:
        return (None, None, None)

    # Your uploads go under instance/data/files/videos/<file>
    try:
        from .team import videos_dir  # reuse your existing videos_dir
    except Exception:
        # fallback: instance/data/files/videos
        base = Path(app.config.get("DATA_DIR", app.instance_path)) / "files" / "videos"
        def videos_dir(_): return base

    fpath = videos_dir(app) / Path(video_rel_path).name
    if not fpath.exists():
        app.logger.warning("Video not found for email attach: %s", fpath)
        return (None, None, None)

    # size check (skip large attachments)
    size_mb = fpath.stat().st_size / (1024 * 1024)
    if size_mb > ATTACHMENT_HARD_LIMIT_MB:
        app.logger.info("Skipping attach (%.1f MB exceeds limit %.1f MB): %s",
                        size_mb, ATTACHMENT_HARD_LIMIT_MB, fpath)
        return (None, None, None)

    ctype, _ = mimetypes.guess_type(fpath.name)
    mimetype = ctype or "application/octet-stream"
    return (fpath.name, mimetype, fpath.read_bytes())

def email_application_via_mailer(app, row: dict):
    """
    Build the message and delegate sending to your existing mailer.py
    """
    to_addr = app.config.get("MAIL_USERNAME")
    if not to_addr:
        app.logger.warning("DRONE_TEAM_EMAIL not configured; skipping email")
        return

    subject = f"[drone_team] Drone Team Application — {row.get('name','Applicant')}"
    body = _format_app_email_body(row)

    # Try to attach the video if reasonably small
    filename, mimetype, blob = _video_attachment_tuple(app, row.get("video_path") or "")
    attachments = []
    if filename and blob:
        attachments.append((filename, mimetype, blob))

    # ---- Call your mailer (pick the option that matches your mailer.py) ----
    # Option A: your mailer exposes a simple function:
    #   mailer.send_email(app, to=..., subject=..., body=..., attachments=[(name, mimetype, bytes)], cc=None, bcc=None)
    if hasattr(mailer, "send_email"):
        mailer.send_email(
            app,
            to=[to_addr],           # list or string, depending on your mailer
            subject=subject,
            body=body,
            attachments=attachments
        )
        return

    # Option B: your mailer exposes a Mailer class with .send(...)
    if hasattr(mailer, "Mailer"):
        m = mailer.Mailer(app)     # or Mailer.from_app(app) if that’s your API
        m.send(
            to=[to_addr],
            subject=subject,
            body=body,
            attachments=attachments
        )
        return

    # Option C: adapter (see below) if your API is different
    raise RuntimeError("mailer.py does not expose send_email(app, ...) or Mailer.send(...). Add a small adapter.")
