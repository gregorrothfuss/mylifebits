"""
3D Route Ride-Along and Tour Engine.
Extracts smooth road-snapped trajectories, bearings, speeds, and Google Earth KML exports.
"""

import sqlite3
import json
import math
import datetime
from typing import Dict, Any, List, Optional
from enrichment.kml_tour_generator import calculate_bearing, generate_earth_tour_kml
from breadcrumbs import haversine_distance


def interpolate_points(pts: List[List[float]], max_step_meters: float = 25.0) -> List[List[float]]:
    """Interpolates coordinates along a polyline so 3D camera glides smoothly."""
    if not pts or len(pts) < 2:
        return pts
    
    dense_pts = []
    for i in range(len(pts) - 1):
        p1 = pts[i]
        p2 = pts[i+1]
        dense_pts.append(p1)
        
        dist = haversine_distance(p1[0], p1[1], p2[0], p2[1])
        if dist > max_step_meters:
            num_steps = int(dist / max_step_meters)
            for s in range(1, num_steps):
                frac = s / float(num_steps)
                lat = p1[0] + (p2[0] - p1[0]) * frac
                lng = p1[1] + (p2[1] - p1[1]) * frac
                dense_pts.append([lat, lng])
                
    dense_pts.append(pts[-1])
    return dense_pts


def get_segment_tour_data(segment_id: int, db_path: str = "timeline_viewer.db") -> Dict[str, Any]:
    """Generates 3D ride-along tour data for a single movement segment."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
    SELECT s.*, p.place_name as prev_place, p.place_address as prev_addr
    FROM segments s
    LEFT JOIN segments p ON p.end_ts <= s.start_ts AND p.segment_type = 'visit'
    WHERE s.id = ?
    ORDER BY p.end_ts DESC LIMIT 1;
    """, (segment_id,))
    seg = c.fetchone()
    if not seg:
        conn.close()
        return {"status": "ERROR", "error": "Segment not found"}

    # Destination visit
    c.execute("""
    SELECT place_name, place_address FROM segments
    WHERE start_ts >= ? AND segment_type = 'visit'
    ORDER BY start_ts ASC LIMIT 1;
    """, (seg['end_ts'],))
    next_v = c.fetchone()

    # Extract coordinates
    coords = []
    if seg['path_points_json']:
        try:
            coords = json.loads(seg['path_points_json'])
        except Exception:
            coords = []

    # Fallback to breadcrumbs if no polyline
    if not coords or len(coords) < 2:
        c.execute("""
        SELECT lat, lng, timestamp FROM breadcrumbs
        WHERE timestamp >= ? AND timestamp <= ?
        ORDER BY timestamp ASC;
        """, (int(seg['start_ts']), int(seg['end_ts'])))
        bc_pts = [[r['lat'], r['lng']] for r in c.fetchall()]
        if len(bc_pts) >= 2:
            coords = bc_pts

    # Fallback to start/end coords
    if not coords and seg['latitude'] and seg['end_lat']:
        coords = [[seg['latitude'], seg['longitude']], [seg['end_lat'], seg['end_lng']]]
    elif not coords and seg['latitude']:
        coords = [[seg['latitude'], seg['longitude']]]

    # Interpolate smooth trajectory
    smooth_coords = interpolate_points(coords, max_step_meters=20.0) if len(coords) >= 2 else coords

    mode = (seg['activity_type'] or "TRAVEL").replace("_", " ").title()
    dist_m = seg['distance_meters'] or (haversine_distance(coords[0][0], coords[0][1], coords[-1][0], coords[-1][1]) if len(coords) >= 2 else 0.0)
    dur_s = max(1.0, seg['end_ts'] - seg['start_ts'])
    avg_speed_kmh = round((dist_m / dur_s) * 3.6, 1)

    orig_name = seg['prev_place'] or "Origin"
    dest_name = next_v['place_name'] if next_v else "Destination"

    # Build trajectory objects with bearings
    trajectory = []
    total_steps = len(smooth_coords)
    step_time_inc = dur_s / max(1, total_steps - 1)

    for i, pt in enumerate(smooth_coords):
        lat, lng = pt[0], pt[1]
        if i < total_steps - 1:
            next_pt = smooth_coords[i+1]
            bearing = calculate_bearing(lat, lng, next_pt[0], next_pt[1])
        elif i > 0:
            prev_pt = smooth_coords[i-1]
            bearing = calculate_bearing(prev_pt[0], prev_pt[1], lat, lng)
        else:
            bearing = 0.0

        cur_ts = seg['start_ts'] + (i * step_time_inc)
        cur_dt = datetime.datetime.fromtimestamp(cur_ts, tz=datetime.timezone.utc)
        cur_iso = cur_dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        trajectory.append({
            "lat": lat,
            "lng": lng,
            "bearing": bearing,
            "timestamp": cur_ts,
            "time_iso": cur_iso,
            "speed_kmh": avg_speed_kmh
        })

    # Start & End Hotspots
    hotspots = []
    if smooth_coords:
        hotspots.append({
            "title": orig_name,
            "lat": smooth_coords[0][0],
            "lng": smooth_coords[0][1],
            "type": "ORIGIN",
            "time": seg['start_time'][11:16] if seg['start_time'] else ""
        })
        hotspots.append({
            "title": dest_name,
            "lat": smooth_coords[-1][0],
            "lng": smooth_coords[-1][1],
            "type": "DESTINATION",
            "time": seg['end_time'][11:16] if seg['end_time'] else ""
        })

    st_iso = seg['start_time']
    et_iso = seg['end_time']
    desc = f"{mode} from {st_iso} to {et_iso}. Distance {int(dist_m)}m"

    conn.close()
    return {
        "status": "SUCCESS",
        "segment_id": segment_id,
        "title": mode,
        "mode": mode,
        "date": seg['date'],
        "start_time": st_iso,
        "end_time": et_iso,
        "distance_meters": round(dist_m, 1),
        "avg_speed_kmh": avg_speed_kmh,
        "origin_name": orig_name,
        "dest_name": dest_name,
        "description": desc,
        "trajectory": trajectory,
        "raw_coords": smooth_coords,
        "hotspots": hotspots
    }


def get_segment_kml(segment_id: int, db_path: str = "timeline_viewer.db") -> str:
    """Generates a downloadable Google Earth 3D Tour KML for a segment."""
    data = get_segment_tour_data(segment_id, db_path)
    if data.get("status") != "SUCCESS":
        return "<kml><Document><name>Error</name></Document></kml>"

    return generate_earth_tour_kml(
        title=f"{data['mode']} Tour - {data['date']}",
        description=data['description'],
        points=data['raw_coords'],
        mode=data['mode'],
        origin_name=data['origin_name'],
        dest_name=data['dest_name']
    )
