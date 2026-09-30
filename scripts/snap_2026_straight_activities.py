#!/usr/bin/env python3
"""
Snap 2026 Straight Activities to Streets & Enforce Strict Truth in Snapping.

1. Fetches genuine OSRM street geometries for all 2026 travel legs (>= 30m) that are currently straight chords.
2. Cleanses the entire database:
   - Sets has_snapped_path = 0 on any activity with <= 2 points or purely collinear points.
   - Clears redundant 2-point straight chords from path_points_json.
"""

import json
import math
import os
import sqlite3
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "timeline_viewer.db")
CACHE_DB_PATH = os.path.join(WORKSPACE_DIR, "snapped_routes_cache.db")


def is_collinear_or_straight(pts: List[List[float]]) -> bool:
    """Returns True if polyline has <= 2 points or all points deviate < 5m from straight chord."""
    if not pts or len(pts) <= 2:
        return True
    p1 = pts[0]
    p2 = pts[-1]
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    denom = math.hypot(dx, dy)
    if denom < 1e-7:
        return True
    max_d = 0.0
    for p in pts[1:-1]:
        d = abs(dy * p[0] - dx * p[1] + p2[0]*p1[1] - p2[1]*p1[0]) / denom
        if d > max_d:
            max_d = d
    # 0.00005 deg is ~5.5 meters
    return max_d < 0.00005


def query_osrm_single(lat1: float, lon1: float, lat2: float, lon2: float, osrm_mode: str) -> Tuple[Optional[List[List[float]]], Optional[float]]:
    try:
        url = f"http://router.project-osrm.org/route/v1/{osrm_mode}/{lon1:.6f},{lat1:.6f};{lon2:.6f},{lat2:.6f}?overview=full&geometries=geojson"
        req = urllib.request.Request(url, headers={'User-Agent': 'GregorMyLifeBits/1.0'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            if data.get('code') == 'Ok' and data.get('routes'):
                coords = data['routes'][0]['geometry']['coordinates']
                pts = [[round(c[1], 6), round(c[0], 6)] for c in coords]
                dist = data['routes'][0]['distance']
                return pts, dist
    except Exception:
        pass
    return None, None


def main():
    print("=================================================================")
    print("     SNAP 2026 STRAIGHT ACTIVITIES & CLEANSE CHORDS IN DB        ")
    print("=================================================================")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    conn_cache = sqlite3.connect(CACHE_DB_PATH)
    c_cache = conn_cache.cursor()

    # 1. Identify 2026 straight activities needing snapping
    print("[1/3] Identifying 2026 activities with straight chords...")
    c.execute("""
        SELECT id, date, activity_type, distance_meters, latitude, longitude, end_lat, end_lng, path_points_json, has_snapped_path
        FROM segments
        WHERE segment_type = 'activity' AND date >= '2026-01-01'
        ORDER BY date DESC;
    """)
    acts_2026 = c.fetchall()

    to_snap = []
    to_query = {}

    for r in acts_2026:
        sid = r["id"]
        atype = (r["activity_type"] or "DRIVING").upper()
        slat, slng = r["latitude"], r["longitude"]
        elat, elng = r["end_lat"], r["end_lng"]
        dist = r["distance_meters"] or 0.0

        if "FLY" in atype or slat is None or elat is None:
            continue
        if slat == elat and slng == elng:
            continue

        try:
            pts = json.loads(r["path_points_json"]) if r["path_points_json"] else []
        except Exception:
            pts = []

        # Needs snapping if currently straight or <= 2 points
        if len(pts) <= 2 or is_collinear_or_straight(pts):
            if dist >= 25.0 or (abs(slat - elat) > 0.0002 or abs(slng - elng) > 0.0002):
                osrm_mode = "bike" if "CYC" in atype else ("foot" if any(k in atype for k in ["WALK", "FOOT"]) else "driving")
                rk = f"{osrm_mode}:{slat:.5f},{slng:.5f};{elat:.5f},{elng:.5f}"
                to_snap.append((sid, rk, osrm_mode, slat, slng, elat, elng, dist))
                if rk not in to_query:
                    to_query[rk] = (slat, slng, elat, elng, osrm_mode)

    print(f"  Found {len(to_snap):,} activities to snap across {len(to_query):,} unique routes.")

    # 2. Query OSRM in parallel
    print("[2/3] Fetching OSRM road curves...")
    fetched_routes: Dict[str, Tuple[List[List[float]], float]] = {}

    # Check cache first
    c_cache.execute("SELECT route_key, geometry_json, distance_m FROM route_cache WHERE geometry_json IS NOT NULL;")
    for rk, geom, dist in c_cache.fetchall():
        if rk in to_query:
            try:
                pts = json.loads(geom)
                if len(pts) >= 3 and not is_collinear_or_straight(pts):
                    fetched_routes[rk] = (pts, dist or 0.0)
            except Exception:
                pass

    missing_query = {rk: v for rk, v in to_query.items() if rk not in fetched_routes}
    print(f"  {len(fetched_routes):,} routes loaded from cache; {len(missing_query):,} routes to fetch via network.")

    if missing_query:
        def worker(item):
            rk, (slat, slng, elat, elng, mode) = item
            pts, dist = query_osrm_single(slat, slng, elat, elng, mode)
            return rk, pts, dist, mode

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker, (rk, v)) for rk, v in missing_query.items()]
            success = 0
            for fut in as_completed(futures):
                rk, pts, dist, mode = fut.result()
                if pts and len(pts) >= 3 and not is_collinear_or_straight(pts):
                    fetched_routes[rk] = (pts, dist or 0.0)
                    c_cache.execute(
                        "INSERT OR REPLACE INTO route_cache (route_key, mode, geometry_json, distance_m, duration_s) VALUES (?, ?, ?, ?, ?);",
                        (rk, mode, json.dumps(pts), dist or 0.0, 300.0)
                    )
                    success += 1
            conn_cache.commit()
            print(f"  [✓] Successfully fetched {success:,} / {len(missing_query):,} genuine road curves.")

    # Update 2026 activities
    updates_2026 = []
    for sid, rk, mode, slat, slng, elat, elng, dist in to_snap:
        if rk in fetched_routes:
            pts, rdist = fetched_routes[rk]
            # Don't apply route if distance is drastically inflated for micro moves
            if dist < 40.0 and rdist > 300.0:
                updates_2026.append((None, 0, sid))
            else:
                updates_2026.append((json.dumps(pts), 1, sid))
        else:
            updates_2026.append((None, 0, sid))

    if updates_2026:
        c.executemany("UPDATE segments SET path_points_json = ?, has_snapped_path = ? WHERE id = ?;", updates_2026)
        conn.commit()
        snapped_count = sum(1 for _, s, _ in updates_2026 if s == 1)
        chord_count = sum(1 for _, s, _ in updates_2026 if s == 0)
        print(f"  [✓] Updated {len(updates_2026):,} 2026 activities ({snapped_count:,} snapped to road curves, {chord_count:,} reset to clean chords).")

    # 3. Cleanse all straight lines with has_snapped_path = 1 across entire DB
    print("[3/3] Auditing all has_snapped_path = 1 activities across entire database...")
    c.execute("""
        SELECT id, path_points_json
        FROM segments
        WHERE segment_type = 'activity' AND has_snapped_path = 1;
    """)
    all_snapped = c.fetchall()
    falsely_snapped = []

    for r in all_snapped:
        sid = r["id"]
        pts_json = r["path_points_json"]
        try:
            pts = json.loads(pts_json) if pts_json else []
        except Exception:
            pts = []

        if is_collinear_or_straight(pts):
            # Cleanse: straight line is NEVER snapped
            new_pts = None if len(pts) <= 2 else pts_json
            falsely_snapped.append((new_pts, 0, sid))

    if falsely_snapped:
        print(f"  Found {len(falsely_snapped):,} straight lines with has_snapped_path = 1. Cleansing to has_snapped_path = 0...")
        c.executemany("UPDATE segments SET path_points_json = ?, has_snapped_path = ? WHERE id = ?;", falsely_snapped)
        conn.commit()
        print(f"  [✓] Cleansed {len(falsely_snapped):,} false straight-line snapped flags.")
    else:
        print("  [✓] Zero falsely-snapped straight lines found.")

    # Final verification
    c.execute("""
        SELECT count(*)
        FROM segments
        WHERE segment_type = 'activity' AND has_snapped_path = 1 AND (path_points_json IS NULL OR length(path_points_json) < 20);
    """)
    bad_count = c.fetchone()[0]
    print(f"  Verification: has_snapped_path = 1 with NULL or tiny path: {bad_count}")

    conn_cache.close()
    conn.close()
    print("=================================================================")
    print("  SNAP & CLEANSE COMPLETED SUCCESSFULLY.")
    print("=================================================================")


if __name__ == "__main__":
    main()
