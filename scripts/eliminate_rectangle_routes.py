#!/usr/bin/env python3
"""
Eliminate Synthetic Rectangle Routes and Snap Authentic Road Curves.

1. Identifies all synthetic axis-aligned L-step corner paths and closed bounding boxes.
2. Fetches high-resolution street/transit curves via OSRM for all 2026 activities.
3. Updates timeline_viewer.db:
   - Replaces 2026 synthetic rectangles with genuine road curves.
   - Cleanses older synthetic rectangles, resetting them to honest straight-line chords.
4. Ensures 0 synthetic rectangles remain in the database.
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


def is_synthetic_rectangle(pts: List[List[float]]) -> bool:
    """Detects artificial axis-aligned L-step corners or bounding boxes."""
    if not pts:
        return False
    if len(pts) == 3:
        p1, p2, p3 = pts[0], pts[1], pts[2]
        # Intermediate point matches p1 latitude & p3 longitude, or p3 latitude & p1 longitude
        return (abs(p2[0] - p1[0]) < 1e-5 and abs(p2[1] - p3[1]) < 1e-5) or \
               (abs(p2[0] - p3[0]) < 1e-5 and abs(p2[1] - p1[1]) < 1e-5)
    if len(pts) in [4, 5] and pts[0] == pts[-1]:
        return True
    return False


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
    print("      ELIMINATE SYNTHETIC RECTANGLES & RESTORE ROAD CURVES       ")
    print("=================================================================")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    conn_cache = sqlite3.connect(CACHE_DB_PATH)
    c_cache = conn_cache.cursor()

    # 1. Scan for all synthetic rectangle paths
    print("[1/4] Scanning for synthetic rectangle paths...")
    c.execute("""
        SELECT id, date, activity_type, latitude, longitude, end_lat, end_lng, path_points_json
        FROM segments
        WHERE segment_type = 'activity' AND path_points_json IS NOT NULL;
    """)
    all_acts = c.fetchall()

    fake_2026 = []
    fake_older = []

    for r in all_acts:
        pts_json = r["path_points_json"]
        try:
            pts = json.loads(pts_json)
        except Exception:
            continue

        if is_synthetic_rectangle(pts):
            if r["date"] >= "2026-01-01":
                fake_2026.append(r)
            else:
                fake_older.append(r)

    print(f"  Found {len(fake_2026):,} fake rectangle activities in 2026.")
    print(f"  Found {len(fake_older):,} fake rectangle activities in older years.")
    total_fake = len(fake_2026) + len(fake_older)
    print(f"  Total synthetic rectangle activities to cleanse: {total_fake:,}")

    # 2. Query OSRM for 2026 activities concurrently
    print("[2/4] Fetching genuine road curves for 2026 activities via OSRM...")
    to_query = {}
    for r in fake_2026:
        atype = (r["activity_type"] or "DRIVING").upper()
        if "FLY" in atype:
            continue
        slat, slng = r["latitude"], r["longitude"]
        elat, elng = r["end_lat"], r["end_lng"]
        if slat is None or elat is None or (slat == elat and slng == elng):
            continue

        osrm_mode = "bike" if "CYC" in atype else ("foot" if any(k in atype for k in ["WALK", "FOOT"]) else "driving")
        rk = f"{osrm_mode}:{slat:.5f},{slng:.5f};{elat:.5f},{elng:.5f}"
        if rk not in to_query:
            to_query[rk] = (slat, slng, elat, elng, osrm_mode)

    print(f"  Unique 2026 routes to fetch: {len(to_query):,}")
    fetched_routes: Dict[str, Tuple[List[List[float]], float]] = {}

    def worker(item):
        rk, (slat, slng, elat, elng, mode) = item
        pts, dist = query_osrm_single(slat, slng, elat, elng, mode)
        return rk, pts, dist, mode

    if to_query:
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker, (rk, v)) for rk, v in to_query.items()]
            success = 0
            for fut in as_completed(futures):
                rk, pts, dist, mode = fut.result()
                if pts and len(pts) >= 2 and not is_synthetic_rectangle(pts):
                    fetched_routes[rk] = (pts, dist or 0.0)
                    c_cache.execute(
                        "INSERT OR REPLACE INTO route_cache (route_key, mode, geometry_json, distance_m, duration_s) VALUES (?, ?, ?, ?, ?);",
                        (rk, mode, json.dumps(pts), dist or 0.0, 300.0)
                    )
                    success += 1
            conn_cache.commit()
            print(f"  [✓] Successfully fetched {success:,} / {len(to_query):,} genuine road curves.")

    # 3. Update 2026 activities in database
    print("[3/4] Updating 2026 activities in database...")
    updates_2026 = []
    for r in fake_2026:
        aid = r["id"]
        atype = (r["activity_type"] or "DRIVING").upper()
        slat, slng = r["latitude"], r["longitude"]
        elat, elng = r["end_lat"], r["end_lng"]
        osrm_mode = "bike" if "CYC" in atype else ("foot" if any(k in atype for k in ["WALK", "FOOT"]) else "driving")
        rk = f"{osrm_mode}:{slat:.5f},{slng:.5f};{elat:.5f},{elng:.5f}" if (slat and elat) else ""

        if rk in fetched_routes:
            pts, dist = fetched_routes[rk]
            updates_2026.append((json.dumps(pts), 1, aid))
        else:
            # Fall back to clean 2-point chord with has_snapped_path = 0
            updates_2026.append((None, 0, aid))

    if updates_2026:
        c.executemany("UPDATE segments SET path_points_json = ?, has_snapped_path = ? WHERE id = ?;", updates_2026)
        conn.commit()
        snapped_2026 = sum(1 for _, s, _ in updates_2026 if s == 1)
        chord_2026 = sum(1 for _, s, _ in updates_2026 if s == 0)
        print(f"  [✓] Updated {len(updates_2026):,} 2026 activities ({snapped_2026:,} snapped to road curves, {chord_2026:,} reset to chords).")

    # 4. Cleansing older synthetic rectangles
    print("[4/4] Cleansing older synthetic rectangles...")
    # Load cache keys to check if any older ones have genuine cached routes
    c_cache.execute("SELECT route_key, geometry_json FROM route_cache WHERE geometry_json IS NOT NULL;")
    cache_lookup = dict(c_cache.fetchall())

    updates_older = []
    for r in fake_older:
        aid = r["id"]
        atype = (r["activity_type"] or "DRIVING").upper()
        slat, slng = r["latitude"], r["longitude"]
        elat, elng = r["end_lat"], r["end_lng"]
        osrm_mode = "bike" if "CYC" in atype else ("foot" if any(k in atype for k in ["WALK", "FOOT"]) else "driving")
        rk = f"{osrm_mode}:{slat:.5f},{slng:.5f};{elat:.5f},{elng:.5f}" if (slat and elat) else ""

        if rk in cache_lookup:
            cached_geom = json.loads(cache_lookup[rk])
            if not is_synthetic_rectangle(cached_geom):
                updates_older.append((cache_lookup[rk], 1, aid))
                continue

        # Revert to honest straight-line chord
        updates_older.append((None, 0, aid))

    if updates_older:
        c.executemany("UPDATE segments SET path_points_json = ?, has_snapped_path = ? WHERE id = ?;", updates_older)
        conn.commit()
        snapped_older = sum(1 for _, s, _ in updates_older if s == 1)
        chord_older = sum(1 for _, s, _ in updates_older if s == 0)
        print(f"  [✓] Cleansed {len(updates_older):,} older activities ({snapped_older:,} restored from cache, {chord_older:,} reset to chords).")

    # Verification: check if ANY synthetic rectangles remain in DB
    c.execute("SELECT path_points_json FROM segments WHERE segment_type = 'activity' AND path_points_json IS NOT NULL;")
    remaining_fake = 0
    for (pts_json,) in c.fetchall():
        try:
            pts = json.loads(pts_json)
            if is_synthetic_rectangle(pts):
                remaining_fake += 1
        except Exception:
            pass

    print("=================================================================")
    print(f"  Cleansing Complete.")
    print(f"  Remaining synthetic rectangles: {remaining_fake}")
    print("=================================================================")

    conn_cache.close()
    conn.close()


if __name__ == "__main__":
    main()
