# skynet/extensions.py

from flask_login import LoginManager

login_manager = LoginManager()
login_manager.login_view = "auth.login_page"  # blueprint.endpoint form

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

db = SQLAlchemy()
migrate = Migrate()

__all__ = ["db", "migrate"]
