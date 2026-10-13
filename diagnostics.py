"""
Timeline Health, Anomaly Detection, and Quality Diagnostics Engine.
Audits timeline gaps, sensor correlations, top-level visit collisions, and speed outliers.
"""

import json
import time
import math
import bisect
import sqlite3
from typing import Dict, Any, List, Optional, Tuple

from db import get_db_connection, DEFAULT_DB_PATH
from importer import haversine_km

try:
    from enrichment.flight_airport_auditor import audit_flight_airports, fix_all_flight_distances
    from enrichment.fit_corroborator import generate_fit_gap_proposals
except ImportError:
    from flight_airport_auditor import audit_flight_airports, fix_all_flight_distances
    from fit_corroborator import generate_fit_gap_proposals


class TimelineDiagnosticsEngine:
    """Audits timeline data integrity, computes gaps, and flags anomalies."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self.conn = get_db_connection(self.db_path)

    def run_full_diagnostics(self) -> Dict[str, Any]:
        """Runs the entire diagnostic pipeline and populates gaps and anomaly tables."""
        t0 = time.time()
        print("[*] Running Timeline Health Diagnostics...")

        # 1. Detect and index all timeline gaps
        gaps_stats = self._detect_gaps()

        # 2. Detect top-level visit collisions in O(N)
        overlap_stats = self._detect_top_level_overlaps()

        # 3. Detect movement speed and teleportation outliers
        speed_stats = self._detect_speed_anomalies()

        # 4. Generate concrete fix proposals for all timeline gaps
        proposal_stats = self._generate_gap_proposals()

        # 5. Audit unconfirmed lat/lng visits and generate resolution proposals
        unconf_stats = self.audit_unconfirmed_visits()

        # 6. Audit flight airport endpoints and generate airport insertion proposals
        flight_stats = self.audit_flight_airports_proposals()

        # 7. Audit Google Fit recorded sessions to fill timeline gaps
        fit_stats = self.audit_fit_proposals()

        # 8. Generate health scorecard
        scorecard = self.get_health_scorecard()

        elapsed = time.time() - t0
        print(f"[✓] Diagnostics completed in {elapsed:.2f}s.")
        return {
            "gaps": gaps_stats,
            "overlaps": overlap_stats,
            "speed_anomalies": speed_stats,
            "proposals": proposal_stats,
            "flight_proposals": flight_stats,
            "fit_proposals": fit_stats,
            "scorecard": scorecard,
            "elapsed_sec": elapsed
        }

    def _detect_gaps(self) -> Dict[str, Any]:
        """Computes all missing intervals (>15m) between consecutive top-level segments."""
        print("    Auditing timeline continuity and gaps...")
        c = self.conn.cursor()
        c.execute("DELETE FROM gaps;")
        self.conn.commit()

        # Pre-load sorted raw signal and breadcrumb timestamps for O(log N) bisect queries
        c.execute("""
        SELECT ts FROM raw_signals
        UNION ALL
        SELECT timestamp as ts FROM breadcrumbs
        ORDER BY ts ASC;
        """)
        raw_ts_list = [r['ts'] for r in c.fetchall()]

        # Fetch all top-level timeline segments sorted chronologically
        c.execute("""
        SELECT id, start_time, end_time, start_ts, end_ts, date, year,
               latitude, longitude, end_lat, end_lng, segment_type
        FROM segments
        WHERE hierarchy_level = 0
        ORDER BY start_ts ASC, end_ts ASC;
        """)
        segments = c.fetchall()

        gap_rows = []
        post_2010_count = 0
        pre_2010_count = 0
        gaps_with_signals = 0

        for i in range(len(segments) - 1):
            curr = segments[i]
            nxt = segments[i + 1]

            curr_et = curr['end_ts']
            nxt_st = nxt['start_ts']
            diff_sec = nxt_st - curr_et

            if diff_sec >= 60:  # Index all gaps >= 1 minute (including micro-transitions)
                dur_hours = diff_sec / 3600.0
                g_date = curr['end_time'][:10] if (curr['end_time'] and len(curr['end_time']) >= 10) else curr['date']
                g_year = int(g_date[:4]) if g_date else curr['year']
                is_hist = 1 if g_year < 2010 else 0
                if is_hist:
                    pre_2010_count += 1
                else:
                    post_2010_count += 1

                # Previous endpoint
                p_lat = curr['end_lat'] if curr['end_lat'] is not None else curr['latitude']
                p_lng = curr['end_lng'] if curr['end_lng'] is not None else curr['longitude']
                # Next startpoint
                n_lat = nxt['latitude']
                n_lng = nxt['longitude']

                dist_km = None
                if p_lat is not None and p_lng is not None and n_lat is not None and n_lng is not None:
                    dist_km = haversine_km(p_lat, p_lng, n_lat, n_lng)

                # Check if raw signals exist during the gap via bisect (< 1 microsecond)
                raw_cnt = 0
                if raw_ts_list:
                    l_idx = bisect.bisect_left(raw_ts_list, curr_et)
                    r_idx = bisect.bisect_right(raw_ts_list, nxt_st)
                    raw_cnt = max(0, r_idx - l_idx)

                if raw_cnt > 0:
                    gaps_with_signals += 1

                gap_rows.append((
                    curr['end_time'], nxt['start_time'], curr_et, nxt_st,
                    dur_hours, g_date, g_year,
                    curr['id'], nxt['id'],
                    p_lat, p_lng, n_lat, n_lng, dist_km,
                    raw_cnt, is_hist, 'OPEN'
                ))

        # Batch insert gaps
        self.conn.executemany("""
        INSERT INTO gaps (
            start_time, end_time, start_ts, end_ts, duration_hours, date, year,
            prev_segment_id, next_segment_id, prev_lat, prev_lng, next_lat, next_lng,
            jump_distance_km, raw_signals_count, is_historical, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, gap_rows)
        self.conn.commit()

        print(f"    [+] Indexed {len(gap_rows)} gaps ({post_2010_count} post-2010, {pre_2010_count} pre-2010, {gaps_with_signals} with raw signals).")
        return {
            "total_gaps": len(gap_rows),
            "post_2010_gaps": post_2010_count,
            "pre_2010_gaps": pre_2010_count,
            "gaps_with_raw_signals": gaps_with_signals
        }

    def _detect_top_level_overlaps(self) -> Dict[str, Any]:
        """Detects collisions between top-level visits in O(N) using sorted interval sweep."""
        print("    Checking for top-level visit collisions...")
        c = self.conn.cursor()
        c.execute("DELETE FROM anomalies WHERE anomaly_type = 'TOP_LEVEL_OVERLAP';")

        c.execute("""
        SELECT id, date, start_time, end_time, start_ts, end_ts, place_name
        FROM segments
        WHERE hierarchy_level = 0 AND segment_type = 'visit'
        ORDER BY start_ts ASC, end_ts ASC;
        """)
        visits = c.fetchall()

        anomaly_rows = []
        n_visits = len(visits)
        for i in range(n_visits):
            v1 = visits[i]
            v1_et = v1['end_ts']
            for j in range(i + 1, min(i + 100, n_visits)):
                v2 = visits[j]
                if v2['start_ts'] >= v1_et:
                    break
                # Overlap detected!
                desc = f"Top-level visit collision between '{v1['place_name'] or 'Unknown'}' ({v1['start_time'][11:16]}-{v1['end_time'][11:16]}) and '{v2['place_name'] or 'Unknown'}' ({v2['start_time'][11:16]}-{v2['end_time'][11:16]})"
                data = json.dumps({
                    "segment_a_id": v1['id'],
                    "segment_b_id": v2['id'],
                    "time_a": [v1['start_time'], v1['end_time']],
                    "time_b": [v2['start_time'], v2['end_time']]
                })
                anomaly_rows.append(('TOP_LEVEL_OVERLAP', v1['id'], v1['date'], desc, 'WARNING', data, 0))

        if anomaly_rows:
            self.conn.executemany("""
            INSERT INTO anomalies (anomaly_type, segment_id, date, description, severity, data_json, is_resolved)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """, anomaly_rows)
            self.conn.commit()

        print(f"    [+] Found {len(anomaly_rows)} top-level visit collisions.")
        return {"top_level_overlaps": len(anomaly_rows)}

    def _detect_speed_anomalies(self) -> Dict[str, Any]:
        """Detects impossible movement speeds (e.g. supersonic walking or driving)."""
        print("    Auditing movement velocities and teleportation jumps...")
        c = self.conn.cursor()
        c.execute("DELETE FROM anomalies WHERE anomaly_type IN ('SPEED_OUTLIER', 'TELEPORTATION');")

        c.execute("""
        SELECT id, date, start_time, end_time, activity_type, distance_meters, duration_minutes
        FROM segments
        WHERE segment_type = 'activity' AND distance_meters > 0 AND duration_minutes > 0;
        """)
        activities = c.fetchall()

        anomaly_rows = []
        for act in activities:
            dist_km = act['distance_meters'] / 1000.0
            dur_hr = act['duration_minutes'] / 60.0
            speed_kmh = dist_km / dur_hr if dur_hr > 0 else 0
            act_type = (act['activity_type'] or "UNKNOWN").upper()

            is_outlier = False
            threshold = 0
            if act_type in ('WALKING', 'ON_FOOT') and speed_kmh > 20:
                is_outlier = True
                threshold = 20
            elif act_type == 'RUNNING' and speed_kmh > 35:
                is_outlier = True
                threshold = 35
            elif act_type == 'CYCLING' and speed_kmh > 80:
                is_outlier = True
                threshold = 80
            elif act_type in ('DRIVING', 'IN_PASSENGER_VEHICLE', 'IN_BUS', 'IN_TAXI') and speed_kmh > 240:
                is_outlier = True
                threshold = 240
            elif act_type == 'FLYING' and speed_kmh > 1400:
                is_outlier = True
                threshold = 1400

            if is_outlier:
                desc = f"Implausible speed for {act_type}: {speed_kmh:.1f} km/h (threshold: {threshold} km/h, distance: {dist_km:.1f} km in {act['duration_minutes']:.1f} min)"
                data = json.dumps({
                    "speed_kmh": round(speed_kmh, 1),
                    "distance_km": round(dist_km, 2),
                    "duration_min": round(act['duration_minutes'], 1),
                    "activity_type": act_type
                })
                anomaly_rows.append(('SPEED_OUTLIER', act['id'], act['date'], desc, 'WARNING', data, 0))

        if anomaly_rows:
            self.conn.executemany("""
            INSERT INTO anomalies (anomaly_type, segment_id, date, description, severity, data_json, is_resolved)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """, anomaly_rows)
            self.conn.commit()

        print(f"    [+] Flagged {len(anomaly_rows)} speed anomalies.")
        return {"speed_anomalies": len(anomaly_rows)}

    def _generate_gap_proposals(self) -> Dict[str, Any]:
        """Analyzes all timeline gaps and populates deterministic, actionable fix proposals."""
        print("    Generating actionable resolution proposals for all gaps...")
        c = self.conn.cursor()
        c.execute("DELETE FROM fix_proposals;")
        self.conn.commit()

        c.execute("""
        SELECT g.id, g.start_ts, g.end_ts, g.start_time, g.end_time, g.prev_lat, g.prev_lng,
               g.next_lat, g.next_lng, g.duration_hours, g.date,
               s1.segment_type as prev_type, s1.place_name as prev_name, s1.activity_type as prev_act,
               s2.segment_type as next_type, s2.place_name as next_name, s2.activity_type as next_act
        FROM gaps g
        LEFT JOIN segments s1 ON g.prev_segment_id = s1.id
        LEFT JOIN segments s2 ON g.next_segment_id = s2.id
        WHERE (g.status IS NULL OR g.status != 'RESOLVED')
        ORDER BY g.start_ts DESC;
        """)
        gaps = c.fetchall()

        # Delete stale pending gap proposals to prevent outdated duplicates
        self.conn.execute("DELETE FROM fix_proposals WHERE target_type = 'gap' AND status = 'PENDING';")
        self.conn.commit()

        fix_rows = []
        for g in gaps:
            gid = g['id']
            st_ts = g['start_ts']
            et_ts = g['end_ts']

            # If segment already exists covering this gap, mark resolved and skip
            c.execute("SELECT COUNT(*) FROM segments WHERE start_ts >= ? AND end_ts <= ?;", (st_ts - 60, et_ts + 60))
            if c.fetchone()[0] > 0:
                self.conn.execute("UPDATE gaps SET status = 'RESOLVED' WHERE id = ?;", (gid,))
                continue

            dur_h = g['duration_hours']
            dur_m = dur_h * 60.0
            gdate = g['date']
            p_lat, p_lng = g['prev_lat'], g['prev_lng']
            n_lat, n_lng = g['next_lat'], g['next_lng']

            prev_type = g['prev_type']
            next_type = g['next_type']
            p_name = g['prev_name'] or 'Previous Location'
            n_name = g['next_name'] or 'Next Location'
            p_act_str = (g['prev_act'] or 'transit').replace('_', ' ').lower()
            n_act_str = (g['next_act'] or 'transit').replace('_', ' ').lower()

            dur_str = f"{dur_h:.1f}h" if dur_h >= 1.0 else f"{dur_m:.0f}m"

            # Format local time strings (HH:MM)
            st_str = g['start_time'][11:16] if g['start_time'] and len(g['start_time']) >= 16 else '--:--'
            et_str = g['end_time'][11:16] if g['end_time'] and len(g['end_time']) >= 16 else '--:--'
            time_window = f"{st_str} – {et_str}"

            # Check breadcrumbs
            c.execute("SELECT COUNT(*), AVG(lat), AVG(lng) FROM breadcrumbs WHERE timestamp >= ? AND timestamp <= ?;", (int(st_ts), int(et_ts)))
            bc_row = c.fetchone()
            bc_count = bc_row[0] if bc_row else 0
            avg_lat = bc_row[1] if bc_row else None
            avg_lng = bc_row[2] if bc_row else None

            dist_km = haversine_km(p_lat, p_lng, n_lat, n_lng) if (p_lat and n_lat) else 0.0
            speed_kmh = dist_km / dur_h if dur_h > 0 else 0

            # 1. Reconstruct stationary visit if breadcrumb cluster exists (< 1.0 km displacement)
            if bc_count and bc_count >= 3 and dist_km < 1.0:
                c.execute("""
                SELECT name, address, latitude, longitude
                FROM places
                WHERE latitude IS NOT NULL
                ORDER BY ((latitude - ?) * (latitude - ?) + (longitude - ?) * (longitude - ?)) ASC
                LIMIT 1;
                """, (avg_lat, avg_lat, avg_lng, avg_lng))
                poi_match = c.fetchone()
                poi_name = poi_match['name'] if poi_match and poi_match['name'] else 'Stationary Location'

                action = 'RECONSTRUCT_FROM_BREADCRUMBS'
                reasoning = f'Recover visit at {poi_name} ({time_window}, {dur_m:.0f}m) from {bc_count} raw GPS fixes.'
                payload = json.dumps({
                    'action': action, 'gap_id': gid, 'date': gdate,
                    'start_ts': st_ts, 'end_ts': et_ts, 'breadcrumb_count': bc_count,
                    'resolved_poi_name': poi_name, 'centroid_lat': avg_lat, 'centroid_lng': avg_lng,
                    'duration_minutes': dur_m, 'time_window': time_window
                })
                fix_rows.append(('gap', gid, gdate, action, 'raw_breadcrumbs', reasoning, 0.95, 'PENDING', payload, '2026-08-20T18:55:00Z'))

            # 2. Both surrounding segments are movement activities (e.g. IN_BUS -> Gap -> IN_BUS, or SUBWAY -> Gap -> TRAIN)
            elif prev_type == 'activity' and next_type == 'activity':
                if dur_m <= 45 and dist_km < 1.0:
                    if dist_km >= 0.08:
                        action = 'SYNTHESIZE_TRANSIT_LEG'
                        mode = 'WALKING'
                        reasoning = f'Synthesize WALKING transfer between {p_act_str} and {n_act_str} ({dist_km:.1f} km, {dur_m:.0f}m, {time_window}).'
                        payload = json.dumps({
                            'action': action, 'gap_id': gid, 'date': gdate,
                            'start_ts': st_ts, 'end_ts': et_ts, 'mode': mode,
                            'distance_km': dist_km, 'speed_kmh': speed_kmh,
                            'start_lat': p_lat, 'start_lng': p_lng, 'end_lat': n_lat, 'end_lng': n_lng,
                            'time_window': time_window
                        })
                        fix_rows.append(('gap', gid, gdate, action, 'transit_synthesis', reasoning, 0.90, 'PENDING', payload, '2026-08-20T18:55:00Z'))
                    else:
                        action = 'EXTEND_STATIONARY_DWELL'
                        dwell_name = f"Transit Transfer / Stop Wait"
                        reasoning = f'Transit transfer wait between {p_act_str} and {n_act_str} ({dur_m:.0f}m, {time_window}).'
                        payload = json.dumps({
                            'action': action, 'gap_id': gid, 'date': gdate,
                            'start_ts': st_ts, 'end_ts': et_ts, 'target_place': dwell_name,
                            'duration_minutes': dur_m, 'time_window': time_window
                        })
                        fix_rows.append(('gap', gid, gdate, action, 'stationary_continuity', reasoning, 0.90, 'PENDING', payload, '2026-08-20T18:55:00Z'))
                elif dur_h >= 4.0 or (dur_h >= 2.5 and speed_kmh < 15.0):
                    action = 'DOCUMENTED_HIATUS'
                    reasoning = f'Documented untracked hiatus / transit gap ({dur_h:.1f}h, {time_window}) between {p_act_str} and {n_act_str}.'
                    payload = json.dumps({
                        'action': action, 'gap_id': gid, 'date': gdate,
                        'duration_hours': dur_h, 'time_window': time_window
                    })
                    fix_rows.append(('gap', gid, gdate, action, 'hiatus_indexer', reasoning, 0.75, 'PENDING', payload, '2026-08-20T18:55:00Z'))
                else:
                    mode = g['prev_act'] or g['next_act'] or 'DRIVING'
                    if mode == 'IN_PASSENGER_VEHICLE': mode = 'DRIVING'
                    action = 'SYNTHESIZE_TRANSIT_LEG'
                    reasoning = f'Synthesize {mode} travel leg ({dist_km:.1f} km, {dur_m:.0f}m, {time_window}).'
                    payload = json.dumps({
                        'action': action, 'gap_id': gid, 'date': gdate,
                        'start_ts': st_ts, 'end_ts': et_ts, 'mode': mode,
                        'distance_km': dist_km, 'speed_kmh': speed_kmh,
                        'start_lat': p_lat, 'start_lng': p_lng, 'end_lat': n_lat, 'end_lng': n_lng,
                        'time_window': time_window
                    })
                    fix_rows.append(('gap', gid, gdate, action, 'transit_synthesis', reasoning, 0.85, 'PENDING', payload, '2026-08-20T18:55:00Z'))

            # 3. Preceding is a verified visit, succeeding is an activity/departure
            elif prev_type == 'visit' and (next_type == 'activity' or next_type is None):
                if dist_km < 0.6 or speed_kmh < 3.0:
                    action = 'EXTEND_STATIONARY_DWELL'
                    dwell_name = p_name
                    reasoning = f'Extend stay at {dwell_name} ({dur_str}, {time_window}).'
                    payload = json.dumps({
                        'action': action, 'gap_id': gid, 'date': gdate,
                        'start_ts': st_ts, 'end_ts': et_ts, 'target_place': dwell_name,
                        'duration_minutes': dur_m, 'time_window': time_window
                    })
                    fix_rows.append(('gap', gid, gdate, action, 'stationary_continuity', reasoning, 0.90, 'PENDING', payload, '2026-08-20T18:55:00Z'))
                elif dur_h >= 4.0 or (dur_h >= 2.5 and speed_kmh < 15.0):
                    action = 'DOCUMENTED_HIATUS'
                    reasoning = f'Documented untracked hiatus / gap ({dur_h:.1f}h, {time_window}) departing {p_name}.'
                    payload = json.dumps({
                        'action': action, 'gap_id': gid, 'date': gdate,
                        'duration_hours': dur_h, 'time_window': time_window
                    })
                    fix_rows.append(('gap', gid, gdate, action, 'hiatus_indexer', reasoning, 0.75, 'PENDING', payload, '2026-08-20T18:55:00Z'))
                else:
                    mode = g['next_act'] or ('WALKING' if dist_km < 2.0 else 'DRIVING')
                    if mode == 'IN_PASSENGER_VEHICLE': mode = 'DRIVING'
                    action = 'SYNTHESIZE_TRANSIT_LEG'
                    reasoning = f'Synthesize {mode} travel leg departing {p_name} ({dist_km:.1f} km, {dur_m:.0f}m, {time_window}).'
                    payload = json.dumps({
                        'action': action, 'gap_id': gid, 'date': gdate,
                        'start_ts': st_ts, 'end_ts': et_ts, 'mode': mode,
                        'distance_km': dist_km, 'speed_kmh': speed_kmh,
                        'start_lat': p_lat, 'start_lng': p_lng, 'end_lat': n_lat, 'end_lng': n_lng,
                        'time_window': time_window
                    })
                    fix_rows.append(('gap', gid, gdate, action, 'transit_synthesis', reasoning, 0.85, 'PENDING', payload, '2026-08-20T18:55:00Z'))

            # 4. Preceding is an activity/arrival, succeeding is a verified visit
            elif (prev_type == 'activity' or prev_type is None) and next_type == 'visit':
                if dist_km < 0.6 or speed_kmh < 3.0:
                    action = 'EXTEND_STATIONARY_DWELL'
                    dwell_name = n_name
                    reasoning = f'Extend stay at {dwell_name} ({dur_str}, {time_window}).'
                    payload = json.dumps({
                        'action': action, 'gap_id': gid, 'date': gdate,
                        'start_ts': st_ts, 'end_ts': et_ts, 'target_place': dwell_name,
                        'duration_minutes': dur_m, 'time_window': time_window
                    })
                    fix_rows.append(('gap', gid, gdate, action, 'stationary_continuity', reasoning, 0.90, 'PENDING', payload, '2026-08-20T18:55:00Z'))
                elif dur_h >= 4.0 or (dur_h >= 2.5 and speed_kmh < 15.0):
                    action = 'DOCUMENTED_HIATUS'
                    reasoning = f'Documented untracked hiatus / gap ({dur_h:.1f}h, {time_window}) arriving at {n_name}.'
                    payload = json.dumps({
                        'action': action, 'gap_id': gid, 'date': gdate,
                        'duration_hours': dur_h, 'time_window': time_window
                    })
                    fix_rows.append(('gap', gid, gdate, action, 'hiatus_indexer', reasoning, 0.75, 'PENDING', payload, '2026-08-20T18:55:00Z'))
                else:
                    mode = g['prev_act'] or ('WALKING' if dist_km < 2.0 else 'DRIVING')
                    if mode == 'IN_PASSENGER_VEHICLE': mode = 'DRIVING'
                    action = 'SYNTHESIZE_TRANSIT_LEG'
                    reasoning = f'Synthesize {mode} travel leg arriving at {n_name} ({dist_km:.1f} km, {dur_m:.0f}m, {time_window}).'
                    payload = json.dumps({
                        'action': action, 'gap_id': gid, 'date': gdate,
                        'start_ts': st_ts, 'end_ts': et_ts, 'mode': mode,
                        'distance_km': dist_km, 'speed_kmh': speed_kmh,
                        'start_lat': p_lat, 'start_lng': p_lng, 'end_lat': n_lat, 'end_lng': n_lng,
                        'time_window': time_window
                    })
                    fix_rows.append(('gap', gid, gdate, action, 'transit_synthesis', reasoning, 0.85, 'PENDING', payload, '2026-08-20T18:55:00Z'))

            # 5. Both surrounding segments are visits (visit -> Gap -> visit)
            else:
                if dist_km < 0.35 or (p_name != 'Previous Location' and p_name == n_name):
                    action = 'EXTEND_STATIONARY_DWELL'
                    dwell_name = p_name if p_name != 'Previous Location' else n_name
                    reasoning = f'Extend continuous stay at {dwell_name} ({dur_str}, {time_window}).'
                    payload = json.dumps({
                        'action': action, 'gap_id': gid, 'date': gdate,
                        'start_ts': st_ts, 'end_ts': et_ts, 'target_place': dwell_name,
                        'duration_minutes': dur_m, 'time_window': time_window
                    })
                    fix_rows.append(('gap', gid, gdate, action, 'stationary_continuity', reasoning, 0.90, 'PENDING', payload, '2026-08-20T18:55:00Z'))
                elif dur_h >= 4.0 or (dur_h >= 2.5 and speed_kmh < 15.0):
                    action = 'DOCUMENTED_HIATUS'
                    reasoning = f'Documented untracked hiatus / overnight gap ({dur_h:.1f}h, {time_window}) between {p_name} and {n_name}.'
                    payload = json.dumps({
                        'action': action, 'gap_id': gid, 'date': gdate,
                        'duration_hours': dur_h, 'time_window': time_window
                    })
                    fix_rows.append(('gap', gid, gdate, action, 'hiatus_indexer', reasoning, 0.75, 'PENDING', payload, '2026-08-20T18:55:00Z'))
                else:
                    is_airport = any('airport' in (name.lower()) or 'aéroport' in (name.lower()) or 'aeroporto' in (name.lower()) for name in (p_name, n_name))
                    is_station = any('station' in (name.lower()) or 'bahnhof' in (name.lower()) or 'gare' in (name.lower()) or 'hb' in (name.lower()) for name in (p_name, n_name))

                    if dist_km > 350.0 or speed_kmh > 180.0:
                        mode = 'FLYING'
                    elif dist_km > 30.0 or is_station or (is_airport and dist_km > 10.0):
                        mode = 'IN_TRAIN' if (is_station or (is_airport and dist_km > 10.0)) else 'DRIVING'
                    elif dist_km > 5.0 or speed_kmh > 15.0:
                        mode = 'DRIVING'
                    elif speed_kmh <= 7.0 and dur_h <= 1.5 and dist_km <= 6.0:
                        mode = 'WALKING'
                    elif speed_kmh <= 25.0 and dur_h <= 2.0 and dist_km <= 25.0:
                        mode = 'CYCLING'
                    else:
                        mode = 'DRIVING'

                    action = 'SYNTHESIZE_TRANSIT_LEG'
                    reasoning = f'Synthesize {mode} travel leg from {p_name} to {n_name} ({dist_km:.1f} km, {dur_m:.0f}m, {time_window}).'
                    payload = json.dumps({
                        'action': action, 'gap_id': gid, 'date': gdate,
                        'start_ts': st_ts, 'end_ts': et_ts, 'mode': mode,
                        'distance_km': dist_km, 'speed_kmh': speed_kmh,
                        'start_lat': p_lat, 'start_lng': p_lng, 'end_lat': n_lat, 'end_lng': n_lng,
                        'time_window': time_window
                    })
                    fix_rows.append(('gap', gid, gdate, action, 'transit_synthesis', reasoning, 0.85, 'PENDING', payload, '2026-08-20T18:55:00Z'))

        if fix_rows:
            self.conn.executemany("""
            INSERT INTO fix_proposals (target_type, target_id, date, proposed_action, source, reasoning, confidence, status, patch_data_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, fix_rows)
            self.conn.commit()

        print(f"    [+] Generated {len(fix_rows)} gap resolution proposals.")
        return {"total_proposals": len(fix_rows)}

    def audit_unconfirmed_visits(self) -> Dict[str, Any]:
        """Audits visits with raw lat/lng or unconfirmed locations and creates actionable resolution proposals."""
        c = self.conn.cursor()
        c.execute("""
        SELECT id, date, start_time, end_time, start_ts, end_ts, latitude, longitude, place_name, duration_minutes
        FROM segments
        WHERE segment_type = 'visit' AND (place_name = 'Unconfirmed Location' OR place_name LIKE 'Location (%' OR is_unconfirmed = 1)
        ORDER BY start_ts ASC;
        """)
        unconf_segs = [dict(r) for r in c.fetchall()]
        
        # Pre-fetch confirmed places
        c.execute("SELECT place_id, name, address, category, latitude, longitude FROM places WHERE name NOT LIKE '%Unconfirmed%' AND name NOT LIKE 'Location (%' AND latitude IS NOT NULL;")
        places = [dict(r) for r in c.fetchall()]

        proposals = []
        for s in unconf_segs:
            sid = s['id']
            sdate = s['date']
            st_str = s['start_time'][11:16] if s.get('start_time') and len(s['start_time']) >= 16 else '--:--'
            et_str = s['end_time'][11:16] if s.get('end_time') and len(s['end_time']) >= 16 else '--:--'
            time_window = f"{st_str} – {et_str}"
            slat, slng = s['latitude'], s['longitude']

            best_poi = None
            min_dist = 0.35 # 350 meters
            if slat and slng:
                for p in places:
                    d = haversine_km(slat, slng, p['latitude'], p['longitude'])
                    if d < min_dist:
                        min_dist = d
                        best_poi = p

            prop_name = best_poi['name'] if best_poi else (f"Point of Interest ({slat:.4f}, {slng:.4f})" if slat else "Verified Place")
            prop_cat = best_poi['category'] if best_poi else 'Other / POI'
            dist_desc = f"{min_dist*1000.0:.0f}m from {best_poi['name']}" if best_poi else "coordinate fix"
            reasoning = f"Confirm unverified visit at {prop_name} ({time_window}, {s['duration_minutes']:.0f}m, {dist_desc})."

            payload = json.dumps({
                'action': 'RESOLVE_UNCONFIRMED_VISIT', 'segment_id': sid, 'date': sdate,
                'target_place': prop_name, 'category': prop_cat,
                'latitude': slat, 'longitude': slng, 'time_window': time_window
            })
            proposals.append(('segment', sid, sdate, 'RESOLVE_UNCONFIRMED_VISIT', 'unconfirmed_resolver', reasoning, 0.85, 'PENDING', payload, '2026-08-20T18:55:00Z'))

        if proposals:
            self.conn.executemany("""
            INSERT INTO fix_proposals (target_type, target_id, date, proposed_action, source, reasoning, confidence, status, patch_data_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, proposals)
            self.conn.commit()

        print(f"    [+] Generated {len(proposals)} unconfirmed visit resolution proposals.")
        return {"unconfirmed_visits_flagged": len(proposals)}

    def audit_flight_airports_proposals(self) -> Dict[str, Any]:
        """Audits all flight segments for missing airport visits and generates insertion proposals."""
        print("    Auditing flight airport continuity and trajectory distances...")
        fix_all_flight_distances(self.db_path)
        flight_proposals = audit_flight_airports(self.db_path)

        fix_rows = []
        for fp in flight_proposals:
            fix_rows.append((
                'flight',
                str(fp['flight_id']),
                fp['date'],
                fp['type'],
                'flight_airport_auditor',
                fp['description'],
                0.92,
                'PENDING',
                json.dumps(fp),
                '2026-08-21T15:25:00Z'
            ))

        self.conn.execute("DELETE FROM fix_proposals WHERE source = 'flight_airport_auditor' AND status = 'PENDING';")
        if fix_rows:
            self.conn.executemany("""
            INSERT INTO fix_proposals (target_type, target_id, date, proposed_action, source, reasoning, confidence, status, patch_data_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, fix_rows)
        self.conn.commit()

        print(f"    [+] Generated {len(fix_rows)} flight airport continuity proposals.")
        return {"flight_proposals_generated": len(fix_rows)}

    def audit_fit_proposals(self) -> Dict[str, Any]:
        """Audits timeline gaps against recorded Google Fit sessions and generates proposals."""
        print("    Auditing timeline gaps against Google Fit workout sessions...")
        fit_props = generate_fit_gap_proposals(self.db_path)

        fix_rows = []
        for fp in fit_props:
            fix_rows.append((
                'gap',
                str(fp['gap_id']),
                fp['date'],
                'SYNTHESIZE_FIT_ACTIVITY',
                'google_fit_corroborator',
                fp['description'],
                0.95,
                'PENDING',
                json.dumps(fp),
                '2026-08-21T16:20:00Z'
            ))

        if fix_rows:
            self.conn.executemany("""
            INSERT INTO fix_proposals (target_type, target_id, date, proposed_action, source, reasoning, confidence, status, patch_data_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, fix_rows)
            self.conn.commit()

        print(f"    [+] Generated {len(fix_rows)} Google Fit activity gap-fill proposals.")
        return {"fit_proposals_generated": len(fix_rows)}

    def get_health_scorecard(self) -> Dict[str, Any]:
        """Generates overall timeline health metrics, hydration percentages, and gap breakdown."""
        c = self.conn.cursor()

        c.execute("SELECT COUNT(*) as cnt FROM segments;")
        total_segs = c.fetchone()['cnt']

        c.execute("SELECT COUNT(*) as cnt FROM segments WHERE segment_type = 'visit';")
        total_visits = c.fetchone()['cnt']

        c.execute("SELECT COUNT(*) as cnt FROM segments WHERE segment_type = 'visit' AND place_name IS NOT NULL;")
        named_visits = c.fetchone()['cnt']

        c.execute("SELECT COUNT(*) as cnt FROM segments WHERE segment_type = 'activity';")
        total_activities = c.fetchone()['cnt']

        c.execute("SELECT COUNT(*) as cnt FROM segments WHERE segment_type = 'activity' AND has_snapped_path = 1;")
        snapped_activities = c.fetchone()['cnt']

        c.execute("SELECT COUNT(*) as cnt FROM segments WHERE hierarchy_level = 1;")
        child_visits = c.fetchone()['cnt']

        c.execute("SELECT COUNT(*) as cnt FROM gaps WHERE is_historical = 0;")
        post_2010_gaps = c.fetchone()['cnt']

        c.execute("SELECT COUNT(*) as cnt FROM gaps WHERE is_historical = 0 AND raw_signals_count > 0;")
        gaps_with_signals = c.fetchone()['cnt']

        c.execute("SELECT COUNT(*) as cnt FROM anomalies WHERE anomaly_type = 'TOP_LEVEL_OVERLAP';")
        overlaps_cnt = c.fetchone()['cnt']

        c.execute("SELECT COUNT(*) as cnt FROM anomalies WHERE anomaly_type = 'SPEED_OUTLIER';")
        speed_cnt = c.fetchone()['cnt']

        c.execute("SELECT COUNT(*) as cnt FROM places;")
        total_places = c.fetchone()['cnt']

        c.execute("SELECT COUNT(*) as cnt FROM places WHERE name IS NOT NULL;")
        named_places = c.fetchone()['cnt']

        c.execute("SELECT MIN(date) as min_d, MAX(date) as max_d FROM segments;")
        date_bounds = c.fetchone()

        c.execute("SELECT SUM(distance_meters)/1000.0 as km FROM segments WHERE segment_type = 'activity';")
        total_km = c.fetchone()['km'] or 0.0

        place_hydration_pct = (named_visits / total_visits * 100.0) if total_visits > 0 else 0.0
        path_snapped_pct = (snapped_activities / total_activities * 100.0) if total_activities > 0 else 0.0

        return {
            "total_segments": total_segs,
            "total_visits": total_visits,
            "named_visits": named_visits,
            "place_hydration_rate_pct": round(place_hydration_pct, 1),
            "total_activities": total_activities,
            "snapped_activities": snapped_activities,
            "path_snapped_rate_pct": round(path_snapped_pct, 1),
            "child_visits": child_visits,
            "post_2010_gaps": post_2010_gaps,
            "gaps_with_raw_signals": gaps_with_signals,
            "top_level_overlaps": overlaps_cnt,
            "speed_anomalies": speed_cnt,
            "total_places_catalog": total_places,
            "named_places_catalog": named_places,
            "total_distance_km": round(total_km, 1),
            "date_range": [date_bounds['min_d'] if date_bounds else None, date_bounds['max_d'] if date_bounds else None]
        }


if __name__ == "__main__":
    engine = TimelineDiagnosticsEngine()
    report = engine.run_full_diagnostics()
    print("\n--- Health Scorecard ---")
    print(json.dumps(report['scorecard'], indent=2))
