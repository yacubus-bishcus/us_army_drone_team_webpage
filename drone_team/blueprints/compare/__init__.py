#/drone_team/blueprints/compare/__init__.py
from flask import Blueprint
compare_bp = Blueprint("compare", __name__, url_prefix="/compare")
from . import routes 
