#/drone_team/blueprints/news/routes.py
import os
from datetime import datetime
from flask import render_template, request, jsonify, current_app, flash, redirect, url_for, abort
from flask_login import login_required, current_user 
from drone_team.services import news as news_svc 
from drone_team.authz import admin_required
from drone_team.signal_scheduler import (
    ManualIngestionStatus,
    get_manual_ingestion_status,
    trigger_manual_ingestion,
)
from werkzeug.utils import secure_filename
from drone_team.extensions import db
from drone_team.models import WhitePaper
from . import news_bp
from sqlalchemy import inspect

# GET page
@news_bp.route("/", methods=["GET"])
@login_required 
def uas_news():
    # Example cards; replace with your real feed later
    signal_groups = {
        "Master-Trainer/UAS/C-UAS": "Master-Trainer / UAS / C-UAS",
        "IrregularChat: Counter UxV": "IrregularChat · Counter UxV",
        "IrregularChat: sUAS": "IrregularChat · sUAS",
    }

    sections = {key: [] for key in signal_groups}
    other_items = []

    csv_articles = news_svc.list_articles(current_app)  # newest first

    def _transform(article):
        return {
            "id": article["id"],
            "source": "csv",
            "title": article["title"],
            "summary": article["summary"],
            "image": article["image_url"] or url_for("static", filename="img/news_fallback.jpg"),
            "link": article["url"],
            "group": article.get("added_by", ""),
        }

    for article in csv_articles:
        item = _transform(article)
        key = (article.get("added_by") or "").strip()
        if key in sections:
            sections[key].append(item)
        else:
            other_items.append(item)

    news_sections = [
        {
            "key": key,
            "title": title,
            "items": sections[key],
        }
        for key, title in signal_groups.items()
    ]

    if other_items:
        news_sections.append({
            "key": "other",
            "title": "Other News Sources",
            "items": other_items,
        })

    has_articles = any(section["items"] for section in news_sections)
    # WHITE PAPERS 
    insp = inspect(db.engine)
    if insp.has_table("white_papers"):
        years = [y[0] for y in db.session.query(WhitePaper.year).distinct().order_by(WhitePaper.year.desc())]
        tags = sorted({t.strip() for (val,) in db.session.query(WhitePaper.tags).all()
                       for t in (val or "").split(",") if t.strip()})
    else:
        years, tags = [], []

    return render_template(
        "uas_news.html",
        news_sections=news_sections,
        has_articles=has_articles,
        years=years,
        tags=tags,
    )

# admin-only endpoint to add by URL
@news_bp.route("/admin/articles/url", methods=["POST"])
@admin_required
def add_article_url():
    url = (request.form.get("url") or "").strip()
    if not url:
        flash("Please provide a URL.", "error")
        return redirect(url_for("news.uas_news"))
    try:
        news_svc.add_article_by_url(current_app, url, current_user.username)
        flash("Article added.", "success")
    except Exception as e:
        current_app.logger.exception("Add article failed: %s", e)
        flash(f"Failed to add article: {e}", "error")
    return redirect(url_for("news.uas_news"))

@news_bp.route("/admin/articles/<article_id>/delete", methods=["POST"])
@admin_required
def delete_article(article_id):
    ok = news_svc.delete_article(current_app, article_id)
    if ok:
        flash("Article deleted.", "success")
    else:
        flash("Article not found.", "error")
    return redirect(url_for("news.uas_news"))


@news_bp.route("/admin/signal/update", methods=["POST"])
@admin_required
def run_signal_update():
    previous_status = get_manual_ingestion_status()
    result = trigger_manual_ingestion(current_app)

    flash(result.message, result.category)

    status = result.status or get_manual_ingestion_status()

    if not result.started and status and status.is_running() and status.started_at:
        timestamp = status.started_at.strftime("%Y-%m-%d %H:%M UTC")
        flash(f"Background Signal update has been running since {timestamp}.", "info")

    if previous_status and previous_status.state in {"succeeded", "completed_with_errors", "failed"}:
        _flash_manual_status_summary(previous_status)

    if status and status.dry_run:
        flash("Signal update is running in dry-run mode; no articles will be added.", "info")

    return redirect(url_for("news.uas_news"))


def _flash_manual_status_summary(status: ManualIngestionStatus) -> None:
    if status.state == "succeeded":
        flash("Previous Signal update completed successfully.", "success")
    elif status.state == "completed_with_errors":
        failures = status.error or "unknown group"
        flash(
            "Previous Signal update completed with errors for: " + failures,
            "error",
        )
    elif status.state == "failed":
        message = status.error or "Signal update failed. Check the logs for details."
        flash(message, "error")

# JSON search endpoint (called by sidebar JS)
@news_bp.route("/search", methods=["GET"])
def search_whitepapers():
    q = request.args.get("q", "").strip()
    year = request.args.get("year")
    tag = request.args.get("tag", "").strip()

    query = WhitePaper.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            (WhitePaper.title.ilike(like)) |
            (WhitePaper.authors.ilike(like)) |
            (WhitePaper.abstract.ilike(like)) |
            (WhitePaper.tags.ilike(like))
        )
    if year:
        query = query.filter(WhitePaper.year == int(year))
    if tag:
        query = query.filter(WhitePaper.tags.ilike(f"%{tag}%"))

    results = (query.order_by(WhitePaper.uploaded_at.desc())
                    .limit(50).all())

    return jsonify([
        {
            "id": r.id, "title": r.title, "authors": r.authors, "year": r.year,
            "tags": r.tags, "filesize": r.filesize, "filename": r.filename,
            "url": url_for("news.download_whitepaper", wp_id=r.id)
        } for r in results
    ])

# Upload handler
@news_bp.route("/upload", methods=["POST"])
def upload_whitepaper():
    f = request.files.get("file")
    title = request.form.get("title", "").strip()
    authors = request.form.get("authors", "").strip()
    year = request.form.get("year", type=int)
    tags = request.form.get("tags", "").strip()
    abstract = request.form.get("abstract", "").strip()

    if not f or not title:
        flash("Title and PDF file are required.", "error")
        return redirect(url_for("news.uas_news"))

    if not f.filename.lower().endswith(".pdf"):
        flash("Only PDF uploads are allowed.", "error")
        return redirect(url_for("news.uas_news"))

    fn = secure_filename(f.filename)
    upload_dir = os.path.join(current_app.instance_path, "uploads", "whitepapers")
    os.makedirs(upload_dir, exist_ok=True)
    path = os.path.join(upload_dir, fn)
    f.save(path)

    size = os.path.getsize(path)
    wp = WhitePaper(
        title=title, authors=authors, year=year, tags=tags, abstract=abstract,
        filename=fn, filesize=size, uploaded_at=datetime.utcnow()
    )
    db.session.add(wp)
    db.session.commit()

    flash("White paper uploaded.", "success")
    return redirect(url_for("news.uas_news"))

# File download
@news_bp.route("/download/<int:wp_id>", methods=["GET"])
def download_whitepaper(wp_id):
    from flask import send_from_directory, abort
    wp = WhitePaper.query.get_or_404(wp_id)
    upload_dir = os.path.join(current_app.instance_path, "uploads", "whitepapers")
    if not os.path.exists(os.path.join(upload_dir, wp.filename)):
        abort(404)
    return send_from_directory(upload_dir, wp.filename, as_attachment=True)
