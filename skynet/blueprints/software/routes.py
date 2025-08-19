import os
from flask import render_template, request, jsonify, current_app, abort, send_from_directory, url_for
from sqlalchemy import inspect
from skynet.extensions import db
from skynet.models import SoftwareFile
from . import software_bp

# Landing page with two big tabs/cards
@software_bp.route("/", methods=["GET"])
def index():
    return render_template("software/index.html")

# CAD list page
@software_bp.route("/cad", methods=["GET"])
def cad():
    return _render_list_page("cad")

# UAS list page
@software_bp.route("/uas", methods=["GET"])
def uas():
    return _render_list_page("uas")

def _render_list_page(category):
    # Build dynamic filter choices from DB (safe if table missing)
    insp = inspect(db.engine)
    filetypes, tags = [], []
    if insp.has_table("software_files"):
        filetypes = sorted({ft for (ft,) in db.session.query(SoftwareFile.filetype).filter_by(category=category).all() if ft})
        tags = sorted({t.strip()
                       for (raw,) in db.session.query(SoftwareFile.tags).filter_by(category=category).all()
                       for t in (raw or "").split(",") if t.strip()})
    return render_template("software/list.html",
                           category=category, filetypes=filetypes, tags=tags)

# JSON search for the list page
@software_bp.route("/search", methods=["GET"])
def search():
    category = request.args.get("category", "cad")
    q = request.args.get("q", "").strip()
    filetype = request.args.get("filetype", "").strip()
    tag = request.args.get("tag", "").strip()

    query = SoftwareFile.query.filter(SoftwareFile.category == category)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (SoftwareFile.name.ilike(like)) |
            (SoftwareFile.description.ilike(like)) |
            (SoftwareFile.tags.ilike(like))
        )
    if filetype:
        query = query.filter(SoftwareFile.filetype == filetype)
    if tag:
        query = query.filter(SoftwareFile.tags.ilike(f"%{tag}%"))

    rows = (query.order_by(SoftwareFile.uploaded_at.desc())
                 .limit(200).all())
    def row_to_dict(r):
        return {
            "id": r.id,
            "name": r.name,
            "description": r.description or "",
            "version": r.version or "",
            "license": r.license or "",
            "filetype": r.filetype or "",
            "tags": r.tags or "",
            "filesize_mb": round((r.filesize or 0) / 1024.0 / 1024.0, 2),
            "download_url": url_for("software.download", file_id=r.id)
        }
    return jsonify([row_to_dict(r) for r in rows])

# Download handler
@software_bp.route("/download/<int:file_id>", methods=["GET"])
def download(file_id):
    r = SoftwareFile.query.get_or_404(file_id)
    # Store under instance/uploads/software/<category>/
    base = os.path.join(current_app.instance_path, "uploads", "software", r.category)
    path = os.path.join(base, r.filename)
    if not os.path.exists(path):
        abort(404)
    # Increment download count
    r.downloads = (r.downloads or 0) + 1
    db.session.commit()
    return send_from_directory(base, r.filename, as_attachment=True)
