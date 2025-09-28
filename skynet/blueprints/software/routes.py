#/skynet/blueprints/software/routes.py
import os
from flask import render_template, request, jsonify, current_app, abort, send_from_directory, url_for
from flask_login import login_required, current_user 
from sqlalchemy import inspect
from skynet.extensions import db
from skynet.models import SoftwareFile
from . import software_bp
from functools import wraps 
from skynet.authz import admin_required 
from skynet.services import software as svc 

# Allow common CAD formats; add/remove as needed
ALLOWED_CAD_EXTS = {".stl",".step",".stp",".iges",".igs",".obj",".3mf",".zip",".dwg",".dxf",".sldprt",".sldasm"}

    
# Landing page with two big tabs/cards
@software_bp.route("/", methods=["GET"])
def index():
    return render_template("software/index.html")

@software_bp.route("/software/cad", methods=["GET"])
@login_required
def cad():
    files = svc.list_cad(current_app)
    return render_template("software/software_cad.html", files=files)

# CAD UPLOAD/DOWNLOAD
# UPLOADS admin only function 
@software_bp.route("/software/cad/upload", methods=["POST"])
@admin_required
def cad_upload():
    f = request.files.get("file")
    display_name = (request.form.get("display_name") or "").strip()
    category = (request.form.get("category") or "").strip()
    tags = (request.form.get("tags") or "").strip()
    description = (request.form.get("description") or "").strip()

    if not f or not f.filename:
        flash("Please choose a file to upload.", "error")
        return redirect(url_for("software.cad"))
    if not display_name:
        flash("Please provide a display name.", "error")
        return redirect(url_for("software.cad"))

    ext = Path(f.filename).suffix.lower()
    if ext not in ALLOWED_CAD_EXTS:
        flash(f"Unsupported file type {ext}. Allowed: {', '.join(sorted(ALLOWED_CAD_EXTS))}", "error")
        return redirect(url_for("software.cad"))

    # Save file
    file_id = str(uuid.uuid4())
    stored_name = f"{file_id}_{secure_filename(f.filename)}"
    dest = svc.cad_dir(current_app) / stored_name
    data = f.read()
    dest.write_bytes(data)

    # Write metadata row
    row = {
        "id": file_id,
        "display_name": display_name,
        "category": category,
        "tags": tags,
        "description": description,
        "stored_filename": stored_name,
        "ext": ext,
        "size_bytes": str(len(data)),
        "uploaded_by": current_user.username if current_user.is_authenticated else "anonymous",
        "uploaded_at": __import__("datetime").datetime.utcnow().isoformat(timespec="seconds"),
    }
    svc.add_cad_row(current_app, row)

    flash("CAD file uploaded.", "success")
    return redirect(url_for("software.cad"))

@software_bp.route("/files/cad/<path:stored_filename>")
@login_required
def cad_download(stored_filename):
    # Simple guard: only serve files that exist under the CAD dir
    d = svc.cad_dir(current_app)
    target = d / stored_filename
    if not target.exists() or not target.is_file():
        abort(404)
    return send_from_directory(d, stored_filename, as_attachment=True)

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
