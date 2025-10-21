#/drone_team/blueprints/news/routes.py
import mimetypes
from datetime import datetime
from io import BytesIO
from flask import render_template, request, jsonify, current_app, flash, redirect, url_for, abort, send_file
from flask_login import current_user
from pikepdf import Pdf, PdfError
from pdfminer.pdfdocument import PDFDocument, PDFEncryptionError
from pdfminer.pdfparser import PDFParser, PDFSyntaxError
from pdfminer.psparser import PSEOF
from drone_team.services import news as news_svc
from drone_team.authz import admin_required
from drone_team.extensions import db
from drone_team.models import WhitePaper
from . import news_bp
from sqlalchemy import inspect
from sqlalchemy.orm import load_only
from werkzeug.utils import secure_filename
from drone_team.mailer import send_admin_email

# GET page
@news_bp.route("/", methods=["GET"])
def uas_news():
    # Example cards; replace with your real feed later
    csv_articles = news_svc.list_articles(current_app)  # newest first

    def _transform(article):
        open_count = article.get("open_count")
        try:
            open_count = int(open_count)
        except (TypeError, ValueError):
            open_count = 0
        return {
            "id": article["id"],
            "source": "csv",
            "title": article["title"],
            "summary": article["summary"],
            "image": article["image_url"] or url_for("static", filename="img/news_fallback.jpg"),
            "link": article["url"],
            "group": article.get("added_by", ""),
            "open_count": open_count,
        }

    articles = [_transform(article) for article in csv_articles]
    has_articles = bool(articles)
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
        articles=articles,
        has_articles=has_articles,
        years=years,
        tags=tags,
    )


@news_bp.route("/open/<article_id>", methods=["GET"])
def open_article(article_id):
    article = news_svc.increment_open_count(current_app, article_id)
    if not article:
        abort(404)
    return redirect(article["url"])

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

    results = (
        query.options(
            load_only(
                WhitePaper.id,
                WhitePaper.title,
                WhitePaper.authors,
                WhitePaper.year,
                WhitePaper.tags,
                WhitePaper.filesize,
                WhitePaper.filename,
                WhitePaper.uploaded_at,
            )
        )
        .order_by(WhitePaper.uploaded_at.desc())
        .limit(50)
        .all()
    )

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

    original_filename = f.filename or ""
    if not original_filename.lower().endswith(".pdf"):
        flash("Only PDF uploads are allowed.", "error")
        return redirect(url_for("news.uas_news"))

    fn = secure_filename(original_filename)
    if not fn:
        fn = f"whitepaper_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.pdf"

    blob = f.read()
    if not blob:
        flash("Uploaded PDF is empty.", "error")
        return redirect(url_for("news.uas_news"))

    def _reject_upload(reason: str, user_message: str = "Upload failed security checks. Only valid PDF files are allowed."):
        user_identifier = getattr(current_user, "username", None) or getattr(current_user, "email", None) or "anonymous"
        log_filename = fn or original_filename or "(unnamed)"
        current_app.logger.warning(
            "White paper upload blocked by validation: user=%s filename=%s reason=%s",
            user_identifier,
            log_filename,
            reason,
        )
        if current_app.config.get("EMAIL_AVAILABLE", True):
            app_obj = current_app._get_current_object()
            subject = "White paper upload blocked"
            body = (
                "<p>A white paper upload was blocked by the automated security checks.</p>"
                "<ul>"
                f"<li>User: {user_identifier}</li>"
                f"<li>Filename: {log_filename}</li>"
                f"<li>Reason: {reason}</li>"
                f"<li>Time (UTC): {datetime.utcnow().isoformat(timespec='seconds')}</li>"
                "</ul>"
            )
            try:
                send_admin_email(app_obj, subject, body)
            except Exception as exc:
                current_app.logger.exception(
                    "Failed to send admin alert for blocked white paper upload: %s", exc
                )

        flash(user_message, "error")
        return redirect(url_for("news.uas_news"))

    allowed_mimes = {"application/pdf", "application/x-pdf"}
    declared_mime = (f.mimetype or "").split(";", 1)[0].strip().lower()
    guessed_mime = (mimetypes.guess_type(fn)[0] or "").lower()
    if declared_mime not in allowed_mimes and guessed_mime not in allowed_mimes:
        return _reject_upload(
            f"MIME type validation failed (declared={declared_mime or 'unknown'}, guessed={guessed_mime or 'unknown'})"
        )

    if not blob.startswith(b"%PDF"):
        return _reject_upload("Missing %PDF header signature")

    try:
        with Pdf.open(BytesIO(blob)) as pdf_doc:
            if getattr(pdf_doc, "is_encrypted", False):
                return _reject_upload("Encrypted PDFs are not allowed")
    except PdfError as exc:
        return _reject_upload(f"pikepdf validation error: {exc}")

    try:
        parser = PDFParser(BytesIO(blob))
        PDFDocument(parser)
    except (PDFSyntaxError, PDFEncryptionError, PSEOF) as exc:
        return _reject_upload(f"pdfminer parse failed: {exc}")
    except Exception as exc:  # pragma: no cover - defensive catch
        return _reject_upload(f"Unexpected pdfminer error: {exc}")

    size = len(blob)
    wp = WhitePaper(
        title=title,
        authors=authors,
        year=year,
        tags=tags,
        abstract=abstract,
        filename=fn,
        filesize=size,
        data=blob,
        uploaded_at=datetime.utcnow(),
    )
    db.session.add(wp)
    db.session.commit()

    flash("White paper uploaded.", "success")
    return redirect(url_for("news.uas_news"))

# File download
@news_bp.route("/download/<int:wp_id>", methods=["GET"])
def download_whitepaper(wp_id):
    wp = WhitePaper.query.get_or_404(wp_id)
    if not wp.data:
        abort(404)

    return send_file(
        BytesIO(wp.data),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=wp.filename,
    )
