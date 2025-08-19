from flask import Blueprint

software_bp = Blueprint("software", __name__, url_prefix="/software")
from . import routes  # noqa
