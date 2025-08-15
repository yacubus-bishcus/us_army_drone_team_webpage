import smtplib
from email.message import EmailMessage

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
