"""
Multi-Source Enrichment Engine & Fix Proposal Reasoner.
Orchestrates connectors, generates explainable timeline patches, and applies user-approved fixes.
"""

import json
import datetime
from typing import Dict, Any, List, Optional
import sqlite3

from db import get_db_connection, DEFAULT_DB_PATH
from enrichment.base import BaseEnrichmentConnector, FixProposalData
from enrichment.photos import PhotosEXIFConnector
from enrichment.transactions import TransactionsConnector
from enrichment.email_connector import EmailConnector
from enrichment.routing import RoutingSnapperConnector


class TimelineEnrichmentEngine:
    """Evaluates timeline gaps and unconfirmed places, proposing explainable fixes."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self.connectors: List[BaseEnrichmentConnector] = [
            PhotosEXIFConnector(),
            TransactionsConnector(),
            EmailConnector(),
            RoutingSnapperConnector()
        ]

    def register_connector(self, connector: BaseEnrichmentConnector) -> None:
        self.connectors.append(connector)

    def generate_all_proposals(self) -> Dict[str, Any]:
        """Runs all registered connectors against open gaps and unconfirmed places."""
        conn = get_db_connection(self.db_path)
        c = conn.cursor()

        # Fetch open gaps
        c.execute("""
        SELECT id, start_time, end_time, start_ts, end_ts, date, duration_hours,
               prev_lat, prev_lng, next_lat, next_lng, jump_distance_km
        FROM gaps
        WHERE status = 'OPEN' AND is_historical = 0
        ORDER BY duration_hours DESC;
        """)
        gaps = [dict(r) for r in c.fetchall()]

        # Fetch unconfirmed places
        c.execute("""
        SELECT id, start_time, end_time, start_ts, end_ts, date,
               latitude, longitude, place_id, semantic_type
        FROM segments
        WHERE segment_type = 'visit' AND is_unconfirmed = 1
        ORDER BY start_ts DESC;
        """)
        unconfirmed = [dict(r) for r in c.fetchall()]

        all_proposals: List[FixProposalData] = []
        for conn_obj in self.connectors:
            try:
                props = conn_obj.generate_proposals(gaps, unconfirmed)
                all_proposals.extend(props)
            except Exception as e:
                print(f"[!] Error running connector {conn_obj.get_source_name()}: {e}")

        # Batch insert into fix_proposals table
        if all_proposals:
            rows = [p.to_tuple() for p in all_proposals]
            c.executemany("""
            INSERT INTO fix_proposals (
                target_type, target_id, date, proposed_action, source, reasoning,
                confidence, status, patch_data_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, rows)
            conn.commit()

        conn.close()
        return {
            "total_proposals_generated": len(all_proposals),
            "sources": list(set(p.source for p in all_proposals))
        }

    def apply_fix_proposal(self, proposal_id: int) -> bool:
        """Applies a proposed fix patch non-destructively to the database."""
        conn = get_db_connection(self.db_path)
        c = conn.cursor()
        c.execute("SELECT * FROM fix_proposals WHERE id = ?;", (proposal_id,))
        prop = c.fetchone()
        if not prop or prop['status'] != 'PENDING':
            conn.close()
            return False

        patch_data = json.loads(prop['patch_data_json'])
        action = prop['proposed_action']
        target_id = prop['target_id']

        if action == 'HYDRATE_PLACE':
            c.execute("""
            UPDATE segments
            SET place_name = ?,
                place_address = COALESCE(?, place_address),
                is_unconfirmed = 0
            WHERE id = ?;
            """, (patch_data.get('resolved_name'), patch_data.get('address'), target_id))

        elif action == 'EXTEND_STATIONARY_DWELL':
            gap_id = target_id
            c.execute("SELECT * FROM gaps WHERE id = ?;", (gap_id,))
            gap = c.fetchone()
            if gap:
                c.execute("SELECT * FROM segments WHERE id = ?;", (gap['prev_segment_id'],))
                prev_seg = c.fetchone()
                c.execute("SELECT * FROM segments WHERE id = ?;", (gap['next_segment_id'],))
                next_seg = c.fetchone()

                # 1. If preceding segment is a visit, extend it forward
                if prev_seg and prev_seg['segment_type'] == 'visit':
                    new_dur = (gap['end_ts'] - prev_seg['start_ts']) / 60.0
                    c.execute("""
                    UPDATE segments
                    SET end_time = ?, end_ts = ?, duration_minutes = ?
                    WHERE id = ?;
                    """, (gap['end_time'], gap['end_ts'], new_dur, prev_seg['id']))

                # 2. If preceding is activity but succeeding is a visit (e.g. Home), extend succeeding backward
                elif next_seg and next_seg['segment_type'] == 'visit':
                    new_dur = (next_seg['end_ts'] - gap['start_ts']) / 60.0
                    c.execute("""
                    UPDATE segments
                    SET start_time = ?, start_ts = ?, duration_minutes = ?
                    WHERE id = ?;
                    """, (gap['start_time'], gap['start_ts'], new_dur, next_seg['id']))

                # 3. If both are activities, insert a stationary visit in between
                else:
                    g_yr = int(gap['date'][:4]) if gap['date'] else 2026
                    g_mo = int(gap['date'][5:7]) if gap['date'] else 8
                    g_day = int(gap['date'][8:10]) if gap['date'] else 20
                    dur_m = (gap['end_ts'] - gap['start_ts']) / 60.0
                    from life_periods import get_date_aware_label
                    label, cat = get_date_aware_label(self.db_path, "Stationary Dwell", gap['prev_lat'], gap['prev_lng'], gap['date'])
                    pname = label if label else "Stationary Dwell"
                    c.execute("""
                    INSERT INTO segments (
                        segment_type, place_name, place_address, category, start_time, end_time, start_ts, end_ts,
                        duration_minutes, date, year, month, day, latitude, longitude, hierarchy_level, is_unconfirmed
                    ) VALUES (
                        'visit', ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, 0, 0
                    );
                    """, (
                        pname, pname, cat or 'Other / POI', gap['start_time'], gap['end_time'],
                        gap['start_ts'], gap['end_ts'], dur_m, gap['date'], g_yr, g_mo, g_day,
                        gap['prev_lat'], gap['prev_lng']
                    ))

            c.execute("UPDATE gaps SET status = 'RESOLVED' WHERE id = ?;", (gap_id,))

        elif action == 'SYNTHESIZE_TRANSIT_LEG':
            gap_id = target_id
            c.execute("SELECT * FROM gaps WHERE id = ?;", (gap_id,))
            gap = c.fetchone()
            if gap:
                mode = patch_data.get('mode', 'IN_PASSENGER_VEHICLE')
                dur_m = patch_data.get('duration_minutes', gap['duration_hours'] * 60.0)
                dist_m = patch_data.get('distance_km', gap['jump_distance_km'] or 0.0) * 1000.0
                path_pts = json.dumps([[gap['prev_lat'], gap['prev_lng']], [gap['next_lat'], gap['next_lng']]]) if gap['prev_lat'] else None
                g_yr = int(gap['date'][:4]) if gap['date'] else 2026
                g_mo = int(gap['date'][5:7]) if gap['date'] else 8
                g_day = int(gap['date'][8:10]) if gap['date'] else 20
                
                c.execute("""
                INSERT INTO segments (
                    segment_type, activity_type, start_time, end_time, start_ts, end_ts,
                    duration_minutes, distance_meters, date, year, month, day, latitude, longitude,
                    end_lat, end_lng, path_points_json, has_snapped_path, hierarchy_level
                ) VALUES (
                    'activity', ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, 1, 0
                );
                """, (
                    mode, gap['start_time'], gap['end_time'], gap['start_ts'], gap['end_ts'],
                    dur_m, dist_m, gap['date'], g_yr, g_mo, g_day, gap['prev_lat'], gap['prev_lng'],
                    gap['next_lat'], gap['next_lng'], path_pts
                ))
            c.execute("UPDATE gaps SET status = 'RESOLVED' WHERE id = ?;", (gap_id,))

        elif action in ('RECONSTRUCT_FROM_BREADCRUMBS', 'INSERT_VISIT'):
            gap_id = target_id
            c.execute("SELECT * FROM gaps WHERE id = ?;", (gap_id,))
            gap = c.fetchone()
            if gap:
                g_yr = int(gap['date'][:4]) if gap['date'] else 2026
                g_mo = int(gap['date'][5:7]) if gap['date'] else 8
                g_day = int(gap['date'][8:10]) if gap['date'] else 20

                c.execute("""
                SELECT lat, lng, speed_kmh, timestamp
                FROM breadcrumbs
                WHERE timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC;
                """, (int(gap['start_ts']), int(gap['end_ts'])))
                bc_pts = c.fetchall()
                lat_val = patch_data.get('latitude') or (bc_pts[0]['lat'] if bc_pts else gap['prev_lat'])
                lng_val = patch_data.get('longitude') or (bc_pts[0]['lng'] if bc_pts else gap['prev_lng'])
                dur_m = (gap['end_ts'] - gap['start_ts']) / 60.0

                from breadcrumbs import haversine_distance
                from life_periods import get_date_aware_label

                is_movement = False
                if bc_pts and len(bc_pts) >= 2:
                    p1 = bc_pts[0]
                    p2 = bc_pts[-1]
                    displacement_m = haversine_distance(p1['lat'], p1['lng'], p2['lat'], p2['lng'])
                    overall_speed_kmh = (displacement_m / 1000.0) / (dur_m / 60.0) if dur_m > 0 else 0
                    # Only consider movement if short duration, significant displacement, and plausible transport speed
                    if displacement_m > 600.0 and overall_speed_kmh > 4.5 and dur_m < 180.0:
                        is_movement = True

                if not is_movement:
                    # Stationary visit
                    poi_name = patch_data.get('resolved_poi_name') or 'Recovered Visit'
                    addr_val = patch_data.get('address') or (poi_name if 'Terrace' in poi_name or 'Street' in poi_name or 'Ave' in poi_name else None)
                    label, cat = get_date_aware_label(self.db_path, poi_name, lat_val, lng_val, gap['date'])
                    final_name = label if label else poi_name
                    c.execute("""
                    INSERT INTO segments (
                        segment_type, start_time, end_time, start_ts, end_ts,
                        duration_minutes, date, year, month, day, latitude, longitude,
                        place_name, place_address, category, hierarchy_level, is_unconfirmed
                    ) VALUES (
                        'visit', ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, 0, 0
                    );
                    """, (
                        gap['start_time'], gap['end_time'], gap['start_ts'], gap['end_ts'],
                        dur_m, gap['date'], g_yr, g_mo, g_day, lat_val, lng_val,
                        final_name, addr_val, cat
                    ))
                else:
                    # Movement activity
                    avg_speed = sum(p['speed_kmh'] or 0 for p in bc_pts) / len(bc_pts)
                    mode = 'WALKING' if avg_speed < 6 else ('CYCLING' if avg_speed < 25 else 'IN_PASSENGER_VEHICLE')
                    path_json = json.dumps([[p['lat'], p['lng']] for p in bc_pts])
                    c.execute("""
                    INSERT INTO segments (
                        segment_type, activity_type, start_time, end_time, start_ts, end_ts,
                        duration_minutes, date, year, month, day, latitude, longitude,
                        end_lat, end_lng, path_points_json, has_snapped_path, hierarchy_level
                    ) VALUES (
                        'activity', ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, 0, 0
                    );
                    """, (
                        mode, gap['start_time'], gap['end_time'], gap['start_ts'], gap['end_ts'],
                        dur_m, gap['date'], g_yr, g_mo, g_day, bc_pts[0]['lat'], bc_pts[0]['lng'],
                        bc_pts[-1]['lat'], bc_pts[-1]['lng'], path_json
                    ))
            c.execute("UPDATE gaps SET status = 'RESOLVED' WHERE id = ?;", (gap_id,))

        elif action == 'DOCUMENTED_HIATUS':
            gap_id = target_id
            c.execute("UPDATE gaps SET status = 'RESOLVED_HIATUS' WHERE id = ?;", (gap_id,))

        elif action in ('INSERT_ORIGIN_AIRPORT', 'INSERT_DESTINATION_AIRPORT'):
            flight_id = patch_data.get('flight_id') or target_id
            c.execute("SELECT * FROM segments WHERE id = ?;", (flight_id,))
            flight_seg = c.fetchone()
            if flight_seg:
                airport_name = patch_data.get('airport_name') or 'Airport'
                iata = patch_data.get('airport_iata')
                full_name = f"{airport_name} ({iata})" if iata and iata not in airport_name else airport_name
                lat = patch_data.get('lat') or flight_seg['latitude']
                lng = patch_data.get('lng') or flight_seg['longitude']
                f_yr = int(flight_seg['date'][:4]) if flight_seg['date'] else 2026
                f_mo = int(flight_seg['date'][5:7]) if flight_seg['date'] else 8
                f_day = int(flight_seg['date'][8:10]) if flight_seg['date'] else 20

                if action == 'INSERT_ORIGIN_AIRPORT':
                    end_ts = flight_seg['start_ts']
                    start_ts = end_ts - 2700.0  # 45 min gate boarding dwell
                    dur_m = 45.0
                    from enrichment.local_timezone import get_timezone_offset_hours
                    off1 = get_timezone_offset_hours(flight_seg['latitude'], flight_seg['longitude'], start_ts)
                    dt_st = datetime.datetime.fromtimestamp(start_ts, tz=datetime.timezone.utc) + datetime.timedelta(hours=off1)
                    st_iso = dt_st.strftime("%Y-%m-%dT%H:%M:%S") + f"{'+' if off1>=0 else '-'}{abs(int(off1)):02d}:00"
                    et_iso = flight_seg['start_time']
                else:
                    # INSERT_DESTINATION_AIRPORT: Spliced from flight tail before taxi/transit
                    end_ts = flight_seg['end_ts']
                    start_ts = end_ts - 1800.0  # 30 mins deplaning dwell
                    dur_m = 30.0

                    from enrichment.local_timezone import get_timezone_offset_hours
                    dest_lat = flight_seg['end_lat'] if flight_seg['end_lat'] is not None else lat
                    dest_lng = flight_seg['end_lng'] if flight_seg['end_lng'] is not None else lng
                    off2 = get_timezone_offset_hours(dest_lat, dest_lng, start_ts)
                    dt_st = datetime.datetime.fromtimestamp(start_ts, tz=datetime.timezone.utc) + datetime.timedelta(hours=off2)
                    st_iso = dt_st.strftime("%Y-%m-%dT%H:%M:%S") + f"{'+' if off2>=0 else '-'}{abs(int(off2)):02d}:00"
                    et_iso = flight_seg['end_time']

                    # Trim flight end time so flight touches down when airport visit begins
                    new_flight_dur = (start_ts - flight_seg['start_ts']) / 60.0
                    c.execute("""
                    UPDATE segments
                    SET end_time = ?, end_ts = ?, duration_minutes = ?
                    WHERE id = ?;
                    """, (st_iso, start_ts, new_flight_dur, flight_id))

                c.execute("""
                SELECT id FROM segments
                WHERE date = ? AND start_ts = ? AND end_ts = ? AND place_name = ?;
                """, (flight_seg['date'], start_ts, end_ts, full_name))
                if not c.fetchone():
                    c.execute("""
                    INSERT INTO segments (
                        segment_type, place_name, place_address, category, start_time, end_time, start_ts, end_ts,
                        duration_minutes, date, year, month, day, latitude, longitude, hierarchy_level, is_unconfirmed
                    ) VALUES (
                        'visit', ?, ?, 'Travel & Transit', ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, 0, 0
                    );
                    """, (
                        full_name, full_name, st_iso, et_iso, start_ts, end_ts,
                        dur_m, flight_seg['date'], f_yr, f_mo, f_day, lat, lng
                    ))

        elif action == 'SYNTHESIZE_FIT_ACTIVITY':
            gap_id = target_id
            c.execute("SELECT * FROM gaps WHERE id = ?;", (gap_id,))
            gap = c.fetchone()
            if gap:
                mode = patch_data.get('activity_type', 'WALKING')
                dur_m = (gap['end_ts'] - gap['start_ts']) / 60.0
                g_yr = int(gap['date'][:4]) if gap['date'] else 2026
                g_mo = int(gap['date'][5:7]) if gap['date'] else 8
                g_day = int(gap['date'][8:10]) if gap['date'] else 20
                c.execute("""
                INSERT INTO segments (
                    segment_type, activity_type, start_time, end_time, start_ts, end_ts,
                    duration_minutes, date, year, month, day, latitude, longitude,
                    end_lat, end_lng, hierarchy_level
                ) VALUES (
                    'activity', ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, 0
                );
                """, (
                    mode, gap['start_time'], gap['end_time'], gap['start_ts'], gap['end_ts'],
                    dur_m, gap['date'], g_yr, g_mo, g_day, gap['prev_lat'], gap['prev_lng'],
                    gap['next_lat'], gap['next_lng']
                ))
                c.execute("UPDATE gaps SET status = 'RESOLVED' WHERE id = ?;", (gap_id,))

        # Update proposal state
        c.execute("""
        UPDATE fix_proposals
        SET status = 'ACCEPTED', applied_at = datetime('now')
        WHERE id = ?;
        """, (proposal_id,))

        conn.commit()
        conn.close()
        return True

    def reject_fix_proposal(self, proposal_id: int) -> bool:
        """Rejects a proposed fix without modifying baseline data."""
        conn = get_db_connection(self.db_path)
        c = conn.cursor()
        c.execute("""
        UPDATE fix_proposals
        SET status = 'REJECTED'
        WHERE id = ?;
        """, (proposal_id,))
        conn.commit()
        conn.close()
        return True


if __name__ == "__main__":
    engine = TimelineEnrichmentEngine()
    print("Timeline Enrichment Engine successfully initialized.")
