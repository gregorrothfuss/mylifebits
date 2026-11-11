"""Layer 1 authentic baseline restoration & synthetic guess purge passes."""

from __future__ import annotations

from typing import Any, Dict, Set

from breadcrumbs import haversine_distance
from db import get_db_connection
from enrichment.passes.common import ENGINE_VERSION


def purge_heuristic_gap_guesses(engine: Any) -> Dict[str, int]:
    """
    Removes synthetic gap-plugging, relabeled SYNTHETIC_LIFE routines, and legacy
    UTC-Z mutated rows from `raw_source_segments` and `segments` so the active
    timeline is built strictly from authentic local-timezone source exports and
    verified user-accepted fixes.
    """
    conn = get_db_connection(engine.db_path)
    try:
        c = conn.cursor()
        run_id = engine.start_inference_run(
            conn, "layer1_purge_heuristic_guesses", {"db_path": engine.db_path}
        )

        c.execute("PRAGMA foreign_keys = OFF;")
        c.execute(
            """
            DELETE FROM raw_source_segments
            WHERE start_time LIKE '%Z'
               OR source_stream IN ('SYNTHETIC_LIFE', 'SYNTHETIC_GAP_HEAL', 'cleaned_walk', 'interpolated')
               OR source_stream LIKE 'SYNTHETIC%';
            """
        )
        purged_l0 = int(c.rowcount or 0)

        c.execute(
            """
            DELETE FROM segments
            WHERE start_time LIKE '%Z'
               OR source IN ('SYNTHETIC_LIFE', 'SYNTHETIC_GAP_HEAL', 'cleaned_walk', 'interpolated')
               OR source LIKE 'SYNTHETIC%'
               OR source LIKE 'qg_cat_%';
            """
        )
        purged_count = int(c.rowcount or 0)
        c.execute(
            "UPDATE segments SET parent_segment_id = NULL WHERE parent_segment_id NOT IN (SELECT id FROM segments);"
        )
        c.execute(
            "DELETE FROM anomalies WHERE segment_id IS NOT NULL AND segment_id NOT IN (SELECT id FROM segments);"
        )
        conn.commit()
        c.execute("PRAGMA foreign_keys = ON;")

        out = {
            "purged_layer0_legacy_z_rows": purged_l0,
            "purged_synthetic_segments": purged_count,
        }
        engine.complete_inference_run(conn, run_id, out)
        return out
    finally:
        conn.close()


def restore_missing_and_swallowed_authentic_visits(engine: Any) -> Dict[str, int]:
    """
    Reconciles `segments` against Layer 0 (`raw_source_segments`):
    1. Inserts authentic visits and activities on intervals that are empty in `segments`.
    2. Restores distinct commercial/cultural POI visits that were overwritten or swallowed
       by adjacent Home / Work / Hotel stays.
    """
    conn = get_db_connection(engine.db_path)
    try:
        c = conn.cursor()
        run_id = engine.start_inference_run(
            conn, "layer1_restore_authentic_baseline", {"db_path": engine.db_path}
        )

        c.execute(
            """
            INSERT OR IGNORE INTO places (
                place_id, name, address, category, city, semantic_type,
                latitude, longitude, business_status, visit_count
            )
            SELECT
                place_id,
                COALESCE(MAX(place_name), 'Verified Place'),
                MAX(place_address),
                COALESCE(MAX(category), 'Other / POI'),
                MAX(city),
                MAX(semantic_type),
                AVG(latitude),
                AVG(longitude),
                'OPERATIONAL',
                0
            FROM raw_source_segments
            WHERE place_id IS NOT NULL
            GROUP BY place_id;
            """
        )
        conn.commit()

        c.execute(
            "SELECT place_id, name, address, category, city, semantic_type, latitude, longitude FROM places;"
        )
        places_map = {r["place_id"]: dict(r) for r in c.fetchall() if r["place_id"]}

        anchor_pids: Set[str] = set()
        for pid, p in places_map.items():
            nm = (p.get("name") or "").lower()
            cat = p.get("category") or ""
            sem = p.get("semantic_type") or ""
            if (
                sem in ("TYPE_HOME", "TYPE_WORK")
                or cat in ("Home & Residence", "Work & Office", "Hotels & Lodging")
                or nm.startswith("home")
                or "hotel" in nm
                or "hôtel" in nm
            ):
                anchor_pids.add(pid)

        c.execute(
            """
            SELECT *
            FROM raw_source_segments
            WHERE segment_type = 'visit'
              AND source_stream IN ('ON_DEVICE_2026', 'TAKEOUT_2024')
              AND place_id IS NOT NULL
            ORDER BY CASE WHEN source_stream = 'ON_DEVICE_2026' THEN 0 ELSE 1 END,
                     start_ts ASC;
            """
        )
        l0_visits = [dict(r) for r in c.fetchall()]

        inserted_visits = 0
        unswallowed_visits = 0
        split_stays = 0

        for lv in l0_visits:
            pid = lv["place_id"]
            st_ts = float(lv["start_ts"])
            et_ts = float(lv["end_ts"])
            if et_ts - st_ts < 30:
                continue

            p_info = places_map.get(pid, {})
            pname = lv["place_name"] or p_info.get("name")
            paddr = lv["place_address"] or p_info.get("address")
            pcat = lv["category"] or p_info.get("category") or "Other / POI"
            pcity = lv["city"] or p_info.get("city")
            sem_type = lv["semantic_type"] or p_info.get("semantic_type")
            lat = lv["latitude"] if lv["latitude"] is not None else p_info.get("latitude")
            lng = lv["longitude"] if lv["longitude"] is not None else p_info.get("longitude")

            c.execute(
                """
                SELECT id FROM segments
                WHERE segment_type = 'visit'
                  AND place_id = ?
                  AND start_ts <= ? AND end_ts >= ?
                LIMIT 1;
                """,
                (pid, et_ts + 300, st_ts - 300),
            )
            if c.fetchone():
                continue

            c.execute(
                """
                SELECT id, segment_type, place_id, place_name, category, semantic_type,
                       start_time, end_time, start_ts, end_ts, duration_minutes,
                       latitude, longitude, source
                FROM segments
                WHERE hierarchy_level = 0
                  AND start_ts < ? AND end_ts > ?
                ORDER BY start_ts ASC;
                """,
                (et_ts - 30, st_ts + 30),
            )
            overlaps = [dict(r) for r in c.fetchall()]

            if not overlaps:
                c.execute(
                    """
                    INSERT INTO segments (
                        segment_type, start_time, end_time, start_ts, end_ts,
                        duration_minutes, date, year, month, day,
                        latitude, longitude, place_id, place_name, place_address,
                        semantic_type, category, city, probability, hierarchy_level,
                        source, engine_version, inference_run_id, source_key
                    ) VALUES (
                        'visit', ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?
                    );
                    """,
                    (
                        lv["start_time"],
                        lv["end_time"],
                        st_ts,
                        et_ts,
                        lv["duration_minutes"],
                        lv["date"],
                        lv["year"],
                        lv["month"],
                        lv["day"],
                        lat,
                        lng,
                        pid,
                        pname,
                        paddr,
                        sem_type,
                        pcat,
                        pcity,
                        lv["probability"] or 1.0,
                        lv["hierarchy_level"] or 0,
                        lv["source_stream"],
                        ENGINE_VERSION,
                        run_id,
                        lv["source_key"],
                    ),
                )
                inserted_visits += 1
                continue

            if pid not in anchor_pids and pname:
                if len(overlaps) == 1 and overlaps[0]["segment_type"] == "visit":
                    ov = overlaps[0]
                    ov_pid = ov["place_id"]
                    ov_name = (ov["place_name"] or "").lower()
                    is_ov_anchor = (
                        ov_pid in anchor_pids
                        or ov_name.startswith("home")
                        or "hotel" in ov_name
                        or "hôtel" in ov_name
                        or ov["category"] in ("Home & Residence", "Work & Office", "Hotels & Lodging")
                    )
                    if is_ov_anchor:
                        if abs(ov["start_ts"] - st_ts) <= 600 and abs(ov["end_ts"] - et_ts) <= 600:
                            c.execute(
                                """
                                UPDATE segments
                                SET place_id = ?, place_name = ?, place_address = ?,
                                    category = ?, city = COALESCE(?, city),
                                    semantic_type = ?, latitude = COALESCE(?, latitude),
                                    longitude = COALESCE(?, longitude),
                                    engine_version = ?, inference_run_id = ?, source_key = ?
                                WHERE id = ?;
                                """,
                                (
                                    pid,
                                    pname,
                                    paddr,
                                    pcat,
                                    pcity,
                                    sem_type,
                                    lat,
                                    lng,
                                    ENGINE_VERSION,
                                    run_id,
                                    lv["source_key"],
                                    ov["id"],
                                ),
                            )
                            unswallowed_visits += 1
                        elif ov["start_ts"] <= st_ts - 300 and ov["end_ts"] >= et_ts + 300:
                            ov_lat = ov["latitude"]
                            ov_lng = ov["longitude"]
                            dist_anchor_km = (
                                haversine_distance(float(ov_lat), float(ov_lng), float(lat), float(lng)) / 1000.0
                                if (
                                    ov_lat is not None
                                    and ov_lng is not None
                                    and lat is not None
                                    and lng is not None
                                )
                                else 1.0
                            )
                            if dist_anchor_km > 50.0:
                                c.execute(
                                    """
                                    UPDATE segments
                                    SET start_time = ?, end_time = ?, start_ts = ?, end_ts = ?,
                                        duration_minutes = ?, date = ?, year = ?, month = ?, day = ?,
                                        latitude = ?, longitude = ?, place_id = ?, place_name = ?,
                                        place_address = ?, semantic_type = ?, category = ?, city = ?,
                                        source = ?, engine_version = ?, inference_run_id = ?, source_key = ?
                                    WHERE id = ?;
                                    """,
                                    (
                                        lv["start_time"],
                                        lv["end_time"],
                                        st_ts,
                                        et_ts,
                                        lv["duration_minutes"],
                                        lv["date"],
                                        lv["year"],
                                        lv["month"],
                                        lv["day"],
                                        lat,
                                        lng,
                                        pid,
                                        pname,
                                        paddr,
                                        sem_type,
                                        pcat,
                                        pcity,
                                        lv["source_stream"],
                                        ENGINE_VERSION,
                                        run_id,
                                        lv["source_key"],
                                        ov["id"],
                                    ),
                                )
                                unswallowed_visits += 1
                            else:
                                buf_sec = max(60.0, min(1800.0, round(dist_anchor_km * 120.0)))
                                left_et_ts = max(float(ov["start_ts"]) + 60.0, st_ts - buf_sec)
                                right_st_ts = min(float(ov["end_ts"]) - 60.0, et_ts + buf_sec)
                                left_dur = round((left_et_ts - float(ov["start_ts"])) / 60.0, 2)
                                right_dur = round((float(ov["end_ts"]) - right_st_ts) / 60.0, 2)
                                c.execute(
                                    """
                                    UPDATE segments
                                    SET end_time = ?, end_ts = ?, duration_minutes = ?,
                                        engine_version = ?, inference_run_id = ?
                                    WHERE id = ?;
                                    """,
                                    (
                                        lv["start_time"],
                                        left_et_ts,
                                        left_dur,
                                        ENGINE_VERSION,
                                        run_id,
                                        ov["id"],
                                    ),
                                )
                                c.execute(
                                    """
                                    INSERT INTO segments (
                                        segment_type, start_time, end_time, start_ts, end_ts,
                                        duration_minutes, date, year, month, day,
                                        latitude, longitude, place_id, place_name, place_address,
                                        semantic_type, category, city, probability, hierarchy_level,
                                        source, engine_version, inference_run_id, source_key
                                    ) VALUES (
                                        'visit', ?, ?, ?, ?,
                                        ?, ?, ?, ?, ?,
                                        ?, ?, ?, ?, ?,
                                        ?, ?, ?, 1.0, 0,
                                        ?, ?, ?, ?
                                    );
                                    """,
                                    (
                                        lv["start_time"],
                                        lv["end_time"],
                                        st_ts,
                                        et_ts,
                                        lv["duration_minutes"],
                                        lv["date"],
                                        lv["year"],
                                        lv["month"],
                                        lv["day"],
                                        lat,
                                        lng,
                                        pid,
                                        pname,
                                        paddr,
                                        sem_type,
                                        pcat,
                                        pcity,
                                        lv["source_stream"],
                                        ENGINE_VERSION,
                                        run_id,
                                        lv["source_key"],
                                    ),
                                )
                                r_date = lv["end_time"][:10]
                                c.execute(
                                    """
                                    INSERT INTO segments (
                                        segment_type, start_time, end_time, start_ts, end_ts,
                                        duration_minutes, date, year, month, day,
                                        latitude, longitude, place_id, place_name, place_address,
                                        semantic_type, category, city, probability, hierarchy_level,
                                        source, engine_version, inference_run_id
                                    ) VALUES (
                                        'visit', ?, ?, ?, ?,
                                        ?, ?, ?, ?, ?,
                                        ?, ?, ?, ?, (SELECT address FROM places WHERE place_id = ?),
                                        ?, ?, (SELECT city FROM places WHERE place_id = ?), 1.0, 0,
                                        ?, ?, ?
                                    );
                                    """,
                                    (
                                        lv["end_time"],
                                        ov["end_time"],
                                        right_st_ts,
                                        ov["end_ts"],
                                        right_dur,
                                        r_date,
                                        int(r_date[:4]),
                                        int(r_date[5:7]),
                                        int(r_date[8:10]),
                                        ov["latitude"],
                                        ov["longitude"],
                                        ov["place_id"],
                                        ov["place_name"],
                                        ov["place_id"],
                                        ov["semantic_type"],
                                        ov["category"],
                                        ov["place_id"],
                                        ov["source"],
                                        ENGINE_VERSION,
                                        run_id,
                                    ),
                                )
                                unswallowed_visits += 1
                                split_stays += 1

        c.execute(
            """
            SELECT *
            FROM raw_source_segments
            WHERE segment_type = 'activity'
              AND source_stream IN ('ON_DEVICE_2026', 'TAKEOUT_2024')
            ORDER BY CASE WHEN source_stream = 'ON_DEVICE_2026' THEN 0 ELSE 1 END,
                     start_ts ASC;
            """
        )
        l0_acts = [dict(r) for r in c.fetchall()]
        inserted_activities = 0
        for la in l0_acts:
            st_ts = float(la["start_ts"])
            et_ts = float(la["end_ts"])
            if et_ts - st_ts < 30:
                continue
            c.execute(
                """
                SELECT id FROM segments
                WHERE hierarchy_level = 0
                  AND start_ts < ? AND end_ts > ?
                LIMIT 1;
                """,
                (et_ts - 30, st_ts + 30),
            )
            if not c.fetchone():
                c.execute(
                    """
                    INSERT INTO segments (
                        segment_type, start_time, end_time, start_ts, end_ts,
                        duration_minutes, date, year, month, day,
                        latitude, longitude, end_lat, end_lng,
                        activity_type, distance_meters, probability, hierarchy_level,
                        path_points_json, has_snapped_path,
                        source, engine_version, inference_run_id, source_key
                    ) VALUES (
                        'activity', ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, 0,
                        ?, ?,
                        ?, ?, ?, ?
                    );
                    """,
                    (
                        la["start_time"],
                        la["end_time"],
                        st_ts,
                        et_ts,
                        la["duration_minutes"],
                        la["date"],
                        la["year"],
                        la["month"],
                        la["day"],
                        la["latitude"],
                        la["longitude"],
                        la["end_lat"],
                        la["end_lng"],
                        la["activity_type"],
                        la["distance_meters"] or 0.0,
                        la["probability"] or 1.0,
                        la["path_points_json"],
                        la["has_snapped_path"] or 0,
                        la["source_stream"],
                        ENGINE_VERSION,
                        run_id,
                        la["source_key"],
                    ),
                )
                inserted_activities += 1

        conn.commit()
        out = {
            "inserted_visits": inserted_visits,
            "unswallowed_visits": unswallowed_visits,
            "split_stays": split_stays,
            "inserted_activities": inserted_activities,
        }
        engine.complete_inference_run(conn, run_id, out)
        return out
    finally:
        conn.close()
