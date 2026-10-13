"""
Immersive Trips & Expeditions Clustering Engine.

Clusters multi-day travel away from home (Singapore, Morocco, Japan, Swiss Alps, etc.),
aggregates destinations, calculates true flight/ground distances, and generates
continuous high-density waypoint sequences for cinematic 3D Flythroughs.
"""

import sqlite3
import datetime
import json
import os
from typing import Dict, Any, List, Optional
from breadcrumbs import haversine_distance
from road_snapper import snap_activity_to_streets


def get_all_trips(db_path: str = "timeline_viewer.db", limit: int = 150, country: str = None) -> List[Dict[str, Any]]:
    """
    Returns an enriched list of all multi-day trips and expeditions from the materialized trips table.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    if country and country != "ALL":
        c.execute("""
        SELECT * FROM trips
        WHERE country = ? OR title LIKE ?
        ORDER BY start_date DESC
        LIMIT ?;
        """, (country, f"%{country}%", limit))
    else:
        c.execute("""
        SELECT * FROM trips
        ORDER BY start_date DESC
        LIMIT ?;
        """, (limit,))
        
    rows = c.fetchall()
    trips = []
    
    for r in rows:
        t = dict(r)
        if t.get("highlights_json"):
            try:
                t["highlights"] = json.loads(t["highlights_json"])
            except Exception:
                t["highlights"] = []
        else:
            t["highlights"] = []
        trips.append(t)
        
    conn.close()
    conn.close()
    return trips


def generate_trip_flythrough_data(
    trip_id: str,
    db_path: str = "timeline_viewer.db"
) -> Dict[str, Any]:
    """
    Generates a full cinematic flythrough trajectory with continuous waypoints,
    camera headings, and POI hotspots for the 3D player.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # 1. Fetch trip metadata from trips table or memories table
    c.execute("SELECT * FROM trips WHERE trip_id = ?;", (trip_id,))
    t_row = c.fetchone()
    if not t_row:
        c.execute("SELECT * FROM memories WHERE memory_id = ?;", (trip_id,))
        t_row = c.fetchone()
        
    if not t_row:
        conn.close()
        return {"status": "ERROR", "error": "Trip not found"}
        
    st_ts = t_row["start_ts"]
    end_ts = t_row["end_ts"]
    title = t_row["title"] if "title" in t_row.keys() else "Expedition"
    st_date = t_row["start_date"] if "start_date" in t_row.keys() else t_row["date"]
    
    # 2. Fetch all segments in chronological order
    c.execute("""
    SELECT s.id, s.segment_type, s.start_time, s.end_time, s.start_ts, s.end_ts,
           s.duration_minutes, s.activity_type, s.distance_meters, s.path_points_json,
           s.latitude, s.longitude, s.end_lat, s.end_lng, s.place_name, s.place_address,
           s.category, p.review_rating, p.review_text
    FROM segments s
    LEFT JOIN places p ON s.place_id = p.place_id
    WHERE s.start_ts >= ? AND s.end_ts <= ?
    ORDER BY s.start_ts ASC;
    """, (st_ts, end_ts))
    segments = [dict(r) for r in c.fetchall()]
    
    ground_points = []
    flight_arcs = []
    hotspots = []
    
    for s in segments:
        if s["segment_type"] == "visit":
            lat = s.get("latitude")
            lng = s.get("longitude")
            if lat and lng:
                title = s.get("place_name") or "Place Stop"
                hotspots.append({
                    "segment_id": s["id"],
                    "title": title,
                    "address": s.get("place_address") or "",
                    "category": s.get("category") or "Other / POI",
                    "lat": lat,
                    "lng": lng,
                    "time": s["start_time"][11:16] if s.get("start_time") else "",
                    "date": s["start_time"][:10] if s.get("start_time") else "",
                    "duration_mins": s.get("duration_minutes", 0),
                    "rating": s.get("review_rating"),
                    "review": s.get("review_text"),
                    "streetview_url": f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lng}"
                })
                ground_points.append({
                    "lat": lat,
                    "lng": lng,
                    "mode": "STATIONARY",
                    "title": title,
                    "timestamp": s["start_ts"]
                })
                
        elif s["segment_type"] == "activity":
            mode = (s.get("activity_type") or "TRAVEL").upper()
            coords = []
            if s.get("path_points_json"):
                try:
                    coords = json.loads(s["path_points_json"])
                except Exception:
                    coords = []
            if not coords and s.get("latitude") and s.get("end_lat"):
                coords = [[s["latitude"], s["longitude"]], [s["end_lat"], s["end_lng"]]]
                
            if coords:
                if mode == "FLYING" or (s.get("distance_meters") or 0) > 300000:
                    flight_arcs.append({
                        "from": coords[0],
                        "to": coords[-1],
                        "distance_km": round((s.get("distance_meters") or 0) / 1000.0, 1),
                        "start_time": s.get("start_time", ""),
                        "end_time": s.get("end_time", "")
                    })
                else:
                    for pt in coords:
                        ground_points.append({
                            "lat": pt[0],
                            "lng": pt[1],
                            "mode": mode,
                            "title": mode,
                            "timestamp": s["start_ts"]
                        })
                    
    conn.close()
    return {
        "status": "SUCCESS",
        "trip_id": trip_id,
        "title": title or "Expedition",
        "start_date": st_date or "",
        "waypoints_count": len(ground_points),
        "hotspots_count": len(hotspots),
        "trajectory": ground_points,
        "flight_arcs": flight_arcs,
        "hotspots": hotspots
    }
