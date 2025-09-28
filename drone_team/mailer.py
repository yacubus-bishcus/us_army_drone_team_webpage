# drone_team/mailer.py
# Handles emailing (recommendations, drone team applications, user registrations)
import smtplib
from email.message import EmailMessage

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

def send_admin_email(app, subject, body):
    try:
        msg = EmailMessage()
        msg["From"] = app.config["MAIL_USERNAME"]
        msg["To"] = app.config["ADMIN_EMAIL"]
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(app.config["MAIL_SERVER"], app.config["MAIL_PORT"]) as s:
            if app.config["MAIL_USE_TLS"]:
                s.starttls()
            if app.config["MAIL_USERNAME"] and app.config["MAIL_PASSWORD"]:
                s.login(app.config["MAIL_USERNAME"], app.config["MAIL_PASSWORD"])
            s.send_message(msg)
        print("[MAIL] Admin email sent.")
    except Exception as e:
        print("[MAIL ERROR]", e)
        print("Subject:", subject)
        print("Body:\n", body)
