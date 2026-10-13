"""
Trajectory Boundary & Teleportation Sanitizer.
Audits all movement segments against their immediate boundary visits.
Fixes raw Google Takeout coordinate corruption where an activity segment erroneously
inherits GPS coordinates from a previous journey hours earlier.
"""

import sqlite3
import json
from breadcrumbs import haversine_distance

DEFAULT_DB_PATH = "timeline_viewer.db"


def sanitize_all_trajectories(db_path: str = DEFAULT_DB_PATH):
    print("=" * 70)
    print("🧹 Running Trajectory Boundary Sanitizer...")
    print("=" * 70)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
    SELECT s.id, s.date, s.segment_type, s.activity_type, s.start_time, s.end_time,
           s.duration_minutes, s.distance_meters, s.clean_distance_meters,
           s.latitude, s.longitude, s.end_lat, s.end_lng, s.start_ts, s.end_ts
    FROM segments s
    ORDER BY s.start_ts ASC;
    """)
    segments = [dict(r) for r in c.fetchall()]
    total = len(segments)

    fixed_count = 0

    for i, s in enumerate(segments):
        if s['segment_type'] != 'activity':
            continue

        act_type = (s.get('activity_type') or '').upper()
        if act_type in ('FLYING',):
            continue

        dur_min = s.get('duration_minutes') or 0.0
        if dur_min <= 0:
            continue

        cur_dist = s.get('clean_distance_meters') or s.get('distance_meters') or 0.0
        cur_speed_kmh = (cur_dist / 1000.0) / (dur_min / 60.0)

        # Preceding visit
        prev_visit = None
        if i > 0 and segments[i-1]['segment_type'] == 'visit':
            prev_visit = segments[i-1]

        # Succeeding visit
        next_visit = None
        if i < total - 1 and segments[i+1]['segment_type'] == 'visit':
            next_visit = segments[i+1]

        # Check for start/end coordinate jumps
        needs_fix = False
        new_start_lat = s['latitude']
        new_start_lng = s['longitude']
        new_end_lat = s['end_lat']
        new_end_lng = s['end_lng']

        if prev_visit and prev_visit.get('latitude') is not None:
            p_lat = prev_visit['latitude']
            p_lng = prev_visit['longitude']
            if s['latitude'] is not None:
                d_prev = haversine_distance(p_lat, p_lng, s['latitude'], s['longitude'])
                if d_prev > 3000 and cur_speed_kmh > (45.0 if act_type == 'CYCLING' else 15.0 if act_type == 'WALKING' else 130.0):
                    new_start_lat = p_lat
                    new_start_lng = p_lng
                    needs_fix = True

        if next_visit and next_visit.get('latitude') is not None:
            n_lat = next_visit['latitude']
            n_lng = next_visit['longitude']
            if s['end_lat'] is not None:
                d_next = haversine_distance(n_lat, n_lng, s['end_lat'], s['end_lng'])
                if d_next > 3000 and cur_speed_kmh > (45.0 if act_type == 'CYCLING' else 15.0 if act_type == 'WALKING' else 130.0):
                    new_end_lat = n_lat
                    new_end_lng = n_lng
                    needs_fix = True

        if needs_fix and new_start_lat and new_end_lat:
            true_dist = haversine_distance(new_start_lat, new_start_lng, new_end_lat, new_end_lng)
            path_pts = [[new_start_lat, new_start_lng], [new_end_lat, new_end_lng]]
            c.execute("""
            UPDATE segments
            SET latitude = ?, longitude = ?, end_lat = ?, end_lng = ?,
                distance_meters = ?, clean_distance_meters = ?,
                path_points_json = ?, has_snapped_path = 0
            WHERE id = ?;
            """, (new_start_lat, new_start_lng, new_end_lat, new_end_lng, true_dist, true_dist, json.dumps(path_pts), s['id']))
            fixed_count += 1

    conn.commit()
    conn.close()
    print(f"[✓] Sanitized {fixed_count} corrupted movement segments with teleporting coordinates.")
    return fixed_count


if __name__ == "__main__":
    sanitize_all_trajectories()
