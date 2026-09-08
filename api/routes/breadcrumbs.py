"""
Breadcrumbs, Heatmap, and Outliers API.
"""

from __future__ import annotations

from typing import Any, List

from api.db import query_all, query_one
from api.response import Response, error_response, json_response
from api.router import Request, router


@router.get("/api/heatmap")
def get_heatmap(req: Request) -> Response:
    """Returns aggregated GPS coordinate clusters for heatmap visualization."""
    year = req.get_int("year", 0)
    category = req.get_str("category")

    where: List[str] = ["latitude IS NOT NULL", "longitude IS NOT NULL"]
    params: List[Any] = []

    if year > 0:
        where.append("year = ?")
        params.append(year)
    if category and category.upper() != "ALL":
        where.append("category = ?")
        params.append(category)

    sql = f"""
        SELECT latitude, longitude, COUNT(*) as weight
        FROM segments
        WHERE {" AND ".join(where)}
        GROUP BY ROUND(latitude, 3), ROUND(longitude, 3)
        ORDER BY weight DESC
        LIMIT 15000;
    """
    rows = query_all(sql, params)
    pts = [[r["latitude"], r["longitude"], min(r["weight"], 20)] for r in rows]

    return json_response({"status": "SUCCESS", "points": pts})


@router.get("/api/breadcrumbs")
def get_breadcrumbs(req: Request) -> Response:
    """Returns raw breadcrumbs for a date."""
    date_str = req.get_str("date")
    if not date_str:
        return error_response("Missing 'date' parameter", status_code=400)

    sql = """
        SELECT id, chunk_id, timestamp, date, lat, lng, accuracy, speed_kmh,
               anomaly_type, anomaly_score, anomaly_reason, is_excluded
        FROM breadcrumbs
        WHERE date = ?
        ORDER BY timestamp ASC;
    """
    points = query_all(sql, (date_str,))
    anomaly_count = sum(1 for p in points if p.get("anomaly_type") is not None)

    return json_response({
        "status": "SUCCESS",
        "date": date_str,
        "count": len(points),
        "anomaly_count": anomaly_count,
        "breadcrumbs": points
    })


@router.get("/api/outliers")
def get_outliers(req: Request) -> Response:
    """Returns outlier breadcrumb anomalies leaderboard."""
    limit = min(500, max(1, req.get_int("limit", 100)))

    sql = """
        SELECT id, chunk_id, timestamp, date, lat, lng, speed_kmh,
               anomaly_type, anomaly_score, anomaly_reason, is_excluded
        FROM breadcrumbs
        WHERE anomaly_type IS NOT NULL
        ORDER BY anomaly_score DESC, speed_kmh DESC
        LIMIT ?;
    """
    outliers = query_all(sql, (limit,))

    summary = query_all("""
        SELECT anomaly_type, COUNT(*) as cnt, ROUND(AVG(speed_kmh), 1) as avg_speed
        FROM breadcrumbs
        WHERE anomaly_type IS NOT NULL
        GROUP BY anomaly_type;
    """)

    return json_response({
        "status": "SUCCESS",
        "total_anomalies": sum(s["cnt"] for s in summary),
        "summary": summary,
        "outliers": outliers
    })


@router.post("/api/breadcrumbs/toggle-exclude")
def toggle_exclude_breadcrumb(req: Request) -> Response:
    """Toggles exclusion status of an outlier breadcrumb point."""
    data = req.json()
    point_id = data.get("id")
    is_excluded = int(data.get("is_excluded", 1))
    if point_id is None:
        return error_response("Missing point id", status_code=400)

    from api.db import get_db

    with get_db() as conn:
        c = conn.cursor()
        c.execute("UPDATE breadcrumbs SET is_excluded = ? WHERE id = ?;", (is_excluded, point_id))

    return json_response({"status": "SUCCESS", "id": point_id, "is_excluded": is_excluded})

