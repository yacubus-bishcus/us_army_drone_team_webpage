#/drone_team/blueprints/news/routes.py
from datetime import datetime
from io import BytesIO
from typing import Optional, Tuple

try:  # pragma: no cover - import guard for optional services
    import clamd  # type: ignore
except ImportError:  # pragma: no cover - handled at runtime
    clamd = None  # type: ignore

try:  # pragma: no cover - import guard for optional services
    import pikepdf  # type: ignore
    PikePdfError = pikepdf.PdfError
except Exception:  # pragma: no cover - handled at runtime
    pikepdf = None  # type: ignore

    class PikePdfError(Exception):
        pass

try:  # pragma: no cover - import guard for optional services
    from pdfminer.pdfdocument import PDFDocument
    from pdfminer.pdfparser import PDFParser, PDFSyntaxError
except ImportError:  # pragma: no cover - handled at runtime
    PDFDocument = None  # type: ignore
    PDFParser = None  # type: ignore

    class PDFSyntaxError(Exception):
        pass
from flask import (
    render_template,
    request,
    jsonify,
    current_app,
    flash,
    redirect,
    url_for,
    abort,
    send_file,
)
from flask_login import current_user

from drone_team.services import news as news_svc
from drone_team.authz import admin_required
from drone_team.extensions import db
from drone_team.mailer import send_admin_email
from drone_team.models import WhitePaper
from . import news_bp
from sqlalchemy import inspect
from sqlalchemy.orm import load_only
from werkzeug.utils import secure_filename

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

def _clamav_scan(blob: bytes) -> Tuple[bool, Optional[str]]:
    """Scan the provided blob with ClamAV, returning (ok, message)."""
    app = current_app
    if clamd is None:
        app.logger.error("clamd library not available; cannot scan uploads")
        return False, "scanner_unavailable"
    socket_path = app.config.get("CLAMD_UNIX_SOCKET")
    host = app.config.get("CLAMD_TCP_HOST", "127.0.0.1")
    port = int(app.config.get("CLAMD_TCP_PORT", 3310))

    try:
        if socket_path:
            client = clamd.ClamdUnixSocket(path=socket_path)
        else:
            client = clamd.ClamdNetworkSocket(host=host, port=port)
        client.ping()
    except Exception as exc:
        app.logger.error("ClamAV unavailable: %s", exc, exc_info=True)
        return False, "scanner_unavailable"

    try:
        result = client.instream(BytesIO(blob)) or {}
    except Exception as exc:
        app.logger.error("ClamAV scan error: %s", exc, exc_info=True)
        return False, "scan_error"

    status = result.get("stream")
    if not status:
        app.logger.error("ClamAV unexpected response: %s", result)
        return False, "scan_error"

    disposition, detail = status[0], status[1] if len(status) > 1 else None
    if disposition == "FOUND":
        return False, detail or "malware_detected"
    if disposition != "OK":
        app.logger.error("ClamAV unknown disposition: %s", status)
        return False, "scan_error"
    return True, None


def _validate_pdf(blob: bytes) -> Tuple[bool, Optional[str]]:
    """Basic sanity checks to ensure the blob looks like a PDF."""
    if not blob.startswith(b"%PDF"):
        return False, "missing_pdf_header"

    if pikepdf is None:
        current_app.logger.error("pikepdf module unavailable; cannot validate PDF content")
        return False, "pdf_validator_unavailable"

    try:
        with pikepdf.open(BytesIO(blob)) as pdf_doc:
            if pdf_doc.is_encrypted:
                return False, "encrypted_pdf"
    except PikePdfError as exc:
        current_app.logger.warning("pikepdf rejected upload: %s", exc)
        return False, "invalid_pdf"

    if PDFDocument is None or PDFParser is None:
        current_app.logger.error("pdfminer module unavailable; cannot validate PDF structure")
        return False, "pdf_validator_unavailable"

    try:
        parser = PDFParser(BytesIO(blob))
        PDFDocument(parser)
    except PDFSyntaxError as exc:
        current_app.logger.warning("pdfminer rejected upload: %s", exc)
        return False, "invalid_pdf"
    except Exception as exc:
        current_app.logger.warning("pdfminer error processing upload: %s", exc, exc_info=True)
        return False, "invalid_pdf"

    return True, None


def _alert_admins(subject: str, body: str) -> None:
    app = current_app
    try:
        if not send_admin_email(app, subject, body):
            app.logger.warning("Failed to send admin alert email: %s", subject)
    except Exception as exc:
        app.logger.error("Admin alert email exception: %s", exc, exc_info=True)


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

    mimetype = (f.mimetype or "").lower()
    if mimetype and mimetype not in {"application/pdf", "application/x-pdf"}:
        current_app.logger.warning(
            "White paper upload rejected due to MIME type: %s (user=%s)",
            mimetype,
            getattr(current_user, "username", "unknown"),
        )
        flash("Only PDF uploads are allowed.", "error")
        return redirect(url_for("news.uas_news"))

    fn = secure_filename(f.filename)
    if not fn:
        fn = f"whitepaper_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.pdf"

    blob = f.read()
    if not blob:
        flash("Uploaded PDF is empty.", "error")
        return redirect(url_for("news.uas_news"))

    max_size = current_app.config.get("MAX_CONTENT_LENGTH")
    if max_size and len(blob) > max_size:
        current_app.logger.warning(
            "White paper upload exceeds MAX_CONTENT_LENGTH: %s bytes (user=%s)",
            len(blob),
            getattr(current_user, "username", "unknown"),
        )
        flash("Uploaded PDF exceeds the maximum allowed size.", "error")
        return redirect(url_for("news.uas_news"))

    pdf_ok, pdf_msg = _validate_pdf(blob)
    if not pdf_ok:
        current_app.logger.error("White paper validation failed: %s", pdf_msg)
        if pdf_msg == "pdf_validator_unavailable":
            user_message = "PDF validation service unavailable; upload rejected. Please contact an administrator."
        else:
            user_message = "The uploaded file is not a valid PDF."
        _alert_admins(
            "White paper validation failed",
            (
                f"User {getattr(current_user, 'username', 'unknown')} attempted to upload an invalid PDF.\n"
                f"Reason: {pdf_msg}\n"
                f"Filename: {fn}\n"
                f"IP: {request.remote_addr}"
            ),
        )
        flash(user_message, "error")
        return redirect(url_for("news.uas_news"))

    scan_ok, scan_msg = _clamav_scan(blob)
    if not scan_ok:
        if scan_msg == "scanner_unavailable":
            message = "Virus scanner unavailable; upload rejected. Please try again later."
        elif scan_msg == "scan_error":
            message = "Virus scan error; upload rejected. Please contact an administrator."
        else:
            message = "Upload rejected: the file appears to contain malware."
        current_app.logger.error(
            "White paper scan failed (%s): user=%s filename=%s",
            scan_msg,
            getattr(current_user, "username", "unknown"),
            fn,
        )
        _alert_admins(
            "White paper scan failure",
            (
                f"User {getattr(current_user, 'username', 'unknown')} attempted to upload {fn} and the scan failed.\n"
                f"Scan result: {scan_msg}\n"
                f"IP: {request.remote_addr}"
            ),
        )
        flash(message, "error")
        return redirect(url_for("news.uas_news"))

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
