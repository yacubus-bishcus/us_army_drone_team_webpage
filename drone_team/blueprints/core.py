#drone_team/blueprints/core.py
from flask import Blueprint, render_template, request, current_app 
from ..db import get_user_count
bp = Blueprint("core", __name__)

@bp.route("/")
@bp.route("/home")
def home():
    count = get_user_count(current_app)
    return render_template("home.html",
                           user_count=count,
                           message=request.args.get("message",""),
                           error=request.args.get("error",""))
