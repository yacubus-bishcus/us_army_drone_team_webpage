# skynet/blueprints/compare/routes.py
from flask import Blueprint, render_template, request, redirect, url_for, current_app
from flask_login import login_required
import math
from ...services.uas import load_uas, append_uas, delete_uas, COLUMNS
from . import compare_bp
import re

def parse_speed_range(raw):
    """
    Accepts strings like "120", "90-120", "90 – 120", "90 to 120", "120mph", "90–120 mph".
    Returns (min_val, max_val, avg_val) as floats, or (None, None, None) if not parseable.
    """
    if raw is None:
        return (None, None, None)
    s = str(raw).strip().lower()
    # remove units and commas
    s = s.replace("mph", "").replace(",", "")
    # normalize unicode dashes/en-dash/em-dash to "-"
    s = s.replace("–", "-").replace("—", "-")
    # "to" style
    s = re.sub(r"\s+to\s+", "-", s)

    # try "min-max"
    m = re.match(r"^\s*([+-]?\d+(\.\d+)?)\s*-\s*([+-]?\d+(\.\d+)?)\s*$", s)
    if m:
        a = float(m.group(1))
        b = float(m.group(3))
        lo, hi = (a, b) if a <= b else (b, a)
        return (lo, hi, (lo + hi) / 2.0)

    # try single number
    m = re.match(r"^\s*([+-]?\d+(\.\d+)?)\s*$", s)
    if m:
        v = float(m.group(1))
        return (v, v, v)

    return (None, None, None)

@compare_bp.route("/", methods=["GET"])
@login_required
def compare():
    # Load full dataset once
    df = load_uas(current_app)
    uas_list_full = df.to_dict(orient="records")  # used by selectors & compare views (not paginated)

    for r in uas_list_full:
        smin, smax, savg = parse_speed_range(r.get("speed_mph"))
        r["speed_mph_min_num"] = smin
        r["speed_mph_max_num"] = smax
        r["speed_mph_avg_num"] = savg

    # ---- pagination for the bottom "Data Table" only ----
    try:
        page = int(request.args.get("page", 1) or 1)
    except ValueError:
        page = 1
    try:
        per_page = int(request.args.get("per_page", 25) or 25)
    except ValueError:
        per_page = 25

    page = max(page, 1)
    per_page = max(per_page, 1)

    total = len(uas_list_full)
    pages = max(math.ceil(total / per_page), 1)
    if page > pages:
        page = pages

    start = (page - 1) * per_page
    end = start + per_page
    uas_table = uas_list_full[start:end]  # only this slice feeds the bottom table

    # Preserve all current query params when paging (names, mode, etc.)
    def page_url(p):
        args = request.args.to_dict(flat=False)
        args["page"] = [str(p)]
        args["per_page"] = [str(per_page)]
        flat = {k: (v[0] if len(v) == 1 else v) for k, v in args.items()}
        return url_for(".compare", **flat)

    return render_template(
        "compare.html",
        headers=COLUMNS,
        # Full list for selectors and compare modes
        uas_list=uas_list_full,
        # Paginated rows for the bottom admin/data table
        uas_table=uas_table,
        # Messages
        message=request.args.get("message", ""),
        error=request.args.get("error", ""),
        # Pagination ctx for the bottom table
        total=total,
        page=page,
        pages=pages,
        per_page=per_page,
        has_prev=(page > 1),
        has_next=(page < pages),
        first_url=page_url(1),
        prev_url=page_url(page - 1) if page > 1 else None,
        next_url=page_url(page + 1) if page < pages else None,
        last_url=page_url(pages),
    )

@compare_bp.route("/add", methods=["POST"])
@login_required
def add():
    try:
        form = request.form
        append_uas(current_app, {
            "name": form.get("name",""),
            "range_km": form.get("range_km",""),
            "endurance_min": form.get("endurance_min",""),
            "ceiling_ft": form.get("ceiling_ft", ""),
            "speed_mph": form.get("speed_mph", ""),
            "weight_lbs": form.get("weight_lbs",""),
            "payload_kg": form.get("payload_kg",""),
        })
        return redirect(url_for("compare.compare", message="UAS added successfully"))
    except Exception as e:
        return redirect(url_for("compare.compare", error=str(e)))

@compare_bp.route("/delete", methods=["POST"])
@login_required
def delete():
    try:
        name = request.form.get("name","")
        if not name:
            raise ValueError("Missing name")
        delete_uas(current_app, name)
        return redirect(url_for("compare.compare", message=f"Deleted '{name}'"))
    except Exception as e:
        return redirect(url_for("compare.compare", error=str(e)))
