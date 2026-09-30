"""
High-Resolution Street-Following Road Snapping Engine.

Expands waypoints and straight chord segments into high-density road-following 
street curves using real OpenStreetMap / OSRM routing.
"""

import urllib.request
import json
import sqlite3
import os
import math
import time
from typing import List, Tuple, Optional

CACHE_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapped_routes_cache.db")

def init_cache():
    conn = sqlite3.connect(CACHE_DB)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS route_cache (
        route_key TEXT PRIMARY KEY,
        mode TEXT,
        geometry_json TEXT,
        distance_m REAL,
        duration_s REAL
    );
    """)
    conn.commit()
    conn.close()

def query_osrm_api(lat1: float, lon1: float, lat2: float, lon2: float, osrm_mode: str = 'driving') -> Tuple[Optional[List[List[float]]], Optional[float]]:
    """Queries public OSRM router for real OpenStreetMap geometry."""
    try:
        url = f"http://router.project-osrm.org/route/v1/{osrm_mode}/{lon1:.6f},{lat1:.6f};{lon2:.6f},{lat2:.6f}?overview=full&geometries=geojson"
        req = urllib.request.Request(url, headers={'User-Agent': 'GregorMyLifeBits/1.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            if data.get('code') == 'Ok' and data.get('routes'):
                coords = data['routes'][0]['geometry']['coordinates'] # [ [lng, lat], ... ]
                pts = [[round(c[1], 6), round(c[0], 6)] for c in coords]
                dist = data['routes'][0]['distance']
                return pts, dist
    except Exception:
        pass
    return None, None

def is_synthetic_rectangle_path(pts: List[List[float]]) -> bool:
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

def snap_activity_to_streets(
    waypoints: List[List[float]],
    mode: str = "CYCLING"
) -> List[List[float]]:
    """
    Given waypoints [[lat, lng], ...], generates a high-resolution, street-following path
    along actual road and bridge geometries using OSRM.
    """
    if not waypoints or len(waypoints) < 1:
        return waypoints
    if len(waypoints) == 1:
        return waypoints

    # Strip synthetic rectangle L-step corners or bounding boxes
    if is_synthetic_rectangle_path(waypoints):
        waypoints = [waypoints[0], waypoints[-1]]
        
    start_pt = waypoints[0]
    end_pt = waypoints[-1]
    
    if not start_pt or not end_pt or None in start_pt or None in end_pt:
        return waypoints
        
    m_upper = (mode or "").upper()
    if "FLY" in m_upper:
        return [start_pt, end_pt]
        
    init_cache()
    
    # Determine routing profile
    osrm_mode = "bike"
    is_foot = any(k in m_upper for k in ["WALK", "FOOT", "RUN", "HIK"])
    if is_foot:
        osrm_mode = "foot"
    elif any(k in m_upper for k in ["CAR", "DRIV", "VEHICLE", "TAXI", "BUS"]):
        osrm_mode = "driving"
        
    # Check cache
    s_lat, s_lng = start_pt[0], start_pt[1]
    e_lat, e_lng = end_pt[0], end_pt[1]
    route_key = f"{osrm_mode}:{s_lat:.5f},{s_lng:.5f};{e_lat:.5f},{e_lng:.5f}"
    
    conn = sqlite3.connect(CACHE_DB)
    c = conn.cursor()
    c.execute("SELECT geometry_json FROM route_cache WHERE route_key = ?;", (route_key,))
    row = c.fetchone()
    if row:
        coords = json.loads(row[0])
        conn.close()
        if len(coords) >= 2 and not is_synthetic_rectangle_path(coords):
            return coords

    # Query real OSRM
    pts, dist = query_osrm_api(s_lat, s_lng, e_lat, e_lng, osrm_mode)
    if pts and len(pts) >= 2:
        c.execute("INSERT OR REPLACE INTO route_cache (route_key, mode, geometry_json, distance_m, duration_s) VALUES (?, ?, ?, ?, ?);",
                  (route_key, osrm_mode, json.dumps(pts), dist or 0.0, 300.0))
        conn.commit()
        conn.close()
        return pts

    # If intermediate waypoints were provided (e.g. 3+ points and non-synthetic), interpolate between them
    if len(waypoints) > 2 and not is_synthetic_rectangle_path(waypoints):
        conn.close()
        return waypoints

    # Fallback to direct linear interpolation if network fails
    conn.close()
    return [start_pt, end_pt]

if __name__ == "__main__":
    test_pts = snap_activity_to_streets([[40.7205, -73.9792], [40.7025, -73.9863]], mode="CYCLING")
    print(f"Test snapped path returned {len(test_pts)} points.")
