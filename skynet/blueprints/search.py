from flask import Blueprint, render_template, request, url_for, Response, current_app
from flask_login import login_required
import io, pandas as pd
from ..services.uas import COLUMNS, apply_basic_filters, apply_advanced_query, load_uas

bp = Blueprint("search", __name__)

@bp.route("/search", methods=["GET"])
@login_required
def search():
    df = load_uas(current_app)
    total = len(df)
    filters = {k: (request.args.get(k,"").strip()) for k in
               ["drone", "manufacturer", "country of manufacture", "cost",
               "range_km_min", "range_km_max", "endurance_min_min", "endurance_min_max",
               "speed_mph_min", "speed_mph_max", "weight_lbs_min", "weight_lbs_max",
               "ceiling_ft_max", "payload_kg_max"]
               }
    advanced = request.args.get("advanced","").strip()
    selected_columns = request.args.getlist("columns") or COLUMNS[:]

    df_f = apply_basic_filters(df.copy(), filters)
    df_f = apply_advanced_query(df_f, advanced)

    display_cols = [c for c in selected_columns if c in df_f.columns]
    if not display_cols:
        # fall back to intersection with df_f.columns (don’t crash)
        fallback = [c for c in COLUMNS if c in df_f.columns]
        display_cols = fallback or list(df_f.columns)  # last resort: show everything

    results = df_f[display_cols].to_dict(orient="records")
    qs = request.query_string.decode()
    export_url = url_for("search.export") + (f"?{qs}" if qs else "")

    return render_template("search.html",
                           headers=display_cols, results=results, total=total,
                           filters=filters, advanced=advanced,
                           all_columns=COLUMNS, selected_columns=set(display_cols),
                           export_url=export_url)

@bp.route("/search/export", methods=["GET"])
@login_required
def export():
    df = load_uas(current_app)
    filters = {k: (request.args.get(k,"").strip()) for k in
               ["drone", "manufacturer", "country of manufacture", "cost",
               "range_km_min", "range_km_max", "endurance_min_min", "endurance_min_max",
               "speed_mph_min", "speed_mph_max", "weight_lbs_min", "weight_lbs_max",
               "ceiling_ft_max", "payload_kg_max"]
               }
    advanced = request.args.get("advanced","").strip()
    cols = request.args.getlist("columns") or COLUMNS[:]
    df_f = apply_basic_filters(df.copy(), filters)
    df_f = apply_advanced_query(df_f, advanced)
    
    export_cols = [c for c in cols if c in df_f.columns]
    if not export_cols:
        fallback = [c for c in COLUMNS if c in df_f.columns]
        export_cols = fallback or list(df_f.columns)

    buf = io.StringIO(); df_f[export_cols].to_csv(buf, index=False)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition":"attachment; filename=skynet_search_export.csv"})
