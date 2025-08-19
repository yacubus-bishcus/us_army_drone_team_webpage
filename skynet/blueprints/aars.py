# skynet/blueprints/aars.py
from flask import Blueprint, render_template, request, redirect, url_for, Response, current_app, send_from_directory, jsonify, flash
from flask_login import login_required, current_user
import io
from ..services import aars as svc

bp = Blueprint("aars", __name__)

@bp.route("/submit-aar", methods=["GET","POST"])
@login_required
def submit_aar():
    if request.method == "POST":
        try:
            svc.append(
                current_app,
                current_user.username if current_user.is_authenticated else "anonymous",
                request.form.get("unit",""),
                request.form.get("drones",""),
                request.form.get("training_date",""),
                request.form.get("tags",""),
                request.form.get("report",""),
                request.files.get("attachment")
            )
            return redirect(url_for("aars.submit_aar", message="AAR submitted successfully"))
        except Exception as e:
            return redirect(url_for("aars.submit_aar", error=str(e)))

    # Filters + load main AAR CSV
    filters = {k: request.args.get(k,"") for k in
               ["unit","drones","tags","username","date_from","date_to","mine_only"]}
    df = svc.load_df(current_app)
    df = svc.filter_df(df, filters, current_user.username if current_user.is_authenticated else None)
    df = df.sort_values("created_at", ascending=False).reset_index(drop=True)

    # Add a stable row id if you don't already have one in your CSV
    if "id" not in df.columns:
        df["aar_id"] = df.index.astype(int)
        id_col = "aar_id"
    else:
        id_col = "id"

    # Build records for template (include ID)
    records = df.to_dict(orient="records")
    aar_ids = [str(r[id_col]) for r in records]

    # Load votes & comments from their CSVs
    scores = svc.get_scores(current_app, aar_ids)                   # {id: total}
    my_votes = svc.get_user_votes(current_app, current_user.username, aar_ids)  # {id: -1|0|+1}
    comments_by_aar = svc.get_comments(current_app, aar_ids)        # {id: [ {user, body, created_at}, ... ]}

    qs = request.query_string.decode()
    export_url = url_for("aars.export") + (f"?{qs}" if qs else "")
    return render_template(
        "submit_aar.html",
        message=request.args.get("message",""),
        error=request.args.get("error",""),
        aars=records, filters=filters, export_url=export_url,
        logged_in=(current_user.username if current_user.is_authenticated else None),
        id_col=id_col, scores=scores, my_votes=my_votes, comments_by_aar=comments_by_aar
    )

@bp.route("/submit-aar/vote", methods=["POST"])
@login_required
def vote_aar():
    data = request.get_json(force=True, silent=False)
    aar_id = data.get("aar_id")
    value = int(data.get("value", 0))  # -1, 0, +1
    if value not in (-1, 0, 1):
        return jsonify({"ok": False, "error": "bad vote"}), 400
    if aar_id is None:
        return jsonify({"ok": False, "error": "missing id"}), 400

    svc.record_vote(current_app, aar_id, current_user.username, value)
    # Return updated score & user vote
    score = svc.get_scores(current_app, [aar_id]).get(aar_id, 0)
    return jsonify({"ok": True, "score": score, "user_vote": value})

@bp.route("/submit-aar/comment", methods=["POST"])
@login_required
def comment_aar():
    aar_id = request.form.get("aar_id")
    body = (request.form.get("body") or "").strip()
    if not aar_id or not body:
        flash("Comment cannot be empty.", "error")
        return redirect(url_for("aars.submit_aar"))
    svc.add_comment(current_app, str(aar_id), current_user.username, body)
    return redirect(url_for("aars.submit_aar", _anchor=f"aar-{aar_id}"))

@bp.route("/submit-aar/export", methods=["GET"])
@login_required
def export():
    filters = {k: request.args.get(k,"") for k in
               ["unit","drones","tags","username","date_from","date_to","mine_only"]}
    df = svc.filter_df(svc.load_df(current_app), filters,
                       current_user.username if current_user.is_authenticated else None)
    buf = io.StringIO(); df[svc.AAR_COLUMNS].to_csv(buf, index=False)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition":"attachment; filename=aars_export.csv"})

@bp.route("/files/aar/<path:filename>")
@login_required
def files(filename):
    return send_from_directory(svc.files_dir(current_app), filename, as_attachment=True)

