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
        pid = data.get("place_id")
        if stype == "visit" and not pid:
            import base64
            import hashlib
            import struct

            seed = f"manual|{p_name or ''}|{lat or 0}|{lng or 0}|{d_str}"
            h = hashlib.sha256(seed.encode("utf-8")).digest()
            cell_id = struct.unpack("<Q", h[:8])[0] | 1
            fprint = struct.unpack("<Q", h[8:16])[0] | 1
            blob = b"\x0a\x12\x09" + struct.pack("<Q", cell_id) + b"\x11" + struct.pack("<Q", fprint)
            pid = base64.urlsafe_b64encode(blob).decode("ascii").rstrip("=")
            c.execute(
                """
                INSERT OR IGNORE INTO places (place_id, name, address, category, latitude, longitude, source, business_status, user_confirmed)
                VALUES (?, ?, ?, ?, ?, ?, 'USER_MANUAL', 'OPERATIONAL', 1);
                """,
                (pid, p_name or "Manual Visit", p_addr, cat, lat, lng),
            )

        c.execute("""
            INSERT INTO segments (
                segment_type, place_id, place_name, place_address, category, activity_type,
                start_time, end_time, start_ts, end_ts, duration_minutes, distance_meters,
                date, year, month, day, latitude, longitude, end_lat, end_lng, path_points_json,
                hierarchy_level, is_unconfirmed, source, engine_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 'USER_MANUAL', '2.0.0');
        """, (stype, pid, p_name, p_addr, cat, act_type, st, et, sts, ets, dur_m, dist_m, d_str, y, m, d, lat, lng, end_lat, end_lng, pts_json))
        new_id = c.lastrowid

        # Record user decision in Layer 2 ledger
        c.execute(
            """
            INSERT OR REPLACE INTO user_decisions (
                decision_key, decision_type, date, start_ts, end_ts,
                target_place_id, target_place_name, source_stream, proposal_action, patch_data_json
            ) VALUES (?, 'MANUAL_CREATE', ?, ?, ?, ?, ?, 'USER_MANUAL', 'CREATE_SEGMENT', ?);
            """,
            (
                f"manual_create:{new_id}:{sts}",
                d_str,
                sts,
                ets,
                pid,
                p_name,
                json.dumps({"id": new_id, "segment_type": stype, "place_name": p_name, "activity_type": act_type}),
            ),
        )

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
    raw_st = data.get("start_time")
    raw_et = data.get("end_time")
    parsed_st = _parse_iso(raw_st) if (raw_st and raw_st != existing["start_time"]) else None
    parsed_et = _parse_iso(raw_et) if (raw_et and raw_et != existing["end_time"]) else None

    st = raw_st if (raw_st and (raw_st == existing["start_time"] or parsed_st is not None)) else existing["start_time"]
    et = raw_et if (raw_et and (raw_et == existing["end_time"] or parsed_et is not None)) else existing["end_time"]

    sts = float(data["start_ts"]) if data.get("start_ts") is not None else (parsed_st if parsed_st is not None else existing["start_ts"])
    ets = float(data["end_ts"]) if data.get("end_ts") is not None else (parsed_et if parsed_et is not None else existing["end_ts"])
    dur_m = (ets - sts) / 60.0 if (ets and sts and ets > sts) else existing["duration_minutes"]

    dist_m = float(data.get("distance_meters", existing["distance_meters"] or 0.0))
    lat = float(data["latitude"]) if data.get("latitude") is not None else existing["latitude"]
    lng = float(data["longitude"]) if data.get("longitude") is not None else existing["longitude"]
    pid = data.get("place_id") or existing.get("place_id")

    with get_db() as conn:
        c = conn.cursor()
        # If this is a visit and the user edited the name/address/category, create or update a dedicated place entry
        # when the name differs from the shared catalog place, or update the catalog place directly
        if existing["segment_type"] == "visit" and p_name:
            if pid:
                c.execute("SELECT name, visit_count FROM places WHERE place_id = ?;", (pid,))
                prow = c.fetchone()
                if prow and prow["name"] != p_name and (prow["visit_count"] or 0) > 1 and not data.get("place_id"):
                    # Mint a distinct canonical ChIJ so editing one visit (e.g. a neighbor's apartment or venue)
                    # does not rename 1,000+ visits to Home unless explicitly requested
                    import base64
                    import hashlib
                    import struct

                    seed = f"edit|{p_name}|{p_addr or ''}|{lat or 0}|{lng or 0}"
                    h = hashlib.sha256(seed.encode("utf-8")).digest()
                    cell_id = struct.unpack("<Q", h[:8])[0] | 1
                    fprint = struct.unpack("<Q", h[8:16])[0] | 1
                    blob = b"\x0a\x12\x09" + struct.pack("<Q", cell_id) + b"\x11" + struct.pack("<Q", fprint)
                    pid = base64.urlsafe_b64encode(blob).decode("ascii").rstrip("=")
                    c.execute(
                        """
                        INSERT OR REPLACE INTO places (place_id, name, address, category, latitude, longitude, source, business_status, user_confirmed, visit_count)
                        VALUES (?, ?, ?, ?, ?, ?, 'USER_EDIT', 'OPERATIONAL', 1, 1);
                        """,
                        (pid, p_name, p_addr, cat, lat, lng),
                    )
                else:
                    c.execute(
                        """
                        UPDATE places
                        SET name = ?, address = COALESCE(?, address), category = COALESCE(?, category), user_confirmed = 1
                        WHERE place_id = ?;
                        """,
                        (p_name, p_addr, cat, pid),
                    )

        c.execute("""
            UPDATE segments
            SET place_id = ?, place_name = ?, place_address = ?, category = ?, activity_type = ?,
                start_time = ?, end_time = ?, start_ts = ?, end_ts = ?,
                duration_minutes = ?, distance_meters = ?, latitude = ?, longitude = ?,
                is_unconfirmed = 0, source = 'USER_EDIT'
            WHERE id = ?;
        """, (pid, p_name, p_addr, cat, act_type, st, et, sts, ets, dur_m, dist_m, lat, lng, sid))

        # Record user decision in Layer 2 ledger
        c.execute(
            """
            INSERT OR REPLACE INTO user_decisions (
                decision_key, decision_type, date, start_ts, end_ts,
                target_place_id, target_place_name, source_stream, proposal_action, patch_data_json
            ) VALUES (?, 'EDIT_SEGMENT', ?, ?, ?, ?, ?, 'USER_EDIT', 'UPDATE_SEGMENT', ?);
            """,
            (
                f"edit_segment:{existing.get('source_key') or sid}",
                existing.get("date"),
                sts,
                ets,
                pid,
                p_name,
                json.dumps(
                    {
                        "id": sid,
                        "place_id": pid,
                        "place_name": p_name,
                        "place_address": p_addr,
                        "category": cat,
                        "activity_type": act_type,
                        "start_time": st,
                        "end_time": et,
                    }
                ),
            ),
        )

    return json_response({"status": "SUCCESS", "id": sid})


@router.post("/api/segments/delete")
def delete_segment(req: Request) -> Response:
    """Deletes a segment by ID and records the rejection in user_decisions."""
    data = req.json()
    sid = data.get("id")
    if not sid:
        return error_response("Missing segment 'id'", status_code=400)

    existing = query_one("SELECT * FROM segments WHERE id = ?;", (sid,))

    with get_db() as conn:
        c = conn.cursor()
        # Clear foreign key references before deleting segment
        c.execute("UPDATE segments SET parent_segment_id = NULL, hierarchy_level = 0 WHERE parent_segment_id = ?;", (sid,))
        c.execute("DELETE FROM anomalies WHERE segment_id = ?;", (sid,))
        c.execute("UPDATE gaps SET prev_segment_id = NULL WHERE prev_segment_id = ?;", (sid,))
        c.execute("UPDATE gaps SET next_segment_id = NULL WHERE next_segment_id = ?;", (sid,))
        c.execute("DELETE FROM segments WHERE id = ?;", (sid,))

        if existing:
            c.execute(
                """
                INSERT OR REPLACE INTO user_decisions (
                    decision_key, decision_type, date, start_ts, end_ts,
                    target_place_id, target_place_name, source_stream, proposal_action, patch_data_json
                ) VALUES (?, 'REJECT_SEGMENT', ?, ?, ?, ?, ?, 'USER_EDIT', 'DELETE_SEGMENT', ?);
                """,
                (
                    f"reject_segment:{existing.get('source_key') or sid}:{existing.get('start_ts')}",
                    existing.get("date"),
                    existing.get("start_ts"),
                    existing.get("end_ts"),
                    existing.get("place_id"),
                    existing.get("place_name"),
                    json.dumps({"deleted_id": sid, "date": existing.get("date"), "start_ts": existing.get("start_ts")}),
                ),
            )

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

