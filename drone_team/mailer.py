# drone_team/mailer.py
# Handles emailing (recommendations, drone team applications, user registrations)
from email.message import EmailMessage
import os, smtplib, time, ssl, traceback
from flask import current_app

try:
    from flask_mail import Mail, Message
    HAS_FLASK_MAIL = True
except Exception:
    HAS_FLASK_MAIL = False

def _admin_recipients(app):
    # Prefer a comma-separated env/config value, else ADMIN_EMAIL
    rcpts = (
        app.config.get("MAIL_ADMIN_RECIPIENTS")
        or os.environ.get("MAIL_ADMIN_RECIPIENTS")
        or app.config.get("ADMIN_EMAIL")
        or os.environ.get("ADMIN_EMAIL")
    )
    if not rcpts:
        return []
    return [r.strip() for r in rcpts.split(",") if r.strip()]

def _smtp_send(app, msg: EmailMessage):
    with smtplib.SMTP(app.config["MAIL_SERVER"], app.config["MAIL_PORT"]) as s:
        if app.config.get("MAIL_USE_TLS", True):
            s.starttls()
        if app.config.get("MAIL_USERNAME") and app.config.get("MAIL_PASSWORD"):
            s.login(app.config["MAIL_USERNAME"], app.config["MAIL_PASSWORD"])
        s.send_message(msg)

def send_email(app, to, subject, body, attachments=None, cc=None, bcc=None):
    """
    Generic sender with optional attachments.
    - to/cc/bcc: str or list[str]
    - attachments: list of (filename, mimetype, bytes)
    """
    def _as_list(x):
        if not x: return []
        return x if isinstance(x, (list, tuple)) else [x]

    msg = EmailMessage()
    msg["From"] = app.config.get("MAIL_FROM") or app.config.get("MAIL_USERNAME")
    to_list = _as_list(to)
    cc_list = _as_list(cc)
    bcc_list = _as_list(bcc)

    msg["To"] = ", ".join(to_list)
    if cc_list:  msg["Cc"]  = ", ".join(cc_list)
    if bcc_list: msg["Bcc"] = ", ".join(bcc_list)

    msg["Subject"] = subject
    msg.set_content(body)

    for att in (attachments or []):
        name, mimetype, blob = att
        maintype, subtype = (mimetype.split("/", 1) if "/" in mimetype else ("application", "octet-stream"))
        msg.add_attachment(blob, maintype=maintype, subtype=subtype, filename=name)

    _smtp_send(app, msg)

def send_admin_email(app, subject: str, body: str, *, max_retries: int = 2, backoff_sec: float = 1.5) -> bool:
    recipients = _admin_recipients(app)
    if not recipients:
        app.logger.warning("MAIL: No admin recipients configured (MAIL_ADMIN_RECIPIENTS / ADMIN_EMAIL).")
        return False

    sender = (
        app.config.get("MAIL_DEFAULT_SENDER")
        or os.environ.get("MAIL_DEFAULT_SENDER")
        or app.config.get("MAIL_USERNAME")
        or os.environ.get("MAIL_USERNAME")
    )
# Prefer Flask-Mail if present and configured
    if HAS_FLASK_MAIL:
        try:
            mail = app.extensions.get("mail")
            if mail is None:
                # lazy init if not created elsewhere
                mail = Mail(app)

            msg = Message(subject=subject, recipients=recipients, body=body, sender=sender)

            # Simple retry with backoff
            for attempt in range(1, max_retries + 1):
                try:
                    with mail.connect() as conn:
                        conn.send(msg)
                    return True
                except Exception as e:
                    app.logger.error("MAIL (Flask-Mail) attempt %s failed: %s", attempt, e, exc_info=True)
                    if attempt < max_retries:
                        time.sleep(backoff_sec * attempt)
            return False

        except Exception as e:
            app.logger.error("MAIL (Flask-Mail setup) failed: %s", e, exc_info=True)
            # fall through to smtplib fallback

    # Fallback: raw smtplib (TLS or SSL depending on config)
    try:
        host = app.config.get("MAIL_SERVER", "localhost")
        port = int(app.config.get("MAIL_PORT", "587"))
        username = app.config.get("MAIL_USERNAME")
        password = app.config.get("MAIL_PASSWORD")
        use_tls = str(app.config.get("MAIL_USE_TLS", "false")).lower() in {"1","true","t","yes","y","on"}
        use_ssl = str(app.config.get("MAIL_USE_SSL", "false")).lower() in {"1","true","t","yes","y","on"}

        # Build RFC email
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = sender or (username or "no-reply@localhost")
        msg["To"] = ", ".join(recipients)
        msg.set_content(body)

        for attempt in range(1, max_retries + 1):
            try:
                if use_ssl:
                    context = ssl.create_default_context()
                    with smtplib.SMTP_SSL(host=host, port=port, context=context, timeout=15) as server:
                        if username and password:
                            server.login(username, password)
                        server.send_message(msg)
                else:
                    with smtplib.SMTP(host=host, port=port, timeout=15) as server:
                        if use_tls:
                            server.starttls(context=ssl.create_default_context())
                        if username and password:
                            server.login(username, password)
                        server.send_message(msg)
                return True
            except Exception as e:
                app.logger.error("MAIL (smtplib) attempt %s failed: %s", attempt, e, exc_info=True)
                if attempt < max_retries:
                    time.sleep(backoff_sec * attempt)
        return False

    except Exception as e:
        app.logger.error("MAIL (smtplib setup) failed: %s\n%s", e, traceback.format_exc(), exc_info=True)
        return False
