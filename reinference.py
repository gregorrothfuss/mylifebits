"""
Local ODLH Spatio-Temporal Re-Inference Engine.

Performs local semantic re-inference over cleaned GPS breadcrumbs to re-synthesize
high-fidelity Place Visits and clean Activity Travel segments without relying
on closed Google cloud or background services.
"""

import math
import sqlite3
import datetime
from typing import List, Dict, Any, Tuple, Optional
from breadcrumbs import haversine_distance


def cluster_stationary_points(points: List[Dict[str, Any]], max_radius_m: float = 45.0, min_dwell_s: int = 300) -> List[Dict[str, Any]]:
    """
    Groups raw breadcrumbs into stationary place visits using spatio-temporal dwell clustering.
    Returns synthesized visits and remaining moving points.
    """
    if not points:
        return []
        
    visits = []
    current_cluster = [points[0]]
    
    for i in range(1, len(points)):
        p = points[i]
        
        # Calculate centroid of current cluster
        c_lat = sum(x["lat"] for x in current_cluster) / len(current_cluster)
        c_lng = sum(x["lng"] for x in current_cluster) / len(current_cluster)
        
        dist_to_centroid = haversine_distance(c_lat, c_lng, p["lat"], p["lng"])
        
        if dist_to_centroid <= max_radius_m:
            current_cluster.append(p)
        else:
            # Cluster ended. Check if dwell duration qualifies as a visit
            start_ts = current_cluster[0]["timestamp"]
            end_ts = current_cluster[-1]["timestamp"]
            dwell_s = end_ts - start_ts
            
            if dwell_s >= min_dwell_s and len(current_cluster) >= 3:
                # Compute robust median centroid
                med_lat = sorted(x["lat"] for x in current_cluster)[len(current_cluster)//2]
                med_lng = sorted(x["lng"] for x in current_cluster)[len(current_cluster)//2]
                
                visits.append({
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                    "duration_minutes": round(dwell_s / 60.0, 1),
                    "latitude": round(med_lat, 7),
                    "longitude": round(med_lng, 7),
                    "point_count": len(current_cluster),
                    "points": current_cluster,
                })
            current_cluster = [p]
            
    # Handle trailing cluster
    if len(current_cluster) >= 3:
        start_ts = current_cluster[0]["timestamp"]
        end_ts = current_cluster[-1]["timestamp"]
        dwell_s = end_ts - start_ts
        if dwell_s >= min_dwell_s:
            med_lat = sorted(x["lat"] for x in current_cluster)[len(current_cluster)//2]
            med_lng = sorted(x["lng"] for x in current_cluster)[len(current_cluster)//2]
            visits.append({
                "start_ts": start_ts,
                "end_ts": end_ts,
                "duration_minutes": round(dwell_s / 60.0, 1),
                "latitude": round(med_lat, 7),
                "longitude": round(med_lng, 7),
                "point_count": len(current_cluster),
                "points": current_cluster,
            })
            
    return visits


def reinfer_day_timeline(db_path: str, date_str: str, exclude_anomalies: bool = True) -> Dict[str, Any]:
    """
    Executes local ODLH re-inference on a day's breadcrumbs and compares against current timeline.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # 1. Fetch raw breadcrumbs for the requested date
    if exclude_anomalies:
        c.execute("""
        SELECT id, timestamp, lat, lng, accuracy, speed_kmh, anomaly_type, anomaly_score
        FROM breadcrumbs
        WHERE date = ? AND is_excluded = 0 AND (anomaly_type IS NULL OR anomaly_type = 'DWELL_SCATTER')
        ORDER BY timestamp ASC;
        """, (date_str,))
    else:
        c.execute("""
        SELECT id, timestamp, lat, lng, accuracy, speed_kmh, anomaly_type, anomaly_score
        FROM breadcrumbs
        WHERE date = ? AND is_excluded = 0
        ORDER BY timestamp ASC;
        """, (date_str,))
        
    pts = [dict(row) for row in c.fetchall()]
    
    # 2. Fetch existing segments for baseline comparison
    c.execute("""
    SELECT id, segment_type, start_time, end_time, start_ts, end_ts, duration_minutes,
           place_name, activity_type, distance_meters, latitude, longitude
    FROM segments
    WHERE date = ?
    ORDER BY start_ts ASC;
    """, (date_str,))
    existing_segments = [dict(row) for row in c.fetchall()]
    
    if not pts:
        conn.close()
        return {
            "date": date_str,
            "raw_point_count": 0,
            "reinferred_visits": [],
            "reinferred_activities": [],
            "existing_segment_count": len(existing_segments),
            "quality_gain": "No raw breadcrumbs available for this date"
        }
        
    # 3. Perform spatio-temporal dwell clustering
    reinferred_visits = cluster_stationary_points(pts)
    
    # 4. Resolve POI names from existing database
    for v in reinferred_visits:
        # Find nearest known place within 80m
        c.execute("""
        SELECT place_name, place_id, category, city, latitude, longitude
        FROM segments
        WHERE segment_type = 'visit' AND place_name IS NOT NULL
          AND ABS(latitude - ?) < 0.001 AND ABS(longitude - ?) < 0.001
        LIMIT 1;
        """, (v["latitude"], v["longitude"]))
        match = c.fetchone()
        if match:
            v["place_name"] = match["place_name"]
            v["place_id"] = match["place_id"]
            v["category"] = match["category"]
            v["city"] = match["city"]
        else:
            c.execute("""
            SELECT name, place_id, category, city, latitude, longitude
            FROM places
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL
              AND ABS(latitude - ?) < 0.001 AND ABS(longitude - ?) < 0.001
            LIMIT 1;
            """, (v["latitude"], v["longitude"]))
            pmatch = c.fetchone()
            if pmatch:
                v["place_name"] = pmatch["name"]
                v["place_id"] = pmatch["place_id"]
                v["category"] = pmatch["category"] or "Other / POI"
                v["city"] = pmatch["city"]
            else:
                v["place_name"] = f"Synthesized Place ({v['latitude']:.4f}, {v['longitude']:.4f})"
                v["category"] = "Unknown"
                
    # 5. Synthesize travel segments between visits
    reinferred_activities = []
    for i in range(len(reinferred_visits) - 1):
        v_prev = reinferred_visits[i]
        v_next = reinferred_visits[i + 1]
        
        act_start = v_prev["end_ts"]
        act_end = v_next["start_ts"]
        dur_s = act_end - act_start
        
        if dur_s > 60:
            dist_m = haversine_distance(v_prev["latitude"], v_prev["longitude"], v_next["latitude"], v_next["longitude"])
            speed_kmh = (dist_m / dur_s) * 3.6 if dur_s > 0 else 0
            
            mode = "WALKING"
            if speed_kmh > 45:
                mode = "DRIVING"
            elif speed_kmh > 15:
                mode = "CYCLING"
            elif speed_kmh > 6:
                mode = "RUNNING"
                
            reinferred_activities.append({
                "start_ts": act_start,
                "end_ts": act_end,
                "duration_minutes": round(dur_s / 60.0, 1),
                "start_lat": v_prev["latitude"],
                "start_lng": v_prev["longitude"],
                "end_lat": v_next["latitude"],
                "end_lng": v_next["longitude"],
                "distance_meters": round(dist_m, 1),
                "speed_kmh": round(speed_kmh, 1),
                "activity_type": mode
            })
            
    conn.close()
    
    return {
        "date": date_str,
        "raw_point_count": len(pts),
        "reinferred_visits": reinferred_visits,
        "reinferred_activities": reinferred_activities,
        "existing_segment_count": len(existing_segments),
        "existing_segments": existing_segments,
        "quality_gain": f"Synthesized {len(reinferred_visits)} verified visits and {len(reinferred_activities)} clean travel paths from {len(pts)} GPS fixes."
    }
