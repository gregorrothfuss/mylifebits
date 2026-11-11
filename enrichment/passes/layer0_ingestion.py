"""Layer 0 immutable upstream observation ingestion passes."""

from __future__ import annotations

import datetime
import json
import os
import zipfile
from typing import Any, Dict, List, Tuple

from db import get_db_connection
from enrichment.local_timezone import get_timezone_offset_hours
from enrichment.passes.common import (
    compute_source_key,
    parse_iso_to_ts,
    parse_latlng_str,
)


def snapshot_existing_authentic_segments_to_layer0(engine: Any) -> Dict[str, int]:
    """
    Copies all currently authentic segments in `segments` into `raw_source_segments`
    so Layer 0 preserves 100% of verified observations.
    """
    conn = get_db_connection(engine.db_path)
    try:
        c = conn.cursor()
        run_id = engine.start_inference_run(
            conn, "layer0_snapshot_authentic", {"db_path": engine.db_path}
        )

        c.execute(
            """
            SELECT id, segment_type, start_time, end_time, start_ts, end_ts,
                   duration_minutes, date, year, month, day,
                   latitude, longitude, end_lat, end_lng,
                   place_id, place_name, place_address, semantic_type, category, city,
                   activity_type, distance_meters, probability, hierarchy_level,
                   path_points_json, has_snapped_path, source
            FROM segments
            WHERE COALESCE(source, '') NOT IN ('SYNTHETIC_LIFE', 'SYNTHETIC_GAP_HEAL')
              AND COALESCE(source, '') NOT LIKE 'SYNTHETIC%'
              AND COALESCE(source, '') NOT LIKE 'qg_cat_%';
            """
        )
        rows = c.fetchall()

        batch: List[Tuple[Any, ...]] = []
        for r in rows:
            src_stream = r["source"] or "LEGACY_AUTHENTIC"
            ident = r["place_id"] if r["segment_type"] == "visit" else r["activity_type"]
            skey = compute_source_key(
                src_stream, r["segment_type"], float(r["start_ts"]), float(r["end_ts"]), ident
            )
            batch.append(
                (
                    skey,
                    src_stream,
                    r["segment_type"],
                    r["start_time"],
                    r["end_time"],
                    r["start_ts"],
                    r["end_ts"],
                    r["duration_minutes"],
                    r["date"],
                    r["year"],
                    r["month"],
                    r["day"],
                    r["latitude"],
                    r["longitude"],
                    r["end_lat"],
                    r["end_lng"],
                    r["place_id"],
                    r["place_name"],
                    r["place_address"],
                    r["semantic_type"],
                    r["category"],
                    r["city"],
                    r["activity_type"],
                    r["distance_meters"] or 0.0,
                    r["probability"] or 1.0,
                    r["hierarchy_level"] or 0,
                    r["path_points_json"],
                    r["has_snapped_path"] or 0,
                    None,
                )
            )

        c.executemany(
            """
            INSERT OR IGNORE INTO raw_source_segments (
                source_key, source_stream, segment_type, start_time, end_time,
                start_ts, end_ts, duration_minutes, date, year, month, day,
                latitude, longitude, end_lat, end_lng,
                place_id, place_name, place_address, semantic_type, category, city,
                activity_type, distance_meters, probability, hierarchy_level,
                path_points_json, has_snapped_path, raw_payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            batch,
        )
        conn.commit()

        c.execute("SELECT COUNT(*) FROM raw_source_segments;")
        total_l0 = int(c.fetchone()[0])
        out = {"scanned_authentic": len(rows), "total_layer0_rows": total_l0}
        engine.complete_inference_run(conn, run_id, out)
        return out
    finally:
        conn.close()


def ingest_pixel10_export_to_layer0(engine: Any, json_path: str) -> Dict[str, int]:
    """
    Parses an authentic on-device Pixel Timeline JSON export (`semanticSegments`)
    into `raw_source_segments` without modifying or deleting any existing records.
    """
    if not os.path.exists(json_path):
        return {"ingested_visits": 0, "ingested_activities": 0}

    conn = get_db_connection(engine.db_path)
    try:
        c = conn.cursor()
        run_id = engine.start_inference_run(
            conn, "layer0_ingest_pixel10", {"json_path": json_path}
        )

        c.execute(
            "SELECT place_id, name, address, category, city, semantic_type, latitude, longitude FROM places;"
        )
        places_map = {r["place_id"]: dict(r) for r in c.fetchall() if r["place_id"]}

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        sem_segs = data.get("semanticSegments", [])
        batch: List[Tuple[Any, ...]] = []
        v_count = 0
        a_count = 0

        for seg in sem_segs:
            st_iso = seg.get("startTime")
            et_iso = seg.get("endTime")
            st_ts = parse_iso_to_ts(st_iso)
            et_ts = parse_iso_to_ts(et_iso)
            if not st_iso or not et_iso or st_ts is None or et_ts is None or et_ts <= st_ts:
                continue

            dur_min = round((et_ts - st_ts) / 60.0, 2)
            date_str = st_iso[:10]
            yr = int(date_str[:4])
            mo = int(date_str[5:7])
            dy = int(date_str[8:10])
            hl = int(seg.get("visit", {}).get("hierarchyLevel", 0) or 0)

            if "visit" in seg:
                v = seg["visit"]
                tc = v.get("topCandidate", {})
                pid = tc.get("placeId")
                sem_type = tc.get("semanticType")
                lat, lng = parse_latlng_str(tc.get("placeLocation", {}).get("latLng"))
                p_info = places_map.get(pid, {}) if pid else {}
                pname = p_info.get("name")
                paddr = p_info.get("address")
                pcat = p_info.get("category")
                pcity = p_info.get("city")
                if lat is None:
                    lat = p_info.get("latitude")
                if lng is None:
                    lng = p_info.get("longitude")

                skey = compute_source_key("ON_DEVICE_2026", "visit", st_ts, et_ts, pid)
                batch.append(
                    (
                        skey,
                        "ON_DEVICE_2026",
                        "visit",
                        st_iso,
                        et_iso,
                        st_ts,
                        et_ts,
                        dur_min,
                        date_str,
                        yr,
                        mo,
                        dy,
                        lat,
                        lng,
                        None,
                        None,
                        pid,
                        pname,
                        paddr,
                        sem_type or p_info.get("semantic_type"),
                        pcat,
                        pcity,
                        None,
                        0.0,
                        float(v.get("probability") or tc.get("probability") or 1.0),
                        hl,
                        None,
                        0,
                        None,
                    )
                )
                v_count += 1

            elif "activity" in seg:
                a = seg["activity"]
                tc = a.get("topCandidate", {})
                act_type = tc.get("type") or "MOVING"
                slat, slng = parse_latlng_str(a.get("start", {}).get("latLng"))
                elat, elng = parse_latlng_str(a.get("end", {}).get("latLng"))
                dist_m = float(a.get("distanceMeters") or 0.0)

                pts: List[List[float]] = []
                if slat is not None and slng is not None:
                    pts.append([slat, slng])
                if "timelinePath" in seg:
                    for tp in seg.get("timelinePath", []):
                        plat, plng = parse_latlng_str(tp.get("point"))
                        if plat is not None and plng is not None:
                            pts.append([plat, plng])
                if elat is not None and elng is not None:
                    pts.append([elat, elng])

                path_json = json.dumps(pts) if len(pts) >= 2 else None
                has_snapped = 1 if len(pts) >= 3 else 0
                skey = compute_source_key(
                    "ON_DEVICE_2026", "activity", st_ts, et_ts, act_type
                )
                batch.append(
                    (
                        skey,
                        "ON_DEVICE_2026",
                        "activity",
                        st_iso,
                        et_iso,
                        st_ts,
                        et_ts,
                        dur_min,
                        date_str,
                        yr,
                        mo,
                        dy,
                        slat,
                        slng,
                        elat,
                        elng,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        act_type,
                        dist_m,
                        float(tc.get("probability") or 1.0),
                        0,
                        path_json,
                        has_snapped,
                        None,
                    )
                )
                a_count += 1

        c.executemany(
            """
            INSERT INTO raw_source_segments (
                source_key, source_stream, segment_type, start_time, end_time,
                start_ts, end_ts, duration_minutes, date, year, month, day,
                latitude, longitude, end_lat, end_lng,
                place_id, place_name, place_address, semantic_type, category, city,
                activity_type, distance_meters, probability, hierarchy_level,
                path_points_json, has_snapped_path, raw_payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_key) DO UPDATE SET
                place_name = COALESCE(raw_source_segments.place_name, excluded.place_name),
                place_address = COALESCE(raw_source_segments.place_address, excluded.place_address),
                category = COALESCE(raw_source_segments.category, excluded.category),
                city = COALESCE(raw_source_segments.city, excluded.city);
            """,
            batch,
        )
        conn.commit()
        out = {"ingested_visits": v_count, "ingested_activities": a_count}
        engine.complete_inference_run(conn, run_id, out)
        return out
    finally:
        conn.close()


def ingest_takeout_2024_to_layer0(engine: Any, zip_path: str) -> Dict[str, int]:
    """
    Parses the 2024 Cloud Takeout Semantic Location History ZIP into `raw_source_segments`
    without overwriting existing rows.
    """
    if not os.path.exists(zip_path):
        return {"ingested_visits": 0, "ingested_activities": 0}

    conn = get_db_connection(engine.db_path)
    try:
        c = conn.cursor()
        run_id = engine.start_inference_run(
            conn, "layer0_ingest_takeout_2024", {"zip_path": zip_path}
        )

        c.execute(
            "SELECT place_id, name, address, category, city, semantic_type FROM places;"
        )
        places_map = {r["place_id"]: dict(r) for r in c.fetchall() if r["place_id"]}

        batch: List[Tuple[Any, ...]] = []
        v_count = 0
        a_count = 0

        with zipfile.ZipFile(zip_path, "r") as z:
            sem_files = sorted(
                [
                    n
                    for n in z.namelist()
                    if "Semantic Location History/" in n and n.endswith(".json")
                ]
            )
            for sf in sem_files:
                data = json.loads(z.read(sf))
                for obj in data.get("timelineObjects", []):
                    if "placeVisit" in obj:
                        pv = obj["placeVisit"]
                        dur = pv.get("duration", {})
                        st_iso = dur.get("startTimestamp")
                        et_iso = dur.get("endTimestamp")
                        st_ts = parse_iso_to_ts(st_iso)
                        et_ts = parse_iso_to_ts(et_iso)
                        if st_ts is None or et_ts is None or et_ts <= st_ts:
                            continue

                        loc = pv.get("location", {})
                        pid = loc.get("placeId")
                        lat = (
                            loc.get("latitudeE7") / 1e7
                            if loc.get("latitudeE7") is not None
                            else None
                        )
                        lng = (
                            loc.get("longitudeE7") / 1e7
                            if loc.get("longitudeE7") is not None
                            else None
                        )

                        off_h = get_timezone_offset_hours(lat, lng, st_ts)
                        tz = datetime.timezone(datetime.timedelta(hours=off_h))
                        dt_st = datetime.datetime.fromtimestamp(st_ts, tz=tz)
                        dt_et = datetime.datetime.fromtimestamp(et_ts, tz=tz)
                        local_st_iso = dt_st.isoformat()
                        local_et_iso = dt_et.isoformat()
                        date_str = local_st_iso[:10]

                        p_info = places_map.get(pid, {}) if pid else {}
                        pname = loc.get("name") or p_info.get("name")
                        paddr = loc.get("address") or p_info.get("address")
                        pcat = p_info.get("category")
                        pcity = p_info.get("city")
                        sem_type = loc.get("semanticType") or p_info.get("semantic_type")
                        dur_min = round((et_ts - st_ts) / 60.0, 2)

                        skey = compute_source_key(
                            "TAKEOUT_2024", "visit", st_ts, et_ts, pid
                        )
                        batch.append(
                            (
                                skey,
                                "TAKEOUT_2024",
                                "visit",
                                local_st_iso,
                                local_et_iso,
                                st_ts,
                                et_ts,
                                dur_min,
                                date_str,
                                int(date_str[:4]),
                                int(date_str[5:7]),
                                int(date_str[8:10]),
                                lat,
                                lng,
                                None,
                                None,
                                pid,
                                pname,
                                paddr,
                                sem_type,
                                pcat,
                                pcity,
                                None,
                                0.0,
                                1.0,
                                0,
                                None,
                                0,
                                None,
                            )
                        )
                        v_count += 1

                    elif "activitySegment" in obj:
                        act = obj["activitySegment"]
                        dur = act.get("duration", {})
                        st_iso = dur.get("startTimestamp")
                        et_iso = dur.get("endTimestamp")
                        st_ts = parse_iso_to_ts(st_iso)
                        et_ts = parse_iso_to_ts(et_iso)
                        if st_ts is None or et_ts is None or et_ts <= st_ts:
                            continue

                        sloc = act.get("startLocation", {})
                        eloc = act.get("endLocation", {})
                        slat = (
                            sloc.get("latitudeE7") / 1e7
                            if sloc.get("latitudeE7") is not None
                            else None
                        )
                        slng = (
                            sloc.get("longitudeE7") / 1e7
                            if sloc.get("longitudeE7") is not None
                            else None
                        )
                        elat = (
                            eloc.get("latitudeE7") / 1e7
                            if eloc.get("latitudeE7") is not None
                            else None
                        )
                        elng = (
                            eloc.get("longitudeE7") / 1e7
                            if eloc.get("longitudeE7") is not None
                            else None
                        )

                        ref_lat = slat if slat is not None else elat
                        ref_lng = slng if slng is not None else elng
                        off_h = get_timezone_offset_hours(ref_lat, ref_lng, st_ts)
                        tz = datetime.timezone(datetime.timedelta(hours=off_h))
                        dt_st = datetime.datetime.fromtimestamp(st_ts, tz=tz)
                        dt_et = datetime.datetime.fromtimestamp(et_ts, tz=tz)
                        local_st_iso = dt_st.isoformat()
                        local_et_iso = dt_et.isoformat()
                        date_str = local_st_iso[:10]

                        act_type = act.get("activityType") or "MOVING"
                        dist_m = float(act.get("distance") or 0.0)
                        dur_min = round((et_ts - st_ts) / 60.0, 2)

                        pts_t: List[List[float]] = []
                        if slat is not None and slng is not None:
                            pts_t.append([slat, slng])
                        for wp in act.get("waypointPath", {}).get("waypoints", []):
                            wlat = wp.get("latE7")
                            wlng = wp.get("lngE7")
                            if wlat is not None and wlng is not None:
                                pts_t.append([wlat / 1e7, wlng / 1e7])
                        for sp in act.get("simplifiedRawPath", {}).get("points", []):
                            wlat = sp.get("latE7")
                            wlng = sp.get("lngE7")
                            if wlat is not None and wlng is not None:
                                pts_t.append([wlat / 1e7, wlng / 1e7])
                        if elat is not None and elng is not None:
                            pts_t.append([elat, elng])

                        path_json = json.dumps(pts_t) if len(pts_t) >= 2 else None
                        has_snapped = 1 if len(pts_t) >= 3 else 0
                        skey = compute_source_key(
                            "TAKEOUT_2024", "activity", st_ts, et_ts, act_type
                        )
                        batch.append(
                            (
                                skey,
                                "TAKEOUT_2024",
                                "activity",
                                local_st_iso,
                                local_et_iso,
                                st_ts,
                                et_ts,
                                dur_min,
                                date_str,
                                int(date_str[:4]),
                                int(date_str[5:7]),
                                int(date_str[8:10]),
                                slat,
                                slng,
                                elat,
                                elng,
                                None,
                                None,
                                None,
                                None,
                                None,
                                None,
                                act_type,
                                dist_m,
                                1.0,
                                0,
                                path_json,
                                has_snapped,
                                None,
                            )
                        )
                        a_count += 1

        c.executemany(
            """
            INSERT INTO raw_source_segments (
                source_key, source_stream, segment_type, start_time, end_time,
                start_ts, end_ts, duration_minutes, date, year, month, day,
                latitude, longitude, end_lat, end_lng,
                place_id, place_name, place_address, semantic_type, category, city,
                activity_type, distance_meters, probability, hierarchy_level,
                path_points_json, has_snapped_path, raw_payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_key) DO UPDATE SET
                start_time = excluded.start_time,
                end_time = excluded.end_time,
                date = excluded.date,
                year = excluded.year,
                month = excluded.month,
                day = excluded.day,
                place_name = COALESCE(raw_source_segments.place_name, excluded.place_name),
                place_address = COALESCE(raw_source_segments.place_address, excluded.place_address),
                category = COALESCE(raw_source_segments.category, excluded.category),
                city = COALESCE(raw_source_segments.city, excluded.city);
            """,
            batch,
        )
        conn.commit()
        out = {"ingested_visits": v_count, "ingested_activities": a_count}
        engine.complete_inference_run(conn, run_id, out)
        return out
    finally:
        conn.close()
