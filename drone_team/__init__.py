# drone_team/__init__.py
from flask import Flask, request, redirect
from flask_login import current_user
from dotenv import load_dotenv
from pathlib import Path
import os

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from .config import Config
from .extensions import login_manager, db as sqla_db, migrate
from .db import init_users_db, seed_admin_user, init_team_applications
from .services.uas import create_csv_if_missing
from .services.aars import create_aar_csv_if_missing
from .cli import register_cli

def create_app():
    load_dotenv()
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config.from_object(Config)

    sandbox_mode = app.config.get("SANDBOX_DATA_MODE", False)
    if sandbox_mode:
        app.logger.info("SANDBOX_DATA_MODE enabled; routing database work to SQLite and skipping external sinks")

    # ★ Prefer DATABASE_URL (Postgres) if provided and sandbox mode is off; otherwise keep SQLite behavior
    db_url_env = os.getenv("DATABASE_URL")
    if db_url_env and not sandbox_mode:
        # Config._normalized_db_uri already normalizes the URL, so no extra work needed
        pass
    else:
        # keep your existing SQLite path logic
        os.makedirs(app.instance_path, exist_ok=True)
        uri = app.config["SQLALCHEMY_DATABASE_URI"]
        if uri.startswith("sqlite:///"):
            db_path = uri[len("sqlite:///"):]
            if db_path == ":memory:":
                pass
            elif os.path.isabs(db_path):
                pass
            else:
                db_filename = os.path.basename(db_path) or "drone_team.db"
                db_path = os.path.join(app.instance_path, db_filename)
                app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + db_path

    app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)

    # Init Flask-SQLAlchemy & Alembic
    sqla_db.init_app(app)
    migrate.init_app(app, sqla_db)
    from . import models  # ensure models are registered

    # Init other extensions
    login_manager.init_app(app)

    # Ensure data dirs/files that the app uses
    Path(app.config["DATA_DIR"]).mkdir(parents=True, exist_ok=True)

    # ★ Create/verify the auth tables in whichever DB we're pointed at (SQLite locally / Postgres in prod)
    init_users_db(app)
    init_team_applications(app)
    seed_admin_user(app)

    # App data bootstraps
    create_csv_if_missing(app)
    from .services.aars import create_aar_csv_if_missing, normalize_aar_csv_formats
    create_aar_csv_if_missing(app)
    normalize_aar_csv_formats(app)

    # Register blueprints
    from .blueprints.core import bp as core_bp
    from .blueprints.auth import bp as auth_bp
    from .blueprints.admin import bp as admin_bp
    from .blueprints.compare import compare_bp
    from .blueprints.search import search_bp
    from .blueprints.aars import bp as aars_bp
    from .blueprints.team import team_bp
    from .blueprints.news import news_bp
    from .blueprints.software import software_bp
    from .blueprints.profile import bp as profile_bp
    from .blueprints.recommendations import bp as recs_bp
    from .blueprints.debug import bp as debug_bp 

    app.register_blueprint(core_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(compare_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(aars_bp)
    app.register_blueprint(team_bp)
    app.register_blueprint(news_bp)
    app.register_blueprint(software_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(recs_bp)
    app.register_blueprint(debug_bp)

    # Redirect www subdomain traffic to the apex domain for Render deployment
    @app.before_request
    def redirect_www_subdomain():
        host = request.headers.get("Host", "")
        if host.lower() == "www.usarmydroneteam.onrender.com" or host.lower() == "usarmydroneteam.onrendor.com":
            target_url = request.url.replace("//www.", "//", 1)
            return redirect(target_url, code=301)

    # Global login wall (lets Home/Login/Register/Static through)
    @app.before_request
    def access_control():
        ep = request.endpoint or ""
        if ep == "static" or ep.endswith(".static"):
            return
        public_endpoints = {
            "core.home",
            "auth.login_page",
            "auth.register_page",
            "auth.forgot_password",
            "auth.reset_password",
            "static",
            "core.healthz",
        }
        user_allowed = {
            "core.home",
            "team.index",
            "team.apply",
            "team.calendar",
            "profile.view",
            "auth.logout_page",
        }
        if ep not in public_endpoints:
            if not getattr(current_user, "is_authenticated", False):
                return login_manager.unauthorized()
        if getattr(current_user, "is_authenticated", False) and getattr(current_user, "role", "") != "admin":
            if ep not in user_allowed:
                return login_manager.unauthorized()

    # ★ Only auto-open a browser for local dev (avoid in PaaS/production workers)
    register_cli(app)

    from .signal_scheduler import init_signal_scheduler

    init_signal_scheduler(app)

    return app

