from flask import Blueprint, render_template, request, redirect, url_for, current_app
from flask_login import login_required
from ..services.uas import load_uas, append_uas, delete_uas, COLUMNS

bp = Blueprint("compare", __name__)

@bp.route("/compare")
@login_required
def compare():
    df = load_uas(current_app)
    return render_template("compare.html",
                           headers=COLUMNS, uas_list=df.to_dict(orient="records"),
                           message=request.args.get("message",""),
                           error=request.args.get("error",""))

@bp.route("/add", methods=["POST"])
@login_required
def add():
    try:
        form = request.form
        append_uas(current_app, {
            "name": form.get("name",""),
            "range_km": form.get("range_km",""),
            "endurance_hr": form.get("endurance_hr",""),
            "ceiling_m": form.get("ceiling_m",""),
            "payload_kg": form.get("payload_kg",""),
        })
        return redirect(url_for("compare.compare", message="UAS added successfully"))
    except Exception as e:
        return redirect(url_for("compare.compare", error=str(e)))

@bp.route("/delete", methods=["POST"])
@login_required
def delete():
    try:
        name = request.form.get("name","")
        if not name: raise ValueError("Missing name")
        delete_uas(current_app, name)
        return redirect(url_for("compare.compare", message=f"Deleted '{name}'"))
    except Exception as e:
        return redirect(url_for("compare.compare", error=str(e)))
