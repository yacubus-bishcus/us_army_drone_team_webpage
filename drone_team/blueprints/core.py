#drone_team/blueprints/core.py
from flask import Blueprint, render_template, request, current_app, jsonify 
from ..db import get_user_count

bp = Blueprint("core", __name__)

@bp.route("/healthz")
def healthz():
    """
    Health check endpoint.
    Confirms the app is alive and the DB is reachable.
    """
    try:
        # Try to get user count from the DB
        count = get_user_count(current_app)
        return jsonify(status="ok", users=count), 200
    except Exception as e:
        # If DB check fails, return HTTP 500
        return jsonify(status="error", message=str(e)), 500


@bp.route("/")
@bp.route("/home")
def home():
    count = get_user_count(current_app)
    return render_template(
        "home.html",
        user_count=count,
        message=request.args.get("message", ""),
        error=request.args.get("error", "")
    )
