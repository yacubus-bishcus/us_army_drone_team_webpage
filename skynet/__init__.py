# skynet/__init__.py
from flask import Flask
from pathlib import Path
from .config import Config
from .extensions import login_manager, db, migrate 
from .db import init_users_db, seed_admin_user
from .services.uas import create_csv_if_missing
from .services.aars import create_aar_csv_if_missing
import webbrowser, os 
from urllib.parse import quote_plus 
from threading import Timer
from dotenv import load_dotenv

def _open_browser_once():
    webbrowser.open_new("http://127.0.0.1:5000")


def create_app():
    load_dotenv()
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config.from_object(Config)

    # check to make sure instance directory exists 
    os.makedirs(app.instance_path, exist_ok=True) 
    # If DATABASE_URL wasn't provided, point sqlite to instance/
    if app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///skynet.db"):
        db_path = os.path.join(app.instance_path, "skynet.db")
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
    from .blueprints.compare import bp as compare_bp
    from .blueprints.search import bp as search_bp
    from .blueprints.aars import bp as aars_bp
    from .blueprints.recommendations import bp as recs_bp
    from .blueprints.news import news_bp
    from .blueprints.software import software_bp 
    from .blueprints.profile import bp as profile_bp

    app.register_blueprint(core_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(compare_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(aars_bp)
    app.register_blueprint(recs_bp)
    app.register_blueprint(news_bp)
    app.register_blueprint(software_bp)
    app.register_blueprint(profile_bp)
    
    # Global login wall (lets Home/Login/Register/Static through)
    @app.before_request
    def require_login_for_tabs():
        from flask import request
        from flask_login import current_user
        public = {"core.home", "auth.login_page", "auth.register_page", "static"}
        if request.endpoint and request.endpoint not in public:
            if not current_user.is_authenticated:
                return login_manager.unauthorized()

    # Auto open browser (single instance)
    Timer(1, _open_browser_once).start()
    return app
