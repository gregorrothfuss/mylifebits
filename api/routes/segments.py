"""
Segment CRUD Operations (Create, Update, Delete).
"""

from __future__ import annotations

import datetime
import json
from typing import Any, Dict, Optional

from api.db import get_db, query_one
from api.response import Response, error_response, json_response
from api.router import Request, router
from breadcrumbs import haversine_distance


def _parse_iso(ts_str: Optional[str]) -> Optional[float]:
    if not ts_str:
        return None
    try:
        return datetime.datetime.fromisoformat(ts_str).timestamp()
    except Exception:
        return None


@router.post("/api/segments/create")
def create_segment(req: Request) -> Response:
    """Creates a new visit or activity segment."""
    data = req.json()
    stype = data.get("segment_type", "visit")
    p_name = data.get("place_name")
    p_addr = data.get("place_address")
    cat = data.get("category", "Other / POI")
    act_type = data.get("activity_type")
    st = data.get("start_time")
    et = data.get("end_time")

    sts = float(data.get("start_ts", 0.0)) if data.get("start_ts") else (_parse_iso(st) or 0.0)
    ets = float(data.get("end_ts", 0.0)) if data.get("end_ts") else (_parse_iso(et) or 0.0)
    dur_m = (ets - sts) / 60.0 if (ets > sts) else float(data.get("duration_minutes", 10.0))

    d_str = data.get("date") or (st[:10] if st else datetime.date.today().isoformat())
    lat = float(data["latitude"]) if data.get("latitude") is not None else None
    lng = float(data["longitude"]) if data.get("longitude") is not None else None
    end_lat = float(data["end_lat"]) if data.get("end_lat") is not None else None
    end_lng = float(data["end_lng"]) if data.get("end_lng") is not None else None

    dist_m = float(data.get("distance_meters", 0.0))
    if dist_m == 0.0 and lat is not None and lng is not None and end_lat is not None and end_lng is not None:
        dist_m = haversine_distance(lat, lng, end_lat, end_lng)

    pts_json = json.dumps([[lat, lng], [end_lat, end_lng]]) if (lat is not None and end_lat is not None) else None

    y = int(d_str[:4])
    m = int(d_str[5:7]) if len(d_str) >= 7 else 1
    d = int(d_str[8:10]) if len(d_str) >= 10 else 1

    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO segments (
                segment_type, place_name, place_address, category, activity_type,
                start_time, end_time, start_ts, end_ts, duration_minutes, distance_meters,
                date, year, month, day, latitude, longitude, end_lat, end_lng, path_points_json,
                hierarchy_level, is_unconfirmed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0);
        """, (stype, p_name, p_addr, cat, act_type, st, et, sts, ets, dur_m, dist_m, d_str, y, m, d, lat, lng, end_lat, end_lng, pts_json))
        new_id = c.lastrowid

        # Mark gap as resolved if specified
        gap_id = data.get("gap_id")
        if gap_id:
            c.execute("UPDATE gaps SET status = 'RESOLVED' WHERE id = ?;", (gap_id,))
            c.execute("UPDATE fix_proposals SET status = 'ACCEPTED', applied_at = datetime('now') WHERE target_id = ?;", (gap_id,))

    return json_response({"status": "SUCCESS", "id": new_id})


@router.post("/api/segments/update")
def update_segment(req: Request) -> Response:
    """Updates an existing segment's metadata, timestamps, or coordinates."""
    data = req.json()
    sid = data.get("id")
    if not sid:
        return error_response("Missing segment 'id'", status_code=400)

    existing = query_one("SELECT * FROM segments WHERE id = ?;", (sid,))
    if not existing:
        return error_response("Segment not found", status_code=404)

    p_name = data.get("place_name", existing["place_name"])
    p_addr = data.get("place_address", existing["place_address"])
    cat = data.get("category", existing["category"])
    act_type = data.get("activity_type", existing["activity_type"])
    st = data.get("start_time", existing["start_time"])
    et = data.get("end_time", existing["end_time"])

    sts = float(data.get("start_ts")) if data.get("start_ts") is not None else (_parse_iso(st) if st != existing["start_time"] else existing["start_ts"])
    ets = float(data.get("end_ts")) if data.get("end_ts") is not None else (_parse_iso(et) if et != existing["end_time"] else existing["end_ts"])
    dur_m = (ets - sts) / 60.0 if (ets and sts and ets > sts) else existing["duration_minutes"]

    dist_m = float(data.get("distance_meters", existing["distance_meters"] or 0.0))
    lat = float(data["latitude"]) if data.get("latitude") is not None else existing["latitude"]
    lng = float(data["longitude"]) if data.get("longitude") is not None else existing["longitude"]

    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE segments
            SET place_name = ?, place_address = ?, category = ?, activity_type = ?,
                start_time = ?, end_time = ?, start_ts = ?, end_ts = ?,
                duration_minutes = ?, distance_meters = ?, latitude = ?, longitude = ?
            WHERE id = ?;
        """, (p_name, p_addr, cat, act_type, st, et, sts, ets, dur_m, dist_m, lat, lng, sid))

    return json_response({"status": "SUCCESS", "id": sid})


@router.post("/api/segments/delete")
def delete_segment(req: Request) -> Response:
    """Deletes a segment by ID."""
    data = req.json()
    sid = data.get("id")
    if not sid:
        return error_response("Missing segment 'id'", status_code=400)

    with get_db() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM segments WHERE id = ?;", (sid,))

    return json_response({"status": "SUCCESS", "deleted_id": sid})


@router.get("/api/segments/3d-tour")
def get_segment_tour(req: Request) -> Response:
    """Returns 3D tour animation trajectory and metadata for Google Earth view."""
    seg_id = req.get_int("segment_id", 0)
    if not seg_id:
        return error_response("Missing segment_id parameter", status_code=400)

    try:
        from api.db import DEFAULT_DB_PATH
        from enrichment.tour_engine import get_segment_tour_data

        data = get_segment_tour_data(seg_id, DEFAULT_DB_PATH)
        return json_response(data)
    except Exception as e:
        return error_response(f"Error generating 3d tour: {e}", status_code=500)


@router.get("/api/segments/export-kml")
def export_segment_kml(req: Request) -> Response:
    """Exports Google Earth KML file for a single segment."""
    seg_id = req.get_int("segment_id", 0)
    if not seg_id:
        return error_response("Missing segment_id parameter", status_code=400)

    try:
        from api.db import DEFAULT_DB_PATH
        from enrichment.tour_engine import get_segment_kml

        kml_str = get_segment_kml(seg_id, DEFAULT_DB_PATH)
        return Response(
            body=kml_str.encode("utf-8"),
            status_code=200,
            content_type="application/vnd.google-earth.kml+xml; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="google_earth_tour_segment_{seg_id}.kml"'
            },
        )
    except Exception as e:
        return error_response(f"Error generating KML: {e}", status_code=500)

