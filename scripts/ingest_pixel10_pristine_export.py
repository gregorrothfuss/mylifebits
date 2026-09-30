#!/usr/bin/env python3
"""
Ingest authentic Pixel 10 export (Timeline-20260908.json) into timeline_viewer.db
for the date range 2026-08-20 through 2026-09-08.

Cleanly replaces synthetic/corrupted records from August 20-31 (such as the fake
Gene's overnight stay) and populates all authentic September 1-8 segments.
"""

import json
import sqlite3
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = WORKSPACE_DIR / "timeline_viewer.db"
EXPORT_FILE = WORKSPACE_DIR / "pixel10_export" / "Timeline-20260908.json"

NY_TZ = timezone(timedelta(hours=-4))  # EDT is UTC-4 in August/September

def parse_latlng_str(s: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    if not s:
        return None, None
    clean = s.replace('°', '').strip()
    parts = [p.strip() for p in clean.split(',')]
    if len(parts) >= 2:
        try:
            return float(parts[0]), float(parts[1])
        except ValueError:
            return None, None
    return None, None

def parse_iso_ts(iso_str: str) -> Tuple[float, str, int, int, int, str]:
    """
    Parses ISO 8601 string and returns:
    (utc_timestamp, date_str_ny, year, month, day, local_iso_str)
    """
    dt = datetime.fromisoformat(iso_str)
    utc_ts = dt.timestamp()
    dt_ny = dt.astimezone(NY_TZ)
    date_str = dt_ny.strftime("%Y-%m-%d")
    return (
        utc_ts,
        date_str,
        dt_ny.year,
        dt_ny.month,
        dt_ny.day,
        dt_ny.isoformat()
    )

def main():
    if not EXPORT_FILE.exists():
        print(f"[!] Export file not found: {EXPORT_FILE}")
        return

    print(f"[*] Loading pristine export: {EXPORT_FILE}...")
    with open(EXPORT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    all_segments = data.get("semanticSegments", [])
    print(f"[*] Total segments in export: {len(all_segments):,}")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Preload places catalog
    c.execute("SELECT place_id, name, address, category, city, latitude, longitude FROM places;")
    places_catalog: Dict[str, Dict[str, Any]] = {}
    for r in c.fetchall():
        places_catalog[r[0]] = {
            "name": r[1],
            "address": r[2],
            "category": r[3],
            "city": r[4],
            "lat": r[5],
            "lng": r[6]
        }
    print(f"[*] Loaded {len(places_catalog):,} places from catalog.")

    # 1. Collect all timelinePath GPS points to associate with activities
    raw_path_points: List[Tuple[float, float, float]] = [] # (ts, lat, lng)
    for seg in all_segments:
        if "timelinePath" in seg:
            for pt in seg["timelinePath"]:
                pt_time = pt.get("time")
                pt_str = pt.get("point")
                if pt_time and pt_str:
                    lat, lng = parse_latlng_str(pt_str)
                    if lat is not None and lng is not None:
                        ts, _, _, _, _, _ = parse_iso_ts(pt_time)
                        raw_path_points.append((ts, lat, lng))

    raw_path_points.sort()
    print(f"[*] Indexed {len(raw_path_points):,} raw GPS breadcrumbs.")

    # 2. Filter segments for Aug 20, 2026 onwards
    target_segments = []
    for s in all_segments:
        st = s.get("startTime", "")
        if st >= "2026-08-20":
            target_segments.append(s)

    print(f"[*] Found {len(target_segments)} segments from 2026-08-20 onwards.")

    # 3. Cleanly clear existing viewer records from 2026-08-20 onwards
    c.execute("DELETE FROM segments WHERE date >= '2026-08-20';")
    deleted_count = c.rowcount
    print(f"[*] Cleared {deleted_count} stale/synthetic segments from 2026-08-20 onwards.")

    # Also clear any fix proposals for these dates
    c.execute("DELETE FROM fix_proposals WHERE date >= '2026-08-20';")
    c.execute("DELETE FROM anomalies WHERE date >= '2026-08-20';")

    inserted_visits = 0
    inserted_activities = 0
    inserted_paths = 0

    for seg in target_segments:
        st_raw = seg.get("startTime")
        et_raw = seg.get("endTime")
        if not st_raw or not et_raw:
            continue

        st_ts, d_str, yr, mo, dy, local_st = parse_iso_ts(st_raw)
        et_ts, _, _, _, _, local_et = parse_iso_ts(et_raw)
        dur_min = max(0.5, (et_ts - st_ts) / 60.0)

        # ----------------------------------------------------
        # Handle Visit
        # ----------------------------------------------------
        if "visit" in seg:
            v = seg["visit"]
            cand = v.get("topCandidate", {})
            pid = cand.get("placeId")
            sem_type = cand.get("semanticType", "UNKNOWN")
            prob = cand.get("probability", 1.0)
            hl = v.get("hierarchyLevel", 0)
            lat, lng = parse_latlng_str(cand.get("placeLocation", {}).get("latLng"))

            p_name = None
            p_addr = None
            p_cat = "Other / POI"
            p_city = "New York"

            if pid and pid in places_catalog:
                p_info = places_catalog[pid]
                p_name = p_info["name"]
                p_addr = p_info["address"]
                p_cat = p_info.get("category") or "Other / POI"
                p_city = p_info.get("city") or "New York"
                if lat is None:
                    lat = p_info["lat"]
                if lng is None:
                    lng = p_info["lng"]

            # Handle Home / Work semantic overrides
            if sem_type == "HOME" or (p_addr and "298 E 2nd" in p_addr):
                p_name = "Home (298 E 2nd St)"
                p_cat = "Home"
                if not lat:
                    lat, lng = 40.7205357, -73.9792147

            if not p_name:
                p_name = f"Location ({lat:.4f}, {lng:.4f})" if (lat and lng) else "Visited Location"

            c.execute("""
                INSERT INTO segments (
                    segment_type, start_time, end_time, start_ts, end_ts, duration_minutes,
                    date, year, month, day, latitude, longitude, place_id, place_name,
                    place_address, semantic_type, category, city, probability, hierarchy_level,
                    is_unconfirmed, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                "visit", local_st, local_et, float(st_ts), float(et_ts), round(dur_min, 2),
                d_str, yr, mo, dy, lat, lng, pid, p_name,
                p_addr, sem_type, p_cat, p_city, prob, hl,
                0, "PIXEL10_EXPORT_PRISTINE"
            ))
            inserted_visits += 1

        # ----------------------------------------------------
        # Handle Activity (Movement)
        # ----------------------------------------------------
        elif "activity" in seg:
            act = seg["activity"]
            cand = act.get("topCandidate", {})
            act_type = cand.get("type", "TRAVEL")
            if act_type == "IN_PASSENGER_VEHICLE":
                act_type = "DRIVING"
            prob = cand.get("probability", 1.0)
            dist = act.get("distanceMeters", 0.0)
            s_lat, s_lng = parse_latlng_str(act.get("start", {}).get("latLng"))
            e_lat, e_lng = parse_latlng_str(act.get("end", {}).get("latLng"))

            # Collect matching GPS breadcrumbs from timelinePath
            matched_pts = []
            if s_lat is not None and s_lng is not None:
                matched_pts.append([s_lat, s_lng])
            for pt_ts, pt_lat, pt_lng in raw_path_points:
                if st_ts <= pt_ts <= et_ts:
                    matched_pts.append([pt_lat, pt_lng])
            if e_lat is not None and e_lng is not None:
                matched_pts.append([e_lat, e_lng])

            # Deduplicate sequential identical points
            dedup_pts = []
            for pt in matched_pts:
                if not dedup_pts or (abs(dedup_pts[-1][0] - pt[0]) > 1e-6 or abs(dedup_pts[-1][1] - pt[1]) > 1e-6):
                    dedup_pts.append(pt)

            path_json = json.dumps(dedup_pts) if len(dedup_pts) >= 2 else None
            has_snapped = 1 if (path_json and len(dedup_pts) > 2) else 0

            c.execute("""
                INSERT INTO segments (
                    segment_type, start_time, end_time, start_ts, end_ts, duration_minutes,
                    date, year, month, day, latitude, longitude, end_lat, end_lng,
                    activity_type, distance_meters, probability, hierarchy_level,
                    is_unconfirmed, source, path_points_json, has_snapped_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                "activity", local_st, local_et, float(st_ts), float(et_ts), round(dur_min, 2),
                d_str, yr, mo, dy, s_lat, s_lng, e_lat, e_lng,
                act_type, dist, prob, 0,
                0, "PIXEL10_EXPORT_PRISTINE", path_json, has_snapped
            ))
            inserted_activities += 1

        # ----------------------------------------------------
        # Handle TimelinePath (Sensor path segment)
        # ----------------------------------------------------
        elif "timelinePath" in seg:
            inserted_paths += 1

    conn.commit()

    # 4. Verify results
    c.execute("SELECT count(*), min(date), max(date) FROM segments WHERE source = 'PIXEL10_EXPORT_PRISTINE';")
    tot_pristine, min_d, max_d = c.fetchone()
    print(f"\n[✓] Ingestion completed:")
    print(f"    - Pristine segments inserted: {tot_pristine} ({inserted_visits} visits, {inserted_activities} activities)")
    print(f"    - Date range: {min_d} through {max_d}")

    # Specific audit on August 25 (Gene's Restaurant)
    c.execute("""
        SELECT segment_type, place_name, start_time, end_time, duration_minutes
        FROM segments
        WHERE date = '2026-08-25' AND segment_type = 'visit'
        ORDER BY start_ts;
    """)
    print("\n[✓] August 25 Visits in database:")
    for r in c.fetchall():
        print(f"    {r[0].upper():<6} | {r[1]:<30} | {r[2]} -> {r[3]} ({r[4]} min)")

    # Specific audit on September 1-8
    c.execute("""
        SELECT date, count(*),
               sum(case when segment_type='visit' then 1 else 0 end) as visits,
               sum(case when segment_type='activity' then 1 else 0 end) as activities
        FROM segments
        WHERE date >= '2026-09-01'
        GROUP BY date ORDER BY date;
    """)
    print("\n[✓] September 1-8 Daily Summary:")
    for r in c.fetchall():
        print(f"    {r[0]}: {r[1]} segments ({r[2]} visits, {r[3]} activities)")

    conn.close()

if __name__ == "__main__":
    main()
