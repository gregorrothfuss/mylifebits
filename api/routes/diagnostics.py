"""
Diagnostics Suite: Gaps, Anomalies, and Unconfirmed Places API.
"""

from __future__ import annotations

from api.db import query_all, query_one
from api.response import Response, json_response
from api.router import Request, router


@router.get("/api/diagnostics/gaps")
def get_diagnostic_gaps(req: Request) -> Response:
    """Returns paginated gaps ordered by duration."""
    page = max(1, req.get_int("page", 1))
    limit = min(200, max(1, req.get_int("limit", 50)))
    min_hours = req.get_float("min_hours", 0.0)
    historical = req.get_int("historical", 0)
    offset = (page - 1) * limit

    sql = """
        SELECT g.*,
               s1.place_name as prev_place_name, s1.activity_type as prev_act_type,
               s2.place_name as next_place_name, s2.activity_type as next_act_type
        FROM gaps g
        LEFT JOIN segments s1 ON g.prev_segment_id = s1.id
        LEFT JOIN segments s2 ON g.next_segment_id = s2.id
        WHERE g.duration_hours >= ? AND g.is_historical = ?
        ORDER BY g.duration_hours DESC
        LIMIT ? OFFSET ?;
    """
    gaps = query_all(sql, (min_hours, historical, limit, offset))

    count_row = query_one(
        "SELECT COUNT(*) as total FROM gaps WHERE duration_hours >= ? AND is_historical = ?;",
        (min_hours, historical),
    )
    total = count_row["total"] if count_row else 0

    return json_response({
        "status": "SUCCESS",
        "page": page,
        "limit": limit,
        "total": total,
        "gaps": gaps
    })


@router.get("/api/diagnostics/anomalies")
def get_diagnostic_anomalies(req: Request) -> Response:
    """Returns detected timeline anomalies."""
    anomalies = query_all("SELECT * FROM anomalies ORDER BY date DESC LIMIT 200;")
    return json_response({"status": "SUCCESS", "anomalies": anomalies})


@router.get("/api/diagnostics/unconfirmed")
def get_diagnostic_unconfirmed(req: Request) -> Response:
    """Returns visits requiring place confirmation."""
    page = max(1, req.get_int("page", 1))
    limit = min(200, max(1, req.get_int("limit", 50)))
    offset = (page - 1) * limit

    unconfirmed = query_all("""
        SELECT s.id, s.date, s.start_time, s.end_time, s.latitude, s.longitude,
               s.place_id, s.semantic_type, s.category, s.city, s.probability
        FROM segments s
        WHERE s.segment_type = 'visit' AND (s.place_name IS NULL OR s.is_unconfirmed = 1)
        ORDER BY s.start_ts DESC
        LIMIT ? OFFSET ?;
    """, (limit, offset))

    count_row = query_one(
        "SELECT COUNT(*) as total FROM segments WHERE segment_type = 'visit' AND (place_name IS NULL OR is_unconfirmed = 1);"
    )
    total = count_row["total"] if count_row else 0

    return json_response({
        "status": "SUCCESS",
        "page": page,
        "limit": limit,
        "total": total,
        "unconfirmed": unconfirmed
    })
