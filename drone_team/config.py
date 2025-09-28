# drone_team/config.py
import os, sys
from pathlib import Path

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///drone_team.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    BASE_DIR   = Path(__file__).resolve().parent.parent
    DATA_DIR   = os.getenv("DATA_DIR", str(BASE_DIR / "data"))

    # Calendar Settings 
    GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "")
    TIMEZONE = os.getenv("APP_TIMEZONE", "America/Chicago")

    # Mail Settings 
    MAIL_SERVER   = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT     = int(os.getenv("MAIL_PORT", "587"))
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "1").lower() in ("1", "true", "yes")
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")

    # Admin Credentials 
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
    ADMIN_EMAIL   = os.getenv("ADMIN_EMAIL")
    ADMIN_INITIAL_PASSWORD  = os.getenv("ADMIN_INITIAL_PASSWORD")

    # Cookies & sessions
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"  # or "Strict"
    SESSION_COOKIE_SECURE = True     # set True in HTTPS (prod)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = True    # HTTPS only in prod
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 7  # 7 days (seconds)

    # Content Restrictions 
    MAX_CONTENT_LENGTH = 25 * 1024 * 1024  # 25 MB upload cap

# ========== Secret Validation ==========
def validate_required_env():
    """Call this AFTER load_dotenv() and app.config.from_object(Config)."""
    required = {
        "SECRET_KEY": Config.SECRET_KEY,
        "ADMIN_USERNAME": Config.ADMIN_USERNAME,
        "ADMIN_EMAIL": Config.ADMIN_EMAIL,
        "ADMIN_INITIAL_PASSWORD": Config.ADMIN_INITIAL_PASSWORD,
        "MAIL_USERNAME": Config.MAIL_USERNAME,
        "MAIL_PASSWORD": Config.MAIL_PASSWORD,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        env_path = Config.BASE_DIR / ".env"
        sys.stderr.write(
            "\n[ERROR] Missing required environment variables:\n"
            f"    {', '.join(missing)}\n"
            f"Checked environment and .env file here:\n"
            f"    {env_path}\n\n"
            "Please create/update your .env file with these variables.\n"
            "Example:\n"
            "-----------------------------------------\n"
            "SECRET_KEY=replace-with-a-long-random-string\n"
            "ADMIN_USERNAME=your_admin_user\n"
            "ADMIN_EMAIL=your@email.com\n"
            "ADMIN_INITIAL_PASSWORD=one-time-password\n"
            "MAIL_USERNAME=your_smtp_user\n"
            "MAIL_PASSWORD=your_smtp_password\n"
            "-----------------------------------------\n"
        )
        sys.exit(1)