#/drone_team/blueprints/search/__init__.py
from flask import Blueprint
search_bp = Blueprint("search", __name__, url_prefix="/search")
from . import routes 
