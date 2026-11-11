"""Layer 1 travel physics, multi-factor flight validation, and snapped polyline activation pass."""

from __future__ import annotations

import bisect
import json
from typing import Any, Dict, List, Optional, Tuple

from breadcrumbs import haversine_distance
from db import get_db_connection
from enrichment.flight_airport_auditor import find_nearest_airport
from enrichment.passes.common import ENGINE_VERSION


def sanitize_physics_and_polylines(engine: Any) -> Dict[str, int]:
    """
    Enforces physical travel mode constraints and polyline flags without guessing:
    1. Reclassifies FLYING segments with distance < 300 km or speed < 250 km/h to ground modes.
    2. Reclassifies non-FLYING segments > 300 km moving > 250 km/h ONLY when BOTH endpoints
       are within < 5 km of verified airport POIs (`AGENTS.md` Rule 6.4).
    3. Recomputes stale distances on spliced segments where endpoint distance contradicts
       `distance_meters`, and reclassifies supersonic WALKING (>12 km/h) / CYCLING (>45 km/h).
    4. Propagates missing `end_lat`/`end_lng` from adjacent segments and activates
       `has_snapped_path = 1` on all activities with >= 3 polyline points.
    """
    conn = get_db_connection(engine.db_path)
    try:
        c = conn.cursor()
        run_id = engine.start_inference_run(
            conn, "layer1_sanitize_physics_and_polylines", {"db_path": engine.db_path}
        )

        # Pre-load catalog airport POIs for <5 km spatial verification alongside KNOWN_AIRPORTS
        c.execute(
            """
            SELECT latitude, longitude
            FROM places
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL
              AND (
                  LOWER(COALESCE(name, '')) LIKE '%airport%'
                  OR LOWER(COALESCE(name, '')) LIKE '%flughafen%'
                  OR LOWER(COALESCE(name, '')) LIKE '%aéroport%'
                  OR LOWER(COALESCE(name, '')) LIKE '%aeroporto%'
                  OR LOWER(COALESCE(name, '')) LIKE '%aeropuerto%'
              );
            """
        )
        catalog_airports: List[Tuple[float, float]] = [
            (float(r[0]), float(r[1])) for r in c.fetchall()
        ]

        def _is_near_airport(lat: Optional[float], lng: Optional[float]) -> bool:
            if lat is None or lng is None:
                return False
            if find_nearest_airport(lat, lng, max_km=5.0) is not None:
                return True
            for alat, alng in catalog_airports:
                if haversine_distance(lat, lng, alat, alng) <= 5000.0:
                    return True
            return False

        def _has_airport_anchors(
            slat_v: Optional[float],
            slng_v: Optional[float],
            elat_v: Optional[float],
            elng_v: Optional[float],
        ) -> bool:
            return _is_near_airport(slat_v, slng_v) and _is_near_airport(elat_v, elng_v)

        propagated_endpoints = 0
        activated_polylines = 0

        c.execute(
            """
            SELECT start_ts, end_ts, path_points_json
            FROM raw_source_segments
            WHERE segment_type = 'activity'
              AND has_snapped_path = 1
              AND path_points_json IS NOT NULL
            ORDER BY start_ts ASC;
            """
        )
        l0_snapped_rows = c.fetchall()
        l0_snapped_starts = [float(r[0]) for r in l0_snapped_rows]

        c.execute(
            """
            SELECT timestamp, lat, lng
            FROM breadcrumbs
            WHERE is_excluded = 0 AND timestamp IS NOT NULL AND lat IS NOT NULL AND lng IS NOT NULL
            ORDER BY timestamp ASC;
            """
        )
        bc_rows = c.fetchall()
        bc_ts = [int(r[0]) for r in bc_rows]

        c.execute(
            """
            SELECT id, start_ts, end_ts, latitude, longitude, end_lat, end_lng,
                   distance_meters, duration_minutes, activity_type, path_points_json, has_snapped_path
            FROM segments
            WHERE segment_type = 'activity'
            ORDER BY start_ts ASC;
            """
        )
        acts = [dict(r) for r in c.fetchall()]

        reclassified_flights = 0
        reclassified_speeds = 0

        for a in acts:
            aid = a["id"]
            slat: Optional[float] = float(a["latitude"]) if a["latitude"] is not None else None
            slng: Optional[float] = float(a["longitude"]) if a["longitude"] is not None else None
            elat: Optional[float] = float(a["end_lat"]) if a["end_lat"] is not None else None
            elng: Optional[float] = float(a["end_lng"]) if a["end_lng"] is not None else None
            pts_json = a["path_points_json"]
            pts: List[List[float]] = []
            if pts_json:
                try:
                    pts = json.loads(pts_json)
                except Exception:
                    pts = []

            updated_coords = False
            if (slat is None or slng is None) and len(pts) >= 1:
                slat, slng = float(pts[0][0]), float(pts[0][1])
                updated_coords = True
            if (elat is None or elng is None) and len(pts) >= 2:
                elat, elng = float(pts[-1][0]), float(pts[-1][1])
                updated_coords = True

            if elat is None or elng is None:
                c.execute(
                    """
                    SELECT latitude, longitude FROM segments
                    WHERE start_ts >= ? AND latitude IS NOT NULL AND longitude IS NOT NULL
                    ORDER BY start_ts ASC LIMIT 1;
                    """,
                    (float(a["end_ts"] or 0.0) - 60.0,),
                )
                nxt = c.fetchone()
                if nxt:
                    elat, elng = float(nxt["latitude"]), float(nxt["longitude"])
                    updated_coords = True

            if (
                slat is not None
                and slng is not None
                and elat is not None
                and elng is not None
                and abs(slat - elat) < 1e-6
                and abs(slng - elng) < 1e-6
            ):
                c.execute(
                    """
                    SELECT latitude, longitude FROM segments
                    WHERE start_ts >= ? AND id != ? AND latitude IS NOT NULL AND longitude IS NOT NULL
                    ORDER BY start_ts ASC LIMIT 1;
                    """,
                    (float(a["end_ts"] or 0.0) - 5.0, aid),
                )
                nxt = c.fetchone()
                if nxt and (
                    abs(slat - float(nxt["latitude"])) > 1e-5
                    or abs(slng - float(nxt["longitude"])) > 1e-5
                ):
                    elat, elng = float(nxt["latitude"]), float(nxt["longitude"])
                    updated_coords = True

            if updated_coords:
                c.execute(
                    "UPDATE segments SET latitude = ?, longitude = ?, end_lat = ?, end_lng = ? WHERE id = ?;",
                    (slat, slng, elat, elng, aid),
                )
                propagated_endpoints += 1

            if len(pts) < 3:
                st_f = float(a["start_ts"] or 0.0)
                et_f = float(a["end_ts"] or 0.0)
                idx = bisect.bisect_left(l0_snapped_starts, st_f - 120.0)
                matched_pts: Optional[List[List[float]]] = None
                while idx < len(l0_snapped_rows) and float(l0_snapped_rows[idx][0]) <= st_f + 120.0:
                    if abs(float(l0_snapped_rows[idx][1]) - et_f) <= 300.0:
                        try:
                            cand = json.loads(l0_snapped_rows[idx][2])
                            if len(cand) >= 3:
                                matched_pts = cand
                                break
                        except Exception:
                            pass
                    idx += 1

                if not matched_pts and bc_ts and st_f > 0 and et_f > st_f:
                    b_start = bisect.bisect_left(bc_ts, int(st_f) - 30)
                    b_end = bisect.bisect_right(bc_ts, int(et_f) + 30)
                    if b_end - b_start >= 1:
                        poly: List[List[float]] = []
                        if slat is not None and slng is not None:
                            poly.append([slat, slng])
                        step = max(1, (b_end - b_start) // 35)
                        for b_idx in range(b_start, b_end, step):
                            blat, blng = float(bc_rows[b_idx][1]), float(bc_rows[b_idx][2])
                            if not poly or abs(blat - poly[-1][0]) > 1e-5 or abs(blng - poly[-1][1]) > 1e-5:
                                poly.append([blat, blng])
                        if elat is not None and elng is not None:
                            if not poly or abs(elat - poly[-1][0]) > 1e-5 or abs(elng - poly[-1][1]) > 1e-5:
                                poly.append([elat, elng])
                        if len(poly) >= 3:
                            matched_pts = poly

                if matched_pts and len(matched_pts) >= 3:
                    pts = matched_pts
                    c.execute(
                        "UPDATE segments SET path_points_json = ?, has_snapped_path = 1 WHERE id = ?;",
                        (json.dumps(pts), aid),
                    )
                    activated_polylines += 1

            if len(pts) >= 3 and not a["has_snapped_path"]:
                c.execute(
                    "UPDATE segments SET has_snapped_path = 1 WHERE id = ?;", (aid,)
                )
                activated_polylines += 1
            elif len(pts) < 3 and a["has_snapped_path"]:
                c.execute(
                    "UPDATE segments SET has_snapped_path = 0 WHERE id = ?;", (aid,)
                )

            dur_min = float(a["duration_minutes"] or 0.0)
            dist_m = float(a["distance_meters"] or 0.0)
            chord_m = (
                haversine_distance(slat, slng, elat, elng)
                if (
                    slat is not None
                    and slng is not None
                    and elat is not None
                    and elng is not None
                )
                else dist_m
            )

            if dur_min < 5.0 and chord_m >= 0 and dist_m > max(500.0, chord_m * 3.0):
                dist_m = round(chord_m * 1.2, 1)
                c.execute(
                    "UPDATE segments SET distance_meters = ? WHERE id = ?;",
                    (dist_m, aid),
                )

            dist_km = dist_m / 1000.0
            dur_h = dur_min / 60.0 if dur_min > 0 else 0.0
            speed_kmh = dist_km / dur_h if dur_h > 0 else 0.0
            mode = (a["activity_type"] or "MOVING").upper()

            new_mode = mode
            if mode == "FLYING":
                if dist_km < 300.0 or speed_kmh < 250.0:
                    if dist_km < 2.0 and speed_kmh <= 10.0:
                        new_mode = "WALKING"
                    elif dist_km < 15.0 and speed_kmh <= 35.0:
                        new_mode = "CYCLING"
                    else:
                        new_mode = "IN_PASSENGER_VEHICLE"
                    reclassified_flights += 1
                elif speed_kmh > 1350.0 and dur_h > 0:
                    clamped_m = round(
                        min(
                            chord_m * 1.05 if chord_m >= 300000.0 else dist_m,
                            dur_h * 900.0 * 1000.0,
                        ),
                        1,
                    )
                    if clamped_m < 300000.0:
                        new_mode = "IN_PASSENGER_VEHICLE"
                        clamped_m = round(min(clamped_m, dur_h * 105.0 * 1000.0), 1)
                        dist_m = clamped_m
                        dist_km = dist_m / 1000.0
                        speed_kmh = dist_km / dur_h if dur_h > 0 else 0.0
                        reclassified_flights += 1
                    c.execute(
                        "UPDATE segments SET distance_meters = ? WHERE id = ?;",
                        (clamped_m, aid),
                    )
                    reclassified_speeds += 1
            else:
                if (
                    dist_km > 300.0
                    and 250.0 < speed_kmh <= 1200.0
                    and _has_airport_anchors(slat, slng, elat, elng)
                ):
                    new_mode = "FLYING"
                    reclassified_flights += 1
                elif mode in ("WALKING", "ON_FOOT") and speed_kmh > 12.0:
                    if speed_kmh <= 38.0 and dist_km <= 25.0:
                        new_mode = "CYCLING"
                    elif speed_kmh <= 150.0:
                        new_mode = "IN_PASSENGER_VEHICLE"
                    else:
                        clamped_m = round(min(chord_m, dur_h * 6.0 * 1000.0), 1)
                        c.execute(
                            "UPDATE segments SET distance_meters = ? WHERE id = ?;",
                            (clamped_m, aid),
                        )
                    reclassified_speeds += 1
                elif mode in ("CYCLING", "ON_BICYCLE") and speed_kmh > 45.0:
                    if speed_kmh <= 150.0:
                        new_mode = "IN_PASSENGER_VEHICLE"
                    else:
                        clamped_m = round(min(chord_m, dur_h * 18.0 * 1000.0), 1)
                        c.execute(
                            "UPDATE segments SET distance_meters = ? WHERE id = ?;",
                            (clamped_m, aid),
                        )
                    reclassified_speeds += 1

            if (
                new_mode in ("DRIVING", "IN_PASSENGER_VEHICLE", "IN_TAXI", "IN_BUS")
                and speed_kmh > 160.0
                and dur_h > 0
            ):
                if (
                    dist_km > 300.0
                    and 250.0 <= speed_kmh <= 1150.0
                    and _has_airport_anchors(slat, slng, elat, elng)
                ):
                    new_mode = "FLYING"
                else:
                    clamped_m = round(
                        min(
                            chord_m if chord_m > 0 else dist_m,
                            dur_h * 105.0 * 1000.0,
                        ),
                        1,
                    )
                    c.execute(
                        "UPDATE segments SET distance_meters = ? WHERE id = ?;",
                        (clamped_m, aid),
                    )
                reclassified_speeds += 1

            if new_mode != mode:
                c.execute(
                    "UPDATE segments SET activity_type = ?, engine_version = ?, inference_run_id = ? WHERE id = ?;",
                    (new_mode, ENGINE_VERSION, run_id, aid),
                )

        c.execute(
            """
            UPDATE segments
            SET end_ts = start_ts + 15.0,
                duration_minutes = 0.25
            WHERE segment_type = 'visit'
              AND source = 'citibike'
              AND ABS(duration_minutes - 0.25) > 0.05;
            """
        )
        normalized_docks = int(c.rowcount or 0)

        c.execute(
            """
            SELECT id, start_ts, end_ts, duration_minutes, place_name, source, latitude, longitude
            FROM segments
            WHERE hierarchy_level = 0 AND segment_type = 'visit'
            ORDER BY start_ts ASC, end_ts ASC;
            """
        )
        top_visits = [dict(r) for r in c.fetchall()]
        resolved_overlaps = 0
        for i in range(len(top_visits) - 1):
            v1 = top_visits[i]
            for j in range(i + 1, min(i + 15, len(top_visits))):
                v2 = top_visits[j]
                if v2["start_ts"] >= v1["end_ts"]:
                    break
                v1_dur = v1["end_ts"] - v1["start_ts"]
                v2_dur = v2["end_ts"] - v2["start_ts"]
                if v2_dur <= 180 and v1_dur > v2_dur:
                    if v2["start_ts"] - v1["start_ts"] <= 60:
                        new_v1_st = v2["end_ts"] + 60.0
                        c.execute(
                            "UPDATE segments SET start_ts = ?, duration_minutes = ROUND((end_ts - ?) / 60.0, 2) WHERE id = ?;",
                            (new_v1_st, new_v1_st, v1["id"]),
                        )
                        v1["start_ts"] = new_v1_st
                    elif v1["end_ts"] - v2["end_ts"] <= 60:
                        new_v1_et = v2["start_ts"] - 60.0
                        c.execute(
                            "UPDATE segments SET end_ts = ?, duration_minutes = ROUND((? - start_ts) / 60.0, 2) WHERE id = ?;",
                            (new_v1_et, new_v1_et, v1["id"]),
                        )
                        v1["end_ts"] = new_v1_et
                    else:
                        c.execute("UPDATE segments SET hierarchy_level = 1 WHERE id = ?;", (v2["id"],))
                else:
                    new_v1_et = max(v1["start_ts"] + 60.0, v2["start_ts"] - 60.0)
                    if new_v1_et < v2["start_ts"] and new_v1_et > v1["start_ts"]:
                        c.execute(
                            "UPDATE segments SET end_ts = ?, duration_minutes = ROUND((? - start_ts) / 60.0, 2) WHERE id = ?;",
                            (new_v1_et, new_v1_et, v1["id"]),
                        )
                        v1["end_ts"] = new_v1_et
                    else:
                        c.execute("UPDATE segments SET hierarchy_level = 1 WHERE id = ?;", (v2["id"],))
                resolved_overlaps += 1

        c.execute(
            """
            SELECT s1.id, s2.id, s1.start_ts, s1.end_ts, s2.start_ts, s2.end_ts,
                   s1.latitude, s1.longitude, s2.latitude, s2.longitude
            FROM segments s1
            JOIN segments s2 ON s1.date = s2.date AND s2.start_ts >= s1.end_ts AND s2.start_ts <= (s1.end_ts + 30)
            WHERE s1.hierarchy_level = 0 AND s2.hierarchy_level = 0
              AND s1.segment_type = 'visit' AND s2.segment_type = 'visit'
              AND s1.latitude IS NOT NULL AND s1.longitude IS NOT NULL
              AND s2.latitude IS NOT NULL AND s2.longitude IS NOT NULL
              AND (s1.engine_version = '2.0.0' OR s2.engine_version = '2.0.0');
            """
        )
        buffered_jumps = 0
        for row in c.fetchall():
            id1, id2, st1, et1, st2, et2, lat1, lng1, lat2, lng2 = row
            if haversine_distance(float(lat1), float(lng1), float(lat2), float(lng2)) > 500.0:
                if (et1 - st1) >= 180.0:
                    new_et1 = st2 - 60.0
                    c.execute(
                        "UPDATE segments SET end_ts = ?, duration_minutes = ROUND((? - start_ts) / 60.0, 2) WHERE id = ?;",
                        (new_et1, new_et1, id1),
                    )
                    buffered_jumps += 1
                elif (et2 - st2) >= 180.0:
                    new_st2 = et1 + 60.0
                    c.execute(
                        "UPDATE segments SET start_ts = ?, duration_minutes = ROUND((end_ts - ?) / 60.0, 2) WHERE id = ?;",
                        (new_st2, new_st2, id2),
                    )
                    buffered_jumps += 1

        conn.commit()
        out = {
            "propagated_endpoints": propagated_endpoints,
            "activated_polylines": activated_polylines,
            "reclassified_flights": reclassified_flights,
            "reclassified_speeds": reclassified_speeds,
            "normalized_citi_docks": normalized_docks,
            "resolved_overlaps": resolved_overlaps,
            "buffered_jumps": buffered_jumps,
        }
        engine.complete_inference_run(conn, run_id, out)
        return out
    finally:
        conn.close()
