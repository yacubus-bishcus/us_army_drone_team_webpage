# drone_team/blueprints/search/routes.py
from flask import render_template, request, url_for, Response, current_app
from flask_login import login_required
import io, math
from ...services.uas import COLUMNS, apply_basic_filters, apply_advanced_query, load_uas
from . import search_bp

@search_bp.route("/", methods=["GET"])
@login_required
def search():
    df = load_uas(current_app)
    total_dataset_rows = len(df)

    filters = {k: (request.args.get(k, "").strip()) for k in
               ["drone", "manufacturer", "country of manufacture", "cost",
                "range_km_min", "range_km_max", "endurance_min_min", "endurance_min_max",
                "speed_mph_min", "speed_mph_max", "weight_lbs_min", "weight_lbs_max",
                "ceiling_ft_max", "payload_kg_max"]
               }
    advanced = request.args.get("advanced", "").strip()
    selected_columns = request.args.getlist("columns") or COLUMNS[:]

    df_f = apply_basic_filters(df.copy(), filters)
    df_f = apply_advanced_query(df_f, advanced)

    display_cols = [c for c in selected_columns if c in df_f.columns]
    if not display_cols:
        fallback = [c for c in COLUMNS if c in df_f.columns]
        display_cols = fallback or list(df_f.columns)

    # --- pagination ---
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

    total_filtered = len(df_f)
    pages = max(math.ceil(total_filtered / per_page), 1)
    if page > pages:
        page = pages

    start = (page - 1) * per_page
    end = start + per_page

    page_df = df_f[display_cols].iloc[start:end]
    results = page_df.to_dict(orient="records")

    # Use blueprint-relative endpoints (".search", ".export")
    def page_url(p):
        args = request.args.to_dict(flat=False)
        args["page"] = [str(p)]
        args["per_page"] = [str(per_page)]
        flat = {k: v[0] if len(v) == 1 else v for k, v in args.items()}
        return url_for(".search", **flat)

    has_prev = page > 1
    has_next = page < pages

    args_for_export = request.args.to_dict(flat=False)
    args_for_export.pop("page", None)
    args_for_export.pop("per_page", None)
    export_url = url_for(".export", **{k: v[0] if len(v) == 1 else v for k, v in args_for_export.items()})

    return render_template(
        "search.html",
        headers=display_cols,
        results=results,
        total=total_dataset_rows,
        filtered_total=total_filtered,
        filters=filters,
        advanced=advanced,
        all_columns=COLUMNS,
        selected_columns=set(display_cols),
        export_url=export_url,
        page=page, pages=pages, per_page=per_page,
        has_prev=has_prev, has_next=has_next,
        first_url=page_url(1),
        prev_url=page_url(page - 1) if has_prev else None,
        next_url=page_url(page + 1) if has_next else None,
        last_url=page_url(pages),
    )

@search_bp.route("/export", methods=["GET"])
@login_required
def export():
    df = load_uas(current_app)
    filters = {k: (request.args.get(k, "").strip()) for k in
               ["drone", "manufacturer", "country of manufacture", "cost",
                "range_km_min", "range_km_max", "endurance_min_min", "endurance_min_max",
                "speed_mph_min", "speed_mph_max", "weight_lbs_min", "weight_lbs_max",
                "ceiling_ft_max", "payload_kg_max"]
               }
    advanced = request.args.get("advanced", "").strip()
    cols = request.args.getlist("columns") or COLUMNS[:]

    df_f = apply_basic_filters(df.copy(), filters)
    df_f = apply_advanced_query(df_f, advanced)

    export_cols = [c for c in cols if c in df_f.columns]
    if not export_cols:
        fallback = [c for c in COLUMNS if c in df_f.columns]
        export_cols = fallback or list(df_f.columns)

    buf = io.StringIO()
    df_f[export_cols].to_csv(buf, index=False)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition":"attachment; filename=drone_team_search_export.csv"})
