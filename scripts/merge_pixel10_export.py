"""
Merge Pixel 10 Timeline JSON Export with Strict Local Edit Protection.

Imports fresh visits and activities from 'pixel10_export/Timeline-20260825.json'
into 'timeline_viewer.db', strictly preserving:
  1. User-confirmed visits and manual place name edits
  2. Accepted fix proposals (status = 'ACCEPTED')
  3. Snapped/stitched cycling & walking routes
  4. Attached contributor review photos and ratings
  5. Multi-source enrichments (Plazes, Swarm, Mail, Calendar)
"""

import os
import sys
import json
import sqlite3
import datetime
import math
import bisect
from typing import Dict, Any, List, Optional, Tuple, Set

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from db import get_db_connection, DEFAULT_DB_PATH
from importer import parse_latlng_str, parse_iso_with_tz_offset, haversine_km, classify_category, extract_city_country, synthesize_place_name
from life_periods import get_date_aware_label
from enrichment.place_reconciler import (
    is_nameless_place,
    reconcile_place_spatial,
    reverse_geocode_osm,
    get_aliased_place,
    record_place_alias,
    resolve_synthetic_feature_id,
    fetch_google_maps_place_details,
)

def enforce_zero_gap_constraints(conn, date_str: str) -> None:
    """Enforces zero-gap timeline continuity on save, merging adjacent duplicate visits,
    stitching boundaries, and calculating distances."""
    c = conn.cursor()

    # Pass 1: Merge adjacent identical visits (same place name or within 100m)
    merged_any = True
    while merged_any:
        merged_any = False
        c.execute("""
        SELECT id, segment_type, place_name, start_time, end_time, start_ts, end_ts,
               duration_minutes, latitude, longitude, date
        FROM segments
        WHERE date = ? OR end_time LIKE ? OR start_time LIKE ?
        ORDER BY start_ts ASC;
        """, (date_str, f"{date_str}%", f"{date_str}%"))
        segs = [dict(r) for r in c.fetchall()]
        if not segs:
            break

        for i in range(len(segs) - 1):
            curr = segs[i]
            nxt = segs[i + 1]
            if curr['segment_type'] == 'visit' and nxt['segment_type'] == 'visit':
                same_place = False
                if curr.get('place_name') and nxt.get('place_name') and curr['place_name'] == nxt['place_name']:
                    same_place = True
                elif curr.get('latitude') and nxt.get('latitude'):
                    dist_m = haversine_km(curr['latitude'], curr['longitude'], nxt['latitude'], nxt['longitude']) * 1000.0
                    if dist_m < 100.0:
                        same_place = True

                time_gap = nxt['start_ts'] - curr['end_ts']
                if same_place and time_gap <= 900:
                    new_end_ts = max(curr['end_ts'], nxt['end_ts'])
                    new_end_time = nxt['end_time'] if nxt['end_ts'] >= curr['end_ts'] else curr['end_time']
                    new_dur = (new_end_ts - curr['start_ts']) / 60.0

                    c.execute("""
                    UPDATE segments
                    SET end_ts = ?, end_time = ?, duration_minutes = ?
                    WHERE id = ?;
                    """, (new_end_ts, new_end_time, new_dur, curr['id']))

                    c.execute("UPDATE gaps SET prev_segment_id = ? WHERE prev_segment_id = ?;", (curr['id'], nxt['id']))
                    c.execute("UPDATE gaps SET next_segment_id = ? WHERE next_segment_id = ?;", (curr['id'], nxt['id']))
                    c.execute("UPDATE anomalies SET segment_id = ? WHERE segment_id = ?;", (curr['id'], nxt['id']))
                    c.execute("UPDATE segments SET parent_segment_id = ? WHERE parent_segment_id = ?;", (curr['id'], nxt['id']))
                    c.execute("UPDATE fix_proposals SET target_id = ? WHERE target_type = 'segment' AND target_id = ?;", (curr['id'], nxt['id']))
                    c.execute("DELETE FROM segments WHERE id = ?;", (nxt['id'],))
                    conn.commit()
                    merged_any = True
                    break

    # Pass 2: Overlap and micro-gap stitching
    c.execute("""
    SELECT id, segment_type, activity_type, start_time, end_time, start_ts, end_ts,
           latitude, longitude, end_lat, end_lng, path_points_json, distance_meters
    FROM segments
    WHERE date = ? OR end_time LIKE ? OR start_time LIKE ?
    ORDER BY start_ts ASC;
    """, (date_str, f"{date_str}%", f"{date_str}%"))
    segs = [dict(r) for r in c.fetchall()]
    if not segs:
        return

    for i in range(len(segs) - 1):
        curr = segs[i]
        nxt = segs[i + 1]
        diff = nxt['start_ts'] - curr['end_ts']

        if diff < 0:
            new_end_ts = nxt['start_ts']
            new_dur = max(1.0, (new_end_ts - curr['start_ts']) / 60.0)
            c.execute("UPDATE segments SET end_ts = ?, end_time = ?, duration_minutes = ? WHERE id = ?;", (new_end_ts, nxt['start_time'], new_dur, curr['id']))
            curr['end_ts'] = new_end_ts

        elif 0 < diff <= 60:
            if curr['segment_type'] == 'visit':
                new_end_ts = nxt['start_ts']
                new_dur = (new_end_ts - curr['start_ts']) / 60.0
                c.execute("UPDATE segments SET end_ts = ?, end_time = ?, duration_minutes = ? WHERE id = ?;", (new_end_ts, nxt['start_time'], new_dur, curr['id']))
                curr['end_ts'] = new_end_ts
            elif nxt['segment_type'] == 'visit':
                new_start_ts = curr['end_ts']
                new_dur = (nxt['end_ts'] - new_start_ts) / 60.0
                c.execute("UPDATE segments SET start_ts = ?, start_time = ?, duration_minutes = ? WHERE id = ?;", (new_start_ts, curr['end_time'], new_dur, nxt['id']))
                nxt['start_ts'] = new_start_ts
            else:
                mid_ts = curr['end_ts'] + diff / 2.0
                c.execute("UPDATE segments SET end_ts = ?, duration_minutes = ? WHERE id = ?;", (mid_ts, (mid_ts - curr['start_ts']) / 60.0, curr['id']))
                c.execute("UPDATE segments SET start_ts = ?, duration_minutes = ? WHERE id = ?;", (mid_ts, (nxt['end_ts'] - mid_ts) / 60.0, nxt['id']))

    for s in segs:
        if s['segment_type'] == 'activity':
            calc_dist = 0.0
            if s.get('path_points_json'):
                try:
                    pts = json.loads(s['path_points_json'])
                    for k in range(len(pts) - 1):
                        calc_dist += haversine_km(pts[k][0], pts[k][1], pts[k+1][0], pts[k+1][1]) * 1000.0
                except Exception:
                    pass
            if calc_dist == 0.0 and s.get('latitude') is not None and s.get('end_lat') is not None:
                calc_dist = haversine_km(s['latitude'], s['longitude'], s['end_lat'], s['end_lng']) * 1000.0
            if calc_dist > 0:
                c.execute("UPDATE segments SET distance_meters = ? WHERE id = ?;", (calc_dist, s['id']))

    conn.commit()

EXPORT_FILE = os.path.join(WORKSPACE_DIR, "pixel10_export", "Timeline-20260921.json")

def get_protected_signatures(conn: sqlite3.Connection) -> Tuple[List[Tuple[int, int]], Set[str]]:
    """Loads sorted intervals and dates containing manual user edits or enrichments."""
    c = conn.cursor()
    protected_windows: List[Tuple[int, int]] = []
    protected_dates: Set[str] = set()

    # 1. User-confirmed places and edited visits (excluding PIXEL10_EXPORT_2026 so fresh exports can update)
    c.execute("""
        SELECT start_ts, end_ts, date, source
        FROM segments
        WHERE (is_unconfirmed = 0 AND source != 'PIXEL10_EXPORT_2026')
           OR source IN ('plazes', 'swarm', 'mail', 'user_edit')
           OR has_snapped_path = 1
           OR parent_segment_id IS NOT NULL;
    """)
    for r in c.fetchall():
        if r[0] and r[1]:
            protected_windows.append((int(r[0]), int(r[1])))
        if r[2]:
            protected_dates.add(r[2])

    # 2. Accepted Fix Proposals
    c.execute("SELECT target_id, date FROM fix_proposals WHERE status = 'ACCEPTED';")
    for r in c.fetchall():
        if r[1]:
            protected_dates.add(r[1])

    protected_windows.sort()
    return protected_windows, protected_dates

def run_merge(export_path: str = EXPORT_FILE, db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    print(f"[*] Reading export file: {export_path}...")
    with open(export_path, 'r', encoding='utf-8') as f:
        doc = json.load(f)

    raw_segments = doc.get('semanticSegments', [])
    print(f"[*] Loaded {len(raw_segments):,} semantic segments from export.")

    conn = get_db_connection(db_path)
    c = conn.cursor()

    # 1. Load protected windows (exclude previous PIXEL10_EXPORT_2026 so newly edited versions replace older drafts)
    protected_windows, protected_dates = get_protected_signatures(conn)
    pw_starts = [w[0] for w in protected_windows]
    print(f"[*] Protected {len(protected_windows):,} locally-edited time windows from overwrite.")

    # Remove previous unedited PIXEL10_EXPORT_2026 segments so updated phone edits take effect
    c.execute("DELETE FROM segments WHERE source = 'PIXEL10_EXPORT_2026';")
    conn.commit()

    # 2. Load existing segments
    c.execute("SELECT start_ts, end_ts, segment_type FROM segments;")
    existing_records = set((int(r[0]), int(r[1]), r[2]) for r in c.fetchall() if r[0] and r[1])
    print(f"[*] Found {len(existing_records):,} existing segments in local database.")

    # 3. Load places catalog
    c.execute("SELECT place_id, name, address, category, city, latitude, longitude, review_rating, review_photos FROM places;")
    places_catalog = {r[0]: dict(zip(['place_id', 'name', 'address', 'category', 'city', 'lat', 'lng', 'rating', 'photos'], r)) for r in c.fetchall() if r[0]}

    inserted_visits = 0
    inserted_activities = 0
    skipped_existing = 0
    skipped_protected = 0
    modified_dates: Set[str] = set()

    for seg in raw_segments:
        st_raw = seg.get('startTime')
        et_raw = seg.get('endTime')
        st_offset = seg.get('startTimeTimezoneUtcOffsetMinutes')
        et_offset = seg.get('endTimeTimezoneUtcOffsetMinutes')

        st_ts, d_str, yr, mo, dy, local_st = parse_iso_with_tz_offset(st_raw, st_offset)
        et_ts, _, _, _, _, local_et = parse_iso_with_tz_offset(et_raw, et_offset)

        if not st_ts or not et_ts:
            continue

        dur_min = max(1.0, (et_ts - st_ts) / 60.0)

        # ----------------------------------------------------
        # Handle Place Visit
        # ----------------------------------------------------
        if 'visit' in seg:
            pv = seg['visit']
            cand = pv.get('topCandidate', {})
            pid = cand.get('placeId')
            sem_type = cand.get('semanticType')
            prob = cand.get('probability', 1.0)
            hl = pv.get('hierarchyLevel', 0)
            lat, lng = parse_latlng_str(cand.get('placeLocation', {}).get('latLng'))

            key = (int(st_ts), int(et_ts), 'visit')
            if key in existing_records:
                skipped_existing += 1
                continue

            # Fast O(log N) interval overlap check against protected edits
            idx = bisect.bisect_right(pw_starts, et_ts)
            is_protected = False
            for k in range(max(0, idx - 5), min(len(protected_windows), idx + 2)):
                pw_st, pw_et = protected_windows[k]
                if max(st_ts, pw_st) < min(et_ts, pw_et):
                    is_protected = True
                    break

            if is_protected:
                skipped_protected += 1
                continue

            # Resolve place details and ensure place exists in places table to satisfy FK
            p_name, p_addr, p_cat, p_city = None, None, 'Other / POI', None
            rev_rating, rev_photos = None, None

            incoming_pid = pid
            aliased_info = get_aliased_place(conn, pid) if pid else None

            if pid and pid in places_catalog and not is_nameless_place(places_catalog[pid]['name']):
                p_info = places_catalog[pid]
                p_name = p_info['name']
                p_addr = p_info['address']
                p_cat = p_info['category']
                p_city = p_info['city']
                rev_rating = p_info['rating']
                rev_photos = p_info['photos']
            elif aliased_info:
                pid = aliased_info['place_id']
                p_name = aliased_info['name']
                p_addr = aliased_info['address']
                p_cat = aliased_info['category']
                p_city = aliased_info['city']
                rev_rating = aliased_info.get('review_rating')
            else:
                # Spatial reconciliation against canonical catalog and life periods
                sp_match = reconcile_place_spatial(db_path, lat, lng, date_str=d_str, conn=conn)
                if sp_match:
                    pid = sp_match['place_id']
                    p_name = sp_match['name']
                    p_addr = sp_match.get('address')
                    p_cat = sp_match.get('category', 'Other / POI')
                    p_city, p_country = extract_city_country(p_addr, lat, lng)
                    if incoming_pid and incoming_pid != pid:
                        record_place_alias(conn, incoming_pid, pid)
                elif lat is not None and lng is not None:
                    # Reverse geocode fallback to eliminate raw coordinate fallbacks
                    geo = reverse_geocode_osm(lat, lng)
                    if geo and geo.get('name'):
                        pid = f"osm_{lat:.5f}_{lng:.5f}"
                        p_name = geo['name']
                        p_addr = geo.get('address')
                        p_cat = geo.get('category', 'Other / POI')
                        p_city = geo.get('city')
                        p_country = geo.get('country')
                        c.execute("""
                            INSERT OR IGNORE INTO places (
                                place_id, name, address, semantic_type, category, city, country,
                                user_confirmed, latitude, longitude, visit_count, source
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """, (
                            pid, p_name, p_addr, sem_type, p_cat, p_city, p_country,
                            0, lat, lng, 1, 'PIXEL10_EXPORT_2026'
                        ))
                    else:
                        p_city, p_country = extract_city_country(None, lat, lng)
                        synth = synthesize_place_name(None, None, sem_type)
                        c.execute("""
                            INSERT OR IGNORE INTO places (
                                place_id, name, address, semantic_type, category, city, country,
                                user_confirmed, latitude, longitude, visit_count, source
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """, (
                            pid, synth, None, sem_type, 'Other / POI', p_city, p_country,
                            0, lat, lng, 1, 'PIXEL10_EXPORT_2026'
                        ))
                        p_name = synth
                else:
                    synth = synthesize_place_name(None, None, sem_type)
                    p_name = synth

            synth_name = synthesize_place_name(p_name, p_addr, sem_type)
            lbl, cat = get_date_aware_label(db_path, synth_name, lat, lng, d_str)
            if lbl:
                synth_name = lbl
                p_cat = cat

            c.execute("""
                INSERT INTO segments (
                    segment_type, start_time, end_time, start_ts, end_ts, duration_minutes,
                    date, year, month, day, latitude, longitude, place_id, place_name,
                    place_address, semantic_type, category, city, probability, hierarchy_level,
                    is_unconfirmed, source, review_rating, review_photos
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                'visit', local_st or st_raw, local_et or et_raw, float(st_ts), float(et_ts), dur_min,
                d_str, yr, mo, dy, lat, lng, pid, synth_name,
                p_addr, sem_type, p_cat, p_city, prob, hl,
                0, 'PIXEL10_EXPORT_2026', rev_rating, rev_photos
            ))
            inserted_visits += 1
            modified_dates.add(d_str)

        # ----------------------------------------------------
        # Handle Movement Activity
        # ----------------------------------------------------
        elif 'activity' in seg:
            act = seg['activity']
            cand = act.get('topCandidate', {})
            act_type = cand.get('type', 'TRAVEL')
            prob = cand.get('probability', 1.0)
            dist = act.get('distanceMeters', 0.0)
            s_lat, s_lng = parse_latlng_str(act.get('start', {}).get('latLng'))
            e_lat, e_lng = parse_latlng_str(act.get('end', {}).get('latLng'))

            if (not dist or dist == 0.0) and s_lat is not None and e_lat is not None:
                dist = haversine_km(s_lat, s_lng, e_lat, e_lng) * 1000.0

            key = (int(st_ts), int(et_ts), 'activity')
            if key in existing_records:
                skipped_existing += 1
                continue

            idx = bisect.bisect_right(pw_starts, et_ts)
            is_protected = False
            for k in range(max(0, idx - 5), min(len(protected_windows), idx + 2)):
                pw_st, pw_et = protected_windows[k]
                if max(st_ts, pw_st) < min(et_ts, pw_et):
                    is_protected = True
                    break

            if is_protected:
                skipped_protected += 1
                continue

            path_pts = [[s_lat, s_lng], [e_lat, e_lng]] if (s_lat and e_lat) else None

            c.execute("""
                INSERT INTO segments (
                    segment_type, start_time, end_time, start_ts, end_ts, duration_minutes,
                    date, year, month, day, latitude, longitude, end_lat, end_lng,
                    activity_type, distance_meters, probability, hierarchy_level,
                    is_unconfirmed, source, path_points_json, has_snapped_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                'activity', local_st or st_raw, local_et or et_raw, float(st_ts), float(et_ts), dur_min,
                d_str, yr, mo, dy, s_lat, s_lng, e_lat, e_lng,
                act_type, dist, prob, 0,
                0, 'PIXEL10_EXPORT_2026', json.dumps(path_pts) if path_pts else None, 0
            ))
            inserted_activities += 1
            modified_dates.add(d_str)

    conn.commit()

    # 4. Enforce zero-gap continuity on all modified recent dates
    print(f"[*] Re-stitching timeline boundaries for {len(modified_dates)} modified dates...")
    for dt_str in modified_dates:
        enforce_zero_gap_constraints(conn, dt_str)

    conn.commit()
    conn.close()

    result = {
        "status": "SUCCESS",
        "inserted_visits": inserted_visits,
        "inserted_activities": inserted_activities,
        "skipped_existing": skipped_existing,
        "skipped_protected": skipped_protected,
        "modified_dates": sorted(list(modified_dates))
    }

    print(f"\n[✓] Merge Complete:")
    print(f"    - New Visits Inserted: {inserted_visits:,}")
    print(f"    - New Activities Inserted: {inserted_activities:,}")
    print(f"    - Existing Skipped: {skipped_existing:,}")
    print(f"    - Protected Local Edits Preserved: {skipped_protected:,}")
    print(f"    - Modified Dates: {len(modified_dates)} dates ({min(modified_dates) if modified_dates else 'N/A'} to {max(modified_dates) if modified_dates else 'N/A'})")

    return result

if __name__ == "__main__":
    export_f = sys.argv[1] if len(sys.argv) > 1 else os.path.join(WORKSPACE_DIR, "pixel10_export", "Timeline-20260921.json")
    run_merge(export_f)
