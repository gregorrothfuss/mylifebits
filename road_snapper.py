"""
High-Resolution Street-Following Road Snapping Engine.

Expands waypoints and straight chord segments into high-density road-following 
street curves using real OpenStreetMap / OSRM routing.
"""

import json
import os
import sqlite3
import ssl
import urllib.request
from typing import List, Optional, Tuple

CACHE_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapped_routes_cache.db")
_SSL_CTX = ssl.create_default_context()
_MAX_OSRM_BYTES = 2 * 1024 * 1024


def init_cache() -> None:
    conn = sqlite3.connect(CACHE_DB)
    try:
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
    finally:
        conn.close()


def query_osrm_api(
    lat1: float, lon1: float, lat2: float, lon2: float, osrm_mode: str = "driving"
) -> Tuple[Optional[List[List[float]]], Optional[float]]:
    """Queries public OSRM router for real OpenStreetMap geometry."""
    try:
        osrm_base = os.environ.get("OSRM_BASE_URL", "https://router.project-osrm.org").rstrip("/")
        profile = osrm_mode if osrm_mode in ("driving", "walking", "cycling", "foot", "bike", "car") else "driving"
        url = (
            f"{osrm_base}/route/v1/{profile}/"
            f"{lon1:.6f},{lat1:.6f};{lon2:.6f},{lat2:.6f}?overview=full&geometries=geojson"
        )
        ua = os.environ.get("HTTP_USER_AGENT", "MyLifeBits/1.0")
        req = urllib.request.Request(url, headers={"User-Agent": ua})
        with urllib.request.urlopen(req, timeout=5, context=_SSL_CTX) as resp:
            raw = resp.read(_MAX_OSRM_BYTES + 1)
            if len(raw) > _MAX_OSRM_BYTES:
                return None, None
            data = json.loads(raw.decode("utf-8"))
            if data.get("code") == "Ok" and data.get("routes"):
                coords = data["routes"][0]["geometry"]["coordinates"]  # [[lng, lat], ...]
                pts = [[round(float(c[1]), 6), round(float(c[0]), 6)] for c in coords]
                dist = float(data["routes"][0]["distance"])
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
        return (abs(p2[0] - p1[0]) < 1e-5 and abs(p2[1] - p3[1]) < 1e-5) or (
            abs(p2[0] - p3[0]) < 1e-5 and abs(p2[1] - p1[1]) < 1e-5
        )
    if len(pts) in [4, 5] and pts[0] == pts[-1]:
        return True
    return False


def snap_activity_to_streets(
    waypoints: List[List[float]],
    mode: str = "CYCLING",
) -> List[List[float]]:
    """
    Given waypoints [[lat, lng], ...], generates a high-resolution, street-following path
    along actual road and bridge geometries using OSRM.
    """
    if not waypoints or len(waypoints) < 1:
        return waypoints
    if len(waypoints) == 1:
        return waypoints

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

    osrm_mode = "bike"
    is_foot = any(k in m_upper for k in ["WALK", "FOOT", "RUN", "HIK"])
    if is_foot:
        osrm_mode = "foot"
    elif any(k in m_upper for k in ["CAR", "DRIV", "VEHICLE", "TAXI", "BUS"]):
        osrm_mode = "driving"

    s_lat, s_lng = start_pt[0], start_pt[1]
    e_lat, e_lng = end_pt[0], end_pt[1]
    route_key = f"{osrm_mode}:{s_lat:.5f},{s_lng:.5f};{e_lat:.5f},{e_lng:.5f}"

    conn = sqlite3.connect(CACHE_DB)
    try:
        c = conn.cursor()
        c.execute("SELECT geometry_json FROM route_cache WHERE route_key = ?;", (route_key,))
        row = c.fetchone()
        if row:
            coords: List[List[float]] = json.loads(row[0])
            if len(coords) >= 2 and not is_synthetic_rectangle_path(coords):
                return coords

        pts, dist = query_osrm_api(s_lat, s_lng, e_lat, e_lng, osrm_mode)
        if pts and len(pts) >= 2:
            c.execute(
                "INSERT OR REPLACE INTO route_cache (route_key, mode, geometry_json, distance_m, duration_s) VALUES (?, ?, ?, ?, ?);",
                (route_key, osrm_mode, json.dumps(pts), dist or 0.0, 300.0),
            )
            conn.commit()
            return pts

        if len(waypoints) > 2 and not is_synthetic_rectangle_path(waypoints):
            return waypoints

        return [start_pt, end_pt]
    finally:
        conn.close()


if __name__ == "__main__":
    test_pts = snap_activity_to_streets([[40.7527, -73.9772], [40.7680, -73.9680]], mode="CYCLING")
    print(f"Test snapped path returned {len(test_pts)} points.")
