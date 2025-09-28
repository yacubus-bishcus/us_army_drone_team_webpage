#drone_team/blueprints/core.py
from flask import Blueprint, render_template, request
bp = Blueprint("core", __name__)

@bp.route("/")
@bp.route("/home")
def home():
    return render_template("home.html",
                           message=request.args.get("message",""),
                           error=request.args.get("error",""))
