# drone_team/__init__.py
from flask import Flask, request 
from flask_login import current_user 
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
from .config import Config 
from .extensions import login_manager, db, migrate 
from .db import init_users_db, seed_admin_user 
from .services.uas import create_csv_if_missing
from .services.aars import create_aar_csv_if_missing 
import webbrowser, os 
from urllib.parse import quote_plus 
from threading import Timer 
from .cli import register_cli

def _open_browser_once():
    webbrowser.open_new("http://127.0.0.1:5000")


def create_app():
    load_dotenv()
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config.from_object(Config)

    # check to make sure instance directory exists 
    os.makedirs(app.instance_path, exist_ok=True) 
    # If DATABASE_URL wasn't provided, point sqlite to instance/
    if app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///drone_team.db"):
        db_path = os.path.join(app.instance_path, "drone_team.db")
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + db_path

    from .extensions import db, migrate
    db.init_app(app)
    migrate.init_app(app, db)
    from . import models  # ensure models are registered

    # Init other extensions
    login_manager.init_app(app)
    # Ensure data directories/files
    Path(app.config["DATA_DIR"]).mkdir(parents=True, exist_ok=True)
    init_users_db(app)         # SQLite tables + pending_users
    seed_admin_user(app)       # Seed admin if missing
    create_csv_if_missing(app) # UAS CSV
    from .services.aars import create_aar_csv_if_missing, normalize_aar_csv_formats
    create_aar_csv_if_missing(app)  # AAR CSV
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
    
    # Global login wall (lets Home/Login/Register/Static through)
    @app.before_request
    def access_control():
        ep = request.endpoint or ""
        bp = request.blueprint or ""
        if ep == "static" or ep.endswith(".static"):
            return 
        # Endpoints that never require login (auth pages + static)
        public_endpoints = {
            "auth.login_page",
            "auth.register_page",
            "static",
        }

        # Endpoints allowed to ANY authenticated user (BETA_RELEASE)
        user_allowed = {
            "core.home",         # Home
            "team.index",        # US Army Drone Team (landing/index)
            "team.apply",        # US Army Drone Team Application 
            "team.calendar",     # US Army Drone Team Calendar 
            "profile.view",      # Profile
            "auth.logout_page",  # Logout
        }


        # 1) Require login for everything except auth pages + static
        if ep not in public_endpoints:
            if not getattr(current_user, "is_authenticated", False):
                return login_manager.unauthorized()

        # 2) If logged in but NOT admin, allow only the beta endpoints
        if getattr(current_user, "is_authenticated", False) and getattr(current_user, "role", "") != "admin":
            if ep not in user_allowed:
                # block anything else for non-admins
                return login_manager.unauthorized()

    # Auto open browser (single instance)
    register_cli(app)
    Timer(1, _open_browser_once).start()
    return app
