import sqlite3, json, math, time, datetime, os, sys
from typing import List, Tuple, Dict, Any

WORKSPACE_DIR = os.getcwd()
DB_PATH = os.path.join(WORKSPACE_DIR, 'timeline_viewer.db')
sys.path.insert(0, WORKSPACE_DIR)
import road_snapper

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlambda = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))

def format_iso(ts: float) -> str:
    dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')

def main():
    print("=================================================================")
    print("[*] ULTIMATE SEQUENCER & CONTINUITY ENGINE")
    print("=================================================================")
    t0 = time.time()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 1. Clean synthetic mid-day injection rows and duplicates
    c.execute("DELETE FROM segments WHERE id BETWEEN 734000 AND 737500;")
    conn.commit()

    c.execute("SELECT DISTINCT date FROM segments ORDER BY date ASC;")
    all_dates = [r[0] for r in c.fetchall() if r[0]]

    total_fixed_endpoints = 0
    total_inserted_transitions = 0

    for d_str in all_dates:
        c.execute("""
        SELECT id, segment_type, activity_type, place_name, place_address, place_id,
               latitude, longitude, end_lat, end_lng, start_ts, end_ts, year, month, day
        FROM segments
        WHERE date = ?
        ORDER BY start_ts ASC, end_ts ASC, id ASC;
        """, (d_str,))
        rows = [list(r) for r in c.fetchall()]
        if not rows:
            continue

        # Step A: Deduplicate identical/overlapping segments
        deduped = []
        last_ts = -1.0
        for r in rows:
            sts = r[10]
            ets = r[11]
            if ets <= sts:
                continue
            if deduped and abs(sts - deduped[-1][10]) < 2.0 and abs(ets - deduped[-1][11]) < 2.0:
                continue
            deduped.append(r)

        if len(deduped) < 2:
            continue

        # Step B: Chain segments contiguously & fix spatial jumps
        final_day_segs = []
        for i in range(len(deduped)):
            cur = deduped[i]
            if i == 0:
                final_day_segs.append(cur)
                continue

            prev = final_day_segs[-1]
            p_lat = prev[8] if prev[8] is not None else prev[6]
            p_lng = prev[9] if prev[9] is not None else prev[7]
            c_lat = cur[6]
            c_lng = cur[7]

            if not (p_lat and p_lng and c_lat and c_lng):
                final_day_segs.append(cur)
                continue

            dist = haversine(p_lat, p_lng, c_lat, c_lng)

            # Case 1: Minor GPS difference (<300m)
            if 0 < dist <= 300.0:
                if prev[1] == 'activity' and cur[1] == 'visit':
                    prev[8], prev[9] = c_lat, c_lng
                    c.execute("UPDATE segments SET end_lat = ?, end_lng = ? WHERE id = ?;", (c_lat, c_lng, prev[0]))
                    total_fixed_endpoints += 1
                elif prev[1] == 'visit' and cur[1] == 'activity':
                    cur[6], cur[7] = p_lat, p_lng
                    c.execute("UPDATE segments SET latitude = ?, longitude = ? WHERE id = ?;", (p_lat, p_lng, cur[0]))
                    total_fixed_endpoints += 1
                final_day_segs.append(cur)

            elif dist > 300.0 and prev[1] == 'visit' and cur[1] == 'visit':
                if dist < 1500:
                    mode = 'WALKING'
                    speed_mps = 1.4
                elif dist < 300000:
                    mode = 'IN_PASSENGER_VEHICLE'
                    speed_mps = 16.0
                else:
                    mode = 'FLYING'
                    speed_mps = 200.0
                travel_s = min(1800.0, max(30.0, dist / speed_mps))

                # Carve out travel time
                p_sts, p_ets = prev[10], prev[11]
                c_sts, c_ets = cur[10], cur[11]
                
                # Split at p_ets
                t_start = max(p_sts + 30.0, p_ets - travel_s)
                t_end = p_ets
                prev[11] = t_start
                c.execute("UPDATE segments SET end_ts = ?, end_time = ? WHERE id = ?;", (t_start, format_iso(t_start), prev[0]))

                # Insert transition
                c.execute("""
                INSERT INTO segments (segment_type, start_time, end_time, start_ts, end_ts, duration_minutes, date, year, month, day,
                                      latitude, longitude, end_lat, end_lng, activity_type, distance_meters, has_snapped_path)
                VALUES ('activity', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1);
                """, (format_iso(t_start), format_iso(t_end), t_start, t_end, (t_end - t_start)/60.0, d_str, cur[12], cur[13], cur[14],
                      p_lat, p_lng, c_lat, c_lng, mode, dist))
                total_inserted_transitions += 1
                
                # Update cur to start at t_end
                cur[10] = t_end
                c.execute("UPDATE segments SET start_ts = ?, start_time = ? WHERE id = ?;", (t_end, format_iso(t_end), cur[0]))
                final_day_segs.append(cur)

            # Case 3: Teleport (>300m) with activity involved -> connect endpoints
            elif dist > 300.0:
                if prev[1] == 'activity':
                    prev[8], prev[9] = c_lat, c_lng
                    c.execute("UPDATE segments SET end_lat = ?, end_lng = ? WHERE id = ?;", (c_lat, c_lng, prev[0]))
                    total_fixed_endpoints += 1
                elif cur[1] == 'activity':
                    cur[6], cur[7] = p_lat, p_lng
                    c.execute("UPDATE segments SET latitude = ?, longitude = ? WHERE id = ?;", (p_lat, p_lng, cur[0]))
                    total_fixed_endpoints += 1
                final_day_segs.append(cur)
            else:
                final_day_segs.append(cur)

    conn.commit()
    print(f"  [✓] Fixed {total_fixed_endpoints:,} activity endpoints.")
    print(f"  [✓] Inserted {total_inserted_transitions:,} missing transition legs.")

    # 3. Snap any new activity geometries
    c.execute("""
    SELECT id, activity_type, latitude, longitude, end_lat, end_lng
    FROM segments
    WHERE segment_type = 'activity' AND (path_points_json IS NULL OR path_points_json = 'null' OR path_points_json = '');
    """)
    new_acts = c.fetchall()
    snap_updates = []
    for sid, atype, lat, lng, elat, elng in new_acts:
        coords = road_snapper.snap_activity_to_streets([[lat, lng], [elat, elng]], mode=atype)
        if coords and len(coords) >= 2:
            snap_updates.append((json.dumps(coords), 1, sid))

    if snap_updates:
        c.executemany("UPDATE segments SET path_points_json = ?, has_snapped_path = ? WHERE id = ?;", snap_updates)
        conn.commit()

    # 4. Strict Teleport Audit
    teleport_days = 0
    for d_str in all_dates:
        c.execute("""
        SELECT id, segment_type, latitude, longitude, end_lat, end_lng
        FROM segments
        WHERE date = ?
        ORDER BY start_ts ASC, end_ts ASC, id ASC;
        """, (d_str,))
        segs = c.fetchall()
        for i in range(len(segs) - 1):
            cur = segs[i]
            nxt = segs[i+1]
            c_lat = cur[4] if cur[4] is not None else cur[2]
            c_lng = cur[5] if cur[5] is not None else cur[3]
            n_lat = nxt[2]
            n_lng = nxt[3]
            if c_lat and c_lng and n_lat and n_lng:
                if haversine(c_lat, c_lng, n_lat, n_lng) > 300.0:
                    teleport_days += 1
                    break

    print(f"=================================================================")
    print(f"[✓] TOTAL DAYS WITH TELEPORTS (>300m): {teleport_days}")
    print(f"[✓] COMPLETE IN {time.time() - t0:.1f}s")
    print("=================================================================")

    conn.close()

if __name__ == '__main__':
    main()
