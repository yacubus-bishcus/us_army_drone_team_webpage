from flask import Blueprint, render_template, request, redirect, url_for, jsonify, flash
from flask_login import login_required, current_user
from skynet.extensions import db
from skynet.models import AAR, AARVote, AARComment

bp = Blueprint("aars", __name__, url_prefix="/aars")

@bp.route("/", methods=["GET"])
@login_required
def feed():
    # simple newest-first feed
    page = request.args.get("page", type=int, default=1)
    per_page = 15
    p = AAR.query.order_by(AAR.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    # Preload votes by current user to color arrows
    my_votes = {}
    if current_user.is_authenticated:
        rows = AARVote.query.filter(AARVote.user_id == current_user.id,
                                    AARVote.aar_id.in_([a.id for a in p.items])).all()
        my_votes = {r.aar_id: r.value for r in rows}
    return render_template("aars_feed.html", page=p, my_votes=my_votes)

@bp.route("/submit", methods=["GET", "POST"])
@login_required
def submit_aar():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        body  = request.form.get("body", "").strip()
        if not title or not body:
            flash("Title and body are required.", "error")
            return redirect(url_for("aars.submit_aar"))
        a = AAR(title=title, body=body, author_id=current_user.id)
        db.session.add(a)
        db.session.commit()
        flash("AAR submitted.", "success")
        return redirect(url_for("aars.feed"))
    return render_template("submit_aar.html")

@bp.route("/vote", methods=["POST"])
@login_required
def vote():
    aar_id = request.json.get("aar_id")
    value  = int(request.json.get("value", 0))  # -1, 0, +1 (0 clears)
    if value not in (-1, 0, +1):
        return jsonify({"ok": False, "error": "bad vote"}), 400
    aar = AAR.query.get_or_404(aar_id)

    v = AARVote.query.filter_by(aar_id=aar.id, user_id=current_user.id).one_or_none()
    if value == 0:
        if v:
            db.session.delete(v)
            db.session.commit()
        score = sum(x.value for x in aar.votes)
        return jsonify({"ok": True, "score": score, "user_vote": 0})

    if v:
        v.value = value
    else:
        v = AARVote(aar_id=aar.id, user_id=current_user.id, value=value)
        db.session.add(v)
    db.session.commit()
    score = sum(x.value for x in aar.votes)
    return jsonify({"ok": True, "score": score, "user_vote": value})

@bp.route("/comment", methods=["POST"])
@login_required
def comment():
    aar_id = request.form.get("aar_id", type=int)
    body   = (request.form.get("body") or "").strip()
    if not body:
        flash("Comment cannot be empty.", "error")
        return redirect(url_for("aars.feed"))
    aar = AAR.query.get_or_404(aar_id)
    c = AARComment(aar_id=aar.id, user_id=current_user.id, body=body)
    db.session.add(c)
    db.session.commit()
    return redirect(url_for("aars.feed", _anchor=f"aar-{aar.id}"))
