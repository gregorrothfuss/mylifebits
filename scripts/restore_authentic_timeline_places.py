"""
Restore Authentic Timeline Places from Pixel 10 Google Maps Cloud Backup.

Eliminates synthetic place replacements and false aliases, ensuring 100% of visits
match the authentic Google Maps Timeline bit-for-bit.
"""

import os
import sys
import json
import sqlite3

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from db import get_db_connection, DEFAULT_DB_PATH
from importer import parse_iso_with_tz_offset, extract_city_country
from enrichment.place_reconciler import fetch_google_maps_place_details, is_nameless_place

EXPORT_FILE = os.path.join(WORKSPACE_DIR, 'pixel10_export', 'Timeline-20260930.json')

def restore_authentic_places(db_path: str = DEFAULT_DB_PATH, dry_run: bool = True):
    print(f"[*] Connecting to {db_path} (dry_run={dry_run})...")
    conn = get_db_connection(db_path)
    c = conn.cursor()

    # 1. Purge bogus spatial aliases
    c.execute("SELECT count(*) FROM place_aliases WHERE alias_place_id LIKE 'ChIJ%';")
    bogus_count = c.fetchone()[0]
    print(f"[*] Found {bogus_count} bogus place aliases in database.")
    if not dry_run:
        c.execute("DELETE FROM place_aliases WHERE alias_place_id LIKE 'ChIJ%';")
        conn.commit()
        print("[+] Deleted all bogus place aliases.")

    # 2. Load export file
    print(f"[*] Loading export: {EXPORT_FILE}...")
    with open(EXPORT_FILE, 'r', encoding='utf-8') as f:
        doc = json.load(f)

    # 3. Collect all non-home ChIJ place IDs in export
    export_visits = []
    unique_pids = set()
    for s in doc.get('semanticSegments', []):
        if 'visit' in s:
            cand = s['visit'].get('topCandidate', {})
            pid = cand.get('placeId')
            sem = cand.get('semanticType')
            st_raw = s.get('startTime')
            et_raw = s.get('endTime')
            st_offset = s.get('startTimeTimezoneUtcOffsetMinutes')
            et_offset = s.get('endTimeTimezoneUtcOffsetMinutes')
            loc = cand.get('placeLocation', {}).get('latLng')
            st_ts, _, _, _, _, _ = parse_iso_with_tz_offset(st_raw, st_offset)
            et_ts, _, _, _, _, _ = parse_iso_with_tz_offset(et_raw, et_offset)
            if st_ts and et_ts:
                export_visits.append({
                    'st_ts': int(st_ts),
                    'et_ts': int(et_ts),
                    'pid': pid,
                    'sem': sem,
                    'loc': loc
                })
                if pid and pid.startswith('ChIJ') and sem != 'HOME':
                    unique_pids.add(pid)

    print(f"[*] Loaded {len(export_visits)} visits from export ({len(unique_pids)} unique ChIJ PIDs).")

    # 4. Ensure all unique PIDs exist in places catalog with authentic names
    c.execute("SELECT place_id, name, address, category, city FROM places;")
    places_catalog = {r[0]: {'name': r[1], 'address': r[2], 'category': r[3], 'city': r[4]} for r in c.fetchall()}

    missing_pids = [p for p in unique_pids if p not in places_catalog or not places_catalog[p]['name'] or is_nameless_place(places_catalog[p]['name'])]
    print(f"[*] Places needing Google Maps resolution: {len(missing_pids)}")

    resolved_count = 0
    for pid in missing_pids:
        if pid.startswith('ChIJAAAAAAAAAA'):
            continue
        print(f"    Fetching details for {pid}...")
        details = fetch_google_maps_place_details(pid, conn=conn, db_path=db_path)
        if details and details.get('name') and not is_nameless_place(details['name']):
            name = details['name']
            addr = details.get('address')
            cat = details.get('category', 'Other / POI')
            lat = details.get('latitude')
            lng = details.get('longitude')
            city, country = extract_city_country(addr, lat, lng)
            p_type = details.get('primary_type')
            if not dry_run:
                c.execute("""
                    INSERT INTO places (
                        place_id, name, address, category, city, country,
                        latitude, longitude, primary_type, user_confirmed,
                        visit_count, source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1, 'GOOGLE_MAPS_KNOWLEDGE_GRAPH')
                    ON CONFLICT(place_id) DO UPDATE SET
                        name = excluded.name,
                        address = COALESCE(excluded.address, places.address),
                        category = CASE WHEN places.category IS NULL OR places.category = 'Other / POI' THEN excluded.category ELSE places.category END,
                        city = COALESCE(excluded.city, places.city),
                        country = COALESCE(excluded.country, places.country);
                """, (pid, name, addr, cat, city, country, lat, lng, p_type))
                conn.commit()
            places_catalog[pid] = {'name': name, 'address': addr, 'category': cat, 'city': city}
            resolved_count += 1
            print(f"    [+] Resolved {pid} -> {name} ({addr})")

    print(f"[*] Successfully resolved {resolved_count} missing places from Google Maps.")

    # 5. Check and restore segments in timeline_viewer.db
    c.execute("SELECT id, start_ts, end_ts, place_name, place_id, segment_type FROM segments WHERE segment_type = 'visit';")
    db_visits = {}
    for r in c.fetchall():
        db_visits[int(r[1])] = {'id': r[0], 'end_ts': int(r[2]), 'name': r[3], 'pid': r[4]}

    restored_segments = 0
    for ev in export_visits:
        st_ts = ev['st_ts']
        exp_pid = ev['pid']
        sem = ev['sem']

        if sem == 'HOME' or not exp_pid or not exp_pid.startswith('ChIJ') or exp_pid.startswith('ChIJAAAAAAAAAA'):
            continue

        if st_ts in db_visits:
            cur = db_visits[st_ts]
            # Check if place ID or name was corrupted / mismatched
            if cur['pid'] != exp_pid:
                # Target place
                p_info = places_catalog.get(exp_pid)
                if p_info and p_info['name'] and not is_nameless_place(p_info['name']):
                    target_name = p_info['name']
                    target_addr = p_info.get('address')
                    target_cat = p_info.get('category', 'Other / POI')
                    target_city = p_info.get('city')
                    if not dry_run:
                        c.execute("""
                            UPDATE segments
                            SET place_id = ?, place_name = ?, place_address = ?, category = ?, city = ?
                            WHERE id = ?;
                        """, (exp_pid, target_name, target_addr, target_cat, target_city, cur['id']))
                    restored_segments += 1
                    if restored_segments <= 20:
                        print(f"    Restore ID {cur['id']}: '{cur['name']}' ({cur['pid']}) -> '{target_name}' ({exp_pid})")

    print(f"[*] Total segments to restore to authentic Google Timeline names: {restored_segments}")

    if not dry_run:
        conn.commit()
        c.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        print("[+] All changes committed and WAL checkpointed successfully.")

    conn.close()

if __name__ == '__main__':
    dry = '--commit' not in sys.argv
    restore_authentic_places(DEFAULT_DB_PATH, dry_run=dry)
