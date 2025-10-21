# drone_team/config.py
import os, sys
from pathlib import Path

# --- Helpers
def strtobool(s: str, default=False):
    return (s or str(default)).lower() in {"1","true","t","yes","y","on"}

def _sandbox_enabled():
    return strtobool(os.getenv("SANDBOX_DATA_MODE", "0"))

def _sandbox_sqlite_url():
    return os.getenv("SANDBOX_SQLITE_URL", "sqlite:///drone_team_debug.db")

# --- DB URL normalization
def _normalized_db_uri():
    if _sandbox_enabled():
        return _sandbox_sqlite_url()

    url = os.getenv("DATABASE_URL")
    if url:
        # Normalize scheme for SQLAlchemy 2.x + psycopg 3
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        # Ensure SSL if not explicitly given
        if "sslmode=" not in url:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}sslmode=require"
        return url
    # Fallback to SQLite
    return "sqlite:///drone_team.db"

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = _normalized_db_uri()
    SQLALCHEMY_TRACKMODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_size": int(os.getenv("DB_POOL_SIZE", "5")),     # per worker
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "5")),
        "pool_timeout": int(os.getenv("DB_POOL_TIMEOUT", "30")),
    }
    BASE_DIR   = Path(__file__).resolve().parent.parent
    DATA_DIR   = os.getenv("DATA_DIR", str(BASE_DIR / "data"))
    SANDBOX_DATA_MODE = _sandbox_enabled()
    SANDBOX_SQLITE_URL = _sandbox_sqlite_url()

    # Calendar Settings 
    GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "")
    TIMEZONE = os.getenv("APP_TIMEZONE", "America/Chicago")

    # Mail Settings 
    EMAIL_AVAILABLE     = os.getenv("EMAIL_AVAILABLE", "1").lower() in ("1", "true", "yes") 
    MAIL_SERVER         = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT           = int(os.getenv("MAIL_PORT", "587"))
    MAIL_USE_TLS        = os.getenv("MAIL_USE_TLS", "1").lower() in ("1", "true", "yes")
    MAIL_USERNAME       = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD       = os.getenv("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER") or os.environ.get("MAIL_USERNAME"),
    # allow only these email domains to self-register
    ALLOWED_SIGNUP_DOMAINS = os.getenv("ALLOWED_SIGNUP_DOMAINS", "army.mil").split(",")


    # Admin Credentials 
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
    ADMIN_EMAIL   = os.getenv("ADMIN_EMAIL")
    ADMIN_INITIAL_PASSWORD  = os.getenv("ADMIN_INITIAL_PASSWORD")

    # Cookies & sessions
    APP_ENV = os.getenv("APP_ENV", "development").lower()  # "production" in PaaS
    PREFERRED_URL_SCHEME = "https" if APP_ENV == "production" else "http"

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = (APP_ENV == "production")
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = (APP_ENV == "production")
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 7  # 7 days (seconds)

    # Content Restrictions
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(25 * 1024 * 1024)))

    # Velocidrone Integration
    VELOCIDRONE_LOGIN_URL = os.getenv("VELOCIDRONE_LOGIN_URL", "").strip()
    VELOCIDRONE_PASSCODE = os.getenv("VELOCIDRONE_PASSCODE")
    VELOCIDRONE_SESSION_TTL = int(os.getenv("VELOCIDRONE_SESSION_TTL", "120"))
    
# ========== Secret Validation ==========
def validate_required_env():
    required = {
        "SECRET_KEY": Config.SECRET_KEY,
        "ADMIN_USERNAME": Config.ADMIN_USERNAME,
        "ADMIN_EMAIL": Config.ADMIN_EMAIL,
        "ADMIN_INITIAL_PASSWORD": Config.ADMIN_INITIAL_PASSWORD,
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