import sqlite3, json, math, datetime

DB_PATH = 'timeline_viewer.db'

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2.0)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2.0)**2
    return 2.0 * R * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

def clean_and_stitch():
    print("[*] CLEANING AND STITCHING TIMELINE ACTIVITIES...")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Step 1: Purge sub-30s micro-events that are activities
    c.execute("""
    SELECT id, start_time, end_time, activity_type, duration_minutes, start_ts, end_ts
    FROM segments
    WHERE segment_type = 'activity' AND (duration_minutes < 0.5 OR (end_ts - start_ts) < 30);
    """)
    micro_rows = c.fetchall()
    print(f"  [1] Found {len(micro_rows)} micro-activities (<30s) to purge.")
    micro_ids = [r[0] for r in micro_rows]
    if micro_ids:
        c.executemany("DELETE FROM segments WHERE id = ?", [(i,) for i in micro_ids])
        conn.commit()

    # Step 2: Merge consecutive same-mode activities
    c.execute("""
    SELECT id, segment_type, start_time, end_time, start_ts, end_ts, duration_minutes,
           activity_type, distance_meters, path_points_json, latitude, longitude, end_lat, end_lng
    FROM segments
    ORDER BY start_ts ASC;
    """)
    rows = c.fetchall()

    merged_count = 0
    i = 0
    to_delete = []
    updates = []

    while i < len(rows) - 1:
        r1 = rows[i]
        r2 = rows[i+1]

        # Check if both are activities of the same mode and contiguous (gap <= 300s)
        if r1[1] == 'activity' and r2[1] == 'activity' and r1[7] == r2[7] and (r2[4] - r1[5]) <= 300:
            # Merge r2 into r1
            merged_id = r1[0]
            new_end_time = r2[3]
            new_end_ts = r2[5]
            new_dur = (new_end_ts - r1[4]) / 60.0
            new_dist = (r1[8] or 0.0) + (r2[8] or 0.0)
            
            pts1 = json.loads(r1[9]) if r1[9] else []
            pts2 = json.loads(r2[9]) if r2[9] else []
            combined_pts = pts1 + pts2
            # Deduplicate consecutive identical points
            dedup_pts = []
            for pt in combined_pts:
                if not dedup_pts or pt != dedup_pts[-1]:
                    dedup_pts.append(pt)

            new_elat = r2[12] or (dedup_pts[-1][0] if dedup_pts else r1[10])
            new_elng = r2[13] or (dedup_pts[-1][1] if dedup_pts else r1[11])

            updates.append((new_end_time, new_end_ts, new_dur, new_dist, json.dumps(dedup_pts), new_elat, new_elng, merged_id))
            to_delete.append(r2[0])
            merged_count += 1
            
            # Update r1 in list for potential chaining with r3
            r1_updated = list(r1)
            r1_updated[3] = new_end_time
            r1_updated[5] = new_end_ts
            r1_updated[6] = new_dur
            r1_updated[8] = new_dist
            r1_updated[9] = json.dumps(dedup_pts)
            r1_updated[12] = new_elat
            r1_updated[13] = new_elng
            rows[i+1] = tuple(r1_updated)
        i += 1

    for u in updates:
        c.execute("""
        UPDATE segments
        SET end_time = ?, end_ts = ?, duration_minutes = ?, distance_meters = ?, path_points_json = ?, end_lat = ?, end_lng = ?
        WHERE id = ?;
        """, u)

    for d in to_delete:
        c.execute("DELETE FROM segments WHERE id = ?;", (d,))

    conn.commit()
    print(f"  [2] Stitched {merged_count} consecutive activity segments.")

    conn.close()
    print("[✓] Cleaning and stitching completed!")

if __name__ == '__main__':
    clean_and_stitch()
