#drone_team/blueprints/news/__init__.py
from flask import Blueprint

news_bp = Blueprint("news", __name__, url_prefix="/news")

from . import routes

