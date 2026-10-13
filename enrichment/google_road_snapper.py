"""
Official Google Roads & Routes API v2 Snapping Engine
Handles both road snapping (snapToRoads) and transit network routing (computeRoutes with TRANSIT)
for Subways, Commuter Trains, Trams, Buses, Ferries, Drives, and Cycling.
"""

import sqlite3
import urllib.request
import json
import os
import sys
import time
from typing import List, Optional, Tuple

DEFAULT_DB_PATH = "timeline_viewer.db"
DEFAULT_API_KEY = ""


def decode_google_polyline(polyline_str: str) -> List[List[float]]:
    """Decodes a Google encoded polyline string into [[lat, lng], ...]"""
    index, lat, lng = 0, 0, 0
    coordinates = []
    length = len(polyline_str)

    while index < length:
        # Latitude
        shift, result = 0, 0
        while True:
            byte = ord(polyline_str[index]) - 63
            index += 1
            result |= (byte & 0x1F) << shift
            shift += 5
            if byte < 0x20:
                break
        delta_lat = ~(result >> 1) if (result & 1) else (result >> 1)
        lat += delta_lat

        # Longitude
        shift, result = 0, 0
        while True:
            byte = ord(polyline_str[index]) - 63
            index += 1
            result |= (byte & 0x1F) << shift
            shift += 5
            if byte < 0x20:
                break
        delta_lng = ~(result >> 1) if (result & 1) else (result >> 1)
        lng += delta_lng

        coordinates.append([lat / 1e5, lng / 1e5])

    return coordinates


def snap_points_via_google_roads(points: List[List[float]], api_key: str) -> Optional[List[List[float]]]:
    """Snaps up to 100 raw GPS fixes to physical road geometries using Google Roads API."""
    if not points or len(points) < 2:
        return None
    sample = points[::max(1, len(points) // 95)][:95]
    path_str = "|".join([f"{p[0]},{p[1]}" for p in sample])
    url = f"https://roads.googleapis.com/v1/snapToRoads?path={path_str}&interpolate=true&key={api_key}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GoogleTimelineStudio/2.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            snapped = data.get("snappedPoints", [])
            if snapped:
                return [[p["location"]["latitude"], p["location"]["longitude"]] for p in snapped]
    except Exception:
        pass
    return None


def compute_route_via_google_routes(
    start: Tuple[float, float], end: Tuple[float, float], mode: str, api_key: str
) -> Optional[List[List[float]]]:
    """
    Synthesizes physical transit or road path between endpoints via Google Routes API v2.
    Supports SUBWAY, TRAIN, TRAM, BUS, FERRY, DRIVE, WALK, and BICYCLE.
    """
    m_upper = (mode or "").upper()
    
    # 1. Determine Google Routes travelMode & transitPreferences
    if any(k in m_upper for k in ["SUBWAY", "METRO"]):
        travel_mode = "TRANSIT"
        transit_prefs = {"allowedTravelModes": ["SUBWAY", "TRAIN"]}
    elif any(k in m_upper for k in ["TRAIN", "RAIL"]):
        travel_mode = "TRANSIT"
        transit_prefs = {"allowedTravelModes": ["TRAIN", "SUBWAY"]}
    elif "TRAM" in m_upper:
        travel_mode = "TRANSIT"
        transit_prefs = {"allowedTravelModes": ["LIGHT_RAIL", "SUBWAY"]}
    elif "BUS" in m_upper:
        travel_mode = "TRANSIT"
        transit_prefs = {"allowedTravelModes": ["BUS"]}
    elif "FERRY" in m_upper:
        travel_mode = "TRANSIT"
        transit_prefs = {"allowedTravelModes": ["BUS", "SUBWAY"]}
    elif any(k in m_upper for k in ["WALK", "FOOT", "RUN"]):
        travel_mode = "WALK"
        transit_prefs = None
    elif any(k in m_upper for k in ["CYCLE", "BIKE"]):
        travel_mode = "BICYCLE"
        transit_prefs = None
    else:
        travel_mode = "DRIVE"
        transit_prefs = None

    url = f"https://routes.googleapis.com/directions/v2:computeRoutes?key={api_key}"
    req_payload = {
        "origin": {"location": {"latLng": {"latitude": start[0], "longitude": start[1]}}},
        "destination": {"location": {"latLng": {"latitude": end[0], "longitude": end[1]}}},
        "travelMode": travel_mode,
    }
    if transit_prefs:
        req_payload["transitPreferences"] = transit_prefs

    headers = {
        "Content-Type": "application/json",
        "X-Goog-FieldMask": "routes.distanceMeters,routes.duration,routes.polyline.encodedPolyline",
    }
    try:
        body = json.dumps(req_payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            routes = data.get("routes", [])
            if routes and routes[0].get("polyline", {}).get("encodedPolyline"):
                poly = routes[0]["polyline"]["encodedPolyline"]
                return decode_google_polyline(poly)
    except Exception:
        pass
    return None


def batch_snap_all_activities(api_key: str, db_path: str = DEFAULT_DB_PATH, limit: int = 100) -> int:
    conn = sqlite3.connect(db_path, timeout=30.0)
    c = conn.cursor()
    c.execute("""
    SELECT id, activity_type, latitude, longitude, end_lat, end_lng, start_ts, end_ts
    FROM segments
    WHERE segment_type = 'activity'
      AND (has_snapped_path = 0 OR has_snapped_path IS NULL)
      AND (activity_type != 'FLYING' AND distance_meters < 300000)
      AND latitude IS NOT NULL AND end_lat IS NOT NULL
    ORDER BY date DESC
    LIMIT ?;
    """, (limit,))
    rows = c.fetchall()
    print(f"[*] Processing {len(rows)} unsnapped activity/transit legs via Google Routes & Roads API...")

    snapped_count = 0
    for sid, act_type, s_lat, s_lng, e_lat, e_lng, s_ts, e_ts in rows:
        # 1. For ground vehicular with raw breadcrumbs, use Roads API snap
        snapped_coords = None
        is_transit = any(k in (act_type or "").upper() for k in ["SUBWAY", "TRAIN", "TRAM", "BUS", "FERRY"])

        if not is_transit:
            c.execute("""
            SELECT lat, lng FROM breadcrumbs
            WHERE timestamp >= ? AND timestamp <= ? AND (is_excluded = 0 OR is_excluded IS NULL)
            ORDER BY timestamp ASC;
            """, (int(s_ts), int(e_ts)))
            bc = c.fetchall()
            if bc and len(bc) >= 3:
                snapped_coords = snap_points_via_google_roads([[r[0], r[1]] for r in bc], api_key)

        # 2. For transit movements or missing breadcrumbs, route via Google Routes API v2
        if not snapped_coords:
            snapped_coords = compute_route_via_google_routes((s_lat, s_lng), (e_lat, e_lng), act_type, api_key)

        if snapped_coords and len(snapped_coords) >= 2:
            # Anchor directly to origin and destination visit coordinates to eliminate visual disconnects
            if s_lat and s_lng:
                d_start = ((snapped_coords[0][0] - s_lat)**2 + (snapped_coords[0][1] - s_lng)**2)**0.5
                if d_start > 0.00005 and d_start < 0.01:
                    snapped_coords.insert(0, [s_lat, s_lng])
            if e_lat and e_lng:
                d_end = ((snapped_coords[-1][0] - e_lat)**2 + (snapped_coords[-1][1] - e_lng)**2)**0.5
                if d_end > 0.00005 and d_end < 0.01:
                    snapped_coords.append([e_lat, e_lng])

            c.execute("""
            UPDATE segments
            SET path_points_json = ?,
                has_snapped_path = 1
            WHERE id = ?;
            """, (json.dumps(snapped_coords), sid))
            conn.commit()
            snapped_count += 1
            print(f"  [✓] Snapped {act_type} Leg #{sid}: {len(snapped_coords)} geometry coordinates")
        time.sleep(0.06)

    conn.close()
    print(f"[✓] Batch Complete: {snapped_count}/{len(rows)} legs snapped to physical road/transit networks.")
    return snapped_count


if __name__ == "__main__":
    key = os.environ.get("GOOGLE_MAPS_API_KEY") or os.environ.get("GOOGLE_API_KEY") or DEFAULT_API_KEY
    batch_snap_all_activities(key)
