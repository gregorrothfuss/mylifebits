#!/usr/bin/env python3
"""
Systemic Path Repair Engine.

1. Propagates adjacent visit endpoints to zero-span activities.
2. Applies high-accuracy OpenStreetMap road polylines from snapped_routes_cache.db.
3. Sets has_snapped_path = 1 for all activities with valid multi-point curves (>= 3 points).
"""

import os
import sys
import json
import math
import sqlite3
from typing import Dict, Tuple, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "timeline_viewer.db")
CACHE_DB_PATH = os.path.join(WORKSPACE_DIR, "snapped_routes_cache.db")


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * R * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def repair_paths():
    print("=================================================================")
    print("           SYSTEMIC PATH REPAIR & ROAD SNAPPING                  ")
    print("=================================================================")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    conn_cache = sqlite3.connect(CACHE_DB_PATH)
    c_cache = conn_cache.cursor()

    # 1. Propagate adjacent visit endpoints to zero-span activities
    print("[1/3] Propagating adjacent visit endpoints to zero-span activities...")
    c.execute("""
        SELECT a.id, a.date, a.activity_type, a.latitude, a.longitude, a.end_lat, a.end_lng, a.start_ts, a.end_ts
        FROM segments a
        WHERE a.segment_type = 'activity'
          AND abs(a.latitude - a.end_lat) < 0.0001
          AND abs(a.longitude - a.end_lng) < 0.0001;
    """)
    zero_spans = c.fetchall()
    propagated_count = 0

    for act in zero_spans:
        aid = act["id"]
        adate = act["date"]
        sts = act["start_ts"]
        ets = act["end_ts"]

        # Preceding visit
        c.execute("""
            SELECT latitude, longitude FROM segments
            WHERE date = ? AND segment_type = 'visit' AND end_ts <= ? AND latitude IS NOT NULL
            ORDER BY end_ts DESC LIMIT 1;
        """, (adate, sts))
        prev_v = c.fetchone()

        # Succeeding visit
        c.execute("""
            SELECT latitude, longitude FROM segments
            WHERE date = ? AND segment_type = 'visit' AND start_ts >= ? AND latitude IS NOT NULL
            ORDER BY start_ts ASC LIMIT 1;
        """, (adate, ets))
        next_v = c.fetchone()

        if prev_v and next_v:
            dist = haversine(prev_v["latitude"], prev_v["longitude"], next_v["latitude"], next_v["longitude"])
            if dist > 25.0:
                c.execute("""
                    UPDATE segments
                    SET latitude = ?, longitude = ?, end_lat = ?, end_lng = ?, distance_meters = ?
                    WHERE id = ?;
                """, (prev_v["latitude"], prev_v["longitude"], next_v["latitude"], next_v["longitude"], dist, aid))
                propagated_count += 1

    conn.commit()
    print(f"  [✓] Propagated {propagated_count:,} zero-span activities from adjacent visits.")

    # 2. Build in-memory cache lookup table
    print("[2/3] Loading route cache into memory...")
    c_cache.execute("SELECT route_key, geometry_json, distance_m FROM route_cache WHERE geometry_json IS NOT NULL;")
    cache_rows = c_cache.fetchall()
    route_map: Dict[str, Tuple[str, float]] = {}
    for rk, geom, dist in cache_rows:
        route_map[rk] = (geom, dist or 0.0)
    print(f"  [✓] Loaded {len(route_map):,} cached routes.")

    # 3. Apply road geometries and update has_snapped_path
    print("[3/3] Applying road geometries and setting has_snapped_path = 1...")
    c.execute("""
        SELECT id, date, activity_type, latitude, longitude, end_lat, end_lng, path_points_json, has_snapped_path
        FROM segments
        WHERE segment_type = 'activity';
    """)
    all_acts = c.fetchall()

    applied_from_cache = 0
    already_snapped = 0
    updated_rows = []

    for act in all_acts:
        aid = act["id"]
        atype = (act["activity_type"] or "").upper()
        lat = act["latitude"]
        lng = act["longitude"]
        elat = act["end_lat"]
        elng = act["end_lng"]
        pts_json = act["path_points_json"]

        # Check existing path_points_json
        has_valid_pts = False
        if pts_json and len(pts_json) > 10:
            try:
                coords = json.loads(pts_json)
                if isinstance(coords, list) and len(coords) >= 3:
                    has_valid_pts = True
            except Exception:
                has_valid_pts = False

        if has_valid_pts:
            already_snapped += 1
            if act["has_snapped_path"] != 1:
                updated_rows.append((pts_json, 1, aid))
            continue

        if "FLY" in atype or lat is None or elat is None:
            continue

        if abs(lat) < 0.01 or abs(lng) < 0.01 or (lat == elat and lng == elng):
            continue

        mode = "bike" if "CYC" in atype else (
            "driving" if any(k in atype for k in ["CAR", "DRIV", "VEHICLE", "SUBWAY", "TRAIN", "TRAM", "BUS", "TAXI"])
            else "foot"
        )

        k1 = f"{mode}:{lat:.5f},{lng:.5f};{elat:.5f},{elng:.5f}"
        if k1 in route_map:
            geom, dist = route_map[k1]
            updated_rows.append((geom, 1, aid))
            applied_from_cache += 1
        else:
            # Try 4-decimal match
            k2 = f"{mode}:{lat:.4f},{lng:.4f};{elat:.4f},{elng:.4f}"
            for ckey in route_map:
                if ckey.startswith(mode) and f"{lat:.4f}" in ckey and f"{elat:.4f}" in ckey:
                    geom, dist = route_map[ckey]
                    updated_rows.append((geom, 1, aid))
                    applied_from_cache += 1
                    break

    if updated_rows:
        print(f"  Executing {len(updated_rows):,} updates to segments table...")
        c.executemany("UPDATE segments SET path_points_json = ?, has_snapped_path = ? WHERE id = ?;", updated_rows)
        conn.commit()

    # Final stats
    c.execute("SELECT COUNT(*) FROM segments WHERE segment_type = 'activity' AND has_snapped_path = 1;")
    total_snapped = c.fetchone()[0]
    total_acts = len(all_acts)
    pct = (total_snapped / total_acts * 100.0) if total_acts > 0 else 0.0

    print("=================================================================")
    print(f"  Total Activities:       {total_acts:,}")
    print(f"  Pre-existing Polylines: {already_snapped:,}")
    print(f"  Newly Snapped from OSRM:{applied_from_cache:,}")
    print(f"  Total Snapped Paths:    {total_snapped:,} ({pct:.1f}%)")
    print("=================================================================")

    conn_cache.close()
    conn.close()


if __name__ == "__main__":
    repair_paths()
