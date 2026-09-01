import os, sys, json, sqlite3, struct, hashlib, datetime
from typing import List, Dict, Any

WORKSPACE_DIR = os.getcwd()
sys.path.insert(0, WORKSPACE_DIR)
import odlh_path_engine as pe
from scripts.build_master_odlh_pure import (
    build_visit_proto, build_activity_proto_snapped, ACTIVITY_ENUM_MAP,
    get_place_fprint_and_cell, ramer_douglas_peucker
)

P10_JSON = os.path.join(WORKSPACE_DIR, 'pixel10_export', 'Timeline-latest.json')
OUT_ODLH_DB = os.path.join(WORKSPACE_DIR, 'scratch', 'odlh_pixel10_baseline.db')
OUT_AUX_DB = os.path.join(WORKSPACE_DIR, 'scratch', 'aux_pixel10_baseline.db')
VIEWER_DB = os.path.join(WORKSPACE_DIR, 'timeline_viewer.db')

GAIA_ID = '104819208193648646391'

def main():
    print("=================================================================")
    print("[*] COMPILING UNMODIFIED PIXEL 10 BASELINE EXPORT TO ODLH STORAGE")
    print("=================================================================")

    with open(P10_JSON, 'r') as f:
        data = json.load(f)

    segs = data.get('semanticSegments', [])
    print(f"[1/4] Loaded {len(segs):,} segments from Pixel 10 export.")

    # Connect to places catalog to get verified names
    conn_v = sqlite3.connect(VIEWER_DB)
    c_v = conn_v.cursor()
    c_v.execute("SELECT place_id, name, address, latitude, longitude FROM places;")
    place_map = {r[0]: {'name': r[1], 'addr': r[2], 'lat': r[3], 'lng': r[4]} for r in c_v.fetchall()}
    conn_v.close()

    # Compile ODLH DB
    if os.path.exists(OUT_ODLH_DB): os.remove(OUT_ODLH_DB)
    conn_o = sqlite3.connect(OUT_ODLH_DB)
    c_o = conn_o.cursor()
    c_o.execute("PRAGMA user_version = 12;")
    c_o.execute("PRAGMA page_size = 4096;")
    c_o.execute("""
    CREATE TABLE semantic_segment_table (
        _id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp_millis INTEGER,
        database_id INTEGER,
        origin_id INTEGER,
        segment_id TEXT,
        semantic_segment BLOB,
        obfuscated_gaia_id TEXT,
        shown_in_timeline INTEGER,
        is_finalized INTEGER,
        start_timestamp_seconds INTEGER,
        end_timestamp_seconds INTEGER,
        segment_type INTEGER,
        hierarchy_level INTEGER,
        fprint INTEGER
    );
    """)
    c_o.execute("CREATE INDEX index_semantic_segment_table_obfuscated_gaia_id_shown_in_timeline ON semantic_segment_table (obfuscated_gaia_id, shown_in_timeline);")
    c_o.execute("CREATE INDEX index_semantic_segment_table_start_timestamp_seconds ON semantic_segment_table (start_timestamp_seconds);")
    c_o.execute("CREATE INDEX index_semantic_segment_table_end_timestamp_seconds ON semantic_segment_table (end_timestamp_seconds);")
    c_o.execute("CREATE INDEX index_semantic_segment_table_segment_type ON semantic_segment_table (segment_type);")

    insert_rows = []
    curr_origin = 1000

    for idx, s in enumerate(segs):
        st_str = s.get('startTime', '')
        et_str = s.get('endTime', '')
        if not (st_str and et_str): continue

        st_dt = datetime.datetime.fromisoformat(st_str)
        et_dt = datetime.datetime.fromisoformat(et_str)
        sts = int(st_dt.timestamp())
        ets = int(et_dt.timestamp())
        if ets <= sts: continue

        seg_id = f"p10_seg_{idx+1}"
        tz_offset_m = s.get('startTimeTimezoneUtcOffsetMinutes', -240)

        pv = s.get('visit')
        act = s.get('activity')

        if pv:
            cand = pv.get('topCandidate', {})
            pid = cand.get('placeId')
            ploc_str = cand.get('placeLocation', {}).get('latLng', '')
            lat, lng = 0.0, 0.0
            if '°' in ploc_str:
                parts = ploc_str.replace('°', '').split(',')
                try: lat, lng = float(parts[0].strip()), float(parts[1].strip())
                except: pass
            if not (lat and lng) and pid in place_map:
                lat, lng = place_map[pid]['lat'] or 0.0, place_map[pid]['lng'] or 0.0

            if not pid: pid = f"gen_{abs(hash(str(lat)+str(lng)))}"
            p_name = place_map.get(pid, {}).get('name', '')
            p_addr = place_map.get(pid, {}).get('addr', '')

            cid, fp, fp_signed = get_place_fprint_and_cell(pid, p_name, p_addr, lat, lng)

            # Build visit proto
            blob_vis = build_visit_proto(sts, ets, cid, fp, lat, lng, seg_id, tz_offset_m=tz_offset_m)
            insert_rows.append((
                None, sts * 1000, 1787254103124001536, curr_origin, seg_id, blob_vis,
                GAIA_ID, 1, 1, sts, ets, 1, 0, fp_signed
            ))
            curr_origin += 1

        elif act:
            cand = act.get('topCandidate', {})
            atype_str = cand.get('type', 'WALKING')
            act_code = ACTIVITY_ENUM_MAP.get(atype_str.upper(), 2)
            dist_m = float(act.get('distanceMeters', 0.0) or 0.0)

            s_loc_str = act.get('startPoint', {}).get('latLng', '')
            e_loc_str = act.get('endPoint', {}).get('latLng', '')
            s_lat, s_lng = 40.7271, -73.9774
            e_lat, e_lng = 40.7271, -73.9774

            if '°' in s_loc_str:
                parts = s_loc_str.replace('°', '').split(',')
                try: s_lat, s_lng = float(parts[0].strip()), float(parts[1].strip())
                except: pass
            if '°' in e_loc_str:
                parts = e_loc_str.replace('°', '').split(',')
                try: e_lat, e_lng = float(parts[0].strip()), float(parts[1].strip())
                except: pass

            path_pts = act.get('timelinePath', [])
            raw_coords = []
            for p in path_pts:
                p_str = p.get('point', '')
                if '°' in p_str:
                    parts = p_str.replace('°', '').split(',')
                    try: raw_coords.append([float(parts[0].strip()), float(parts[1].strip())])
                    except: pass
            if len(raw_coords) < 2:
                coords = [[s_lat, s_lng], [e_lat, e_lng]]
            else:
                coords = ramer_douglas_peucker(raw_coords, epsilon=0.000008)
                if len(coords) > 50:
                    coords = ramer_douglas_peucker(raw_coords, epsilon=0.00002)
                if len(coords) < 2:
                    coords = [[s_lat, s_lng], [e_lat, e_lng]]
                else:
                    coords[0] = [s_lat, s_lng]
                    coords[-1] = [e_lat, e_lng]

            blob_act = build_activity_proto_snapped(sts, ets, act_code, dist_m, seg_id, coords, s_lat, s_lng, e_lat, e_lng, tz_offset_m=tz_offset_m)
            insert_rows.append((
                None, sts * 1000, 1787254103124001536, curr_origin, seg_id, blob_act,
                GAIA_ID, 1, 1, sts, ets, 2, 0, None
            ))
            curr_origin += 1

    c_o.executemany("""
    INSERT INTO semantic_segment_table
    (_id, timestamp_millis, database_id, origin_id, segment_id, semantic_segment, obfuscated_gaia_id, shown_in_timeline, is_finalized, start_timestamp_seconds, end_timestamp_seconds, segment_type, hierarchy_level, fprint)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, insert_rows)
    conn_o.commit()

    # Build matching aux-odlh-storage.db
    if os.path.exists(OUT_AUX_DB): os.remove(OUT_AUX_DB)
    conn_aux = sqlite3.connect(OUT_AUX_DB)
    c_aux = conn_aux.cursor()
    c_aux.execute("""
    CREATE TABLE aux_semantic_segment_table (
        _id INTEGER PRIMARY KEY AUTOINCREMENT,
        segment_id TEXT NOT NULL,
        metadata BLOB,
        obfuscated_gaia_id TEXT NOT NULL,
        start_timestamp_seconds INTEGER NOT NULL,
        end_timestamp_seconds INTEGER NOT NULL,
        segment_type INTEGER NOT NULL
    );
    """)
    c_o.execute("SELECT _id, segment_id, obfuscated_gaia_id, start_timestamp_seconds, end_timestamp_seconds, segment_type FROM semantic_segment_table ORDER BY _id ASC;")
    aux_rows = [(r[0], r[1], None, r[2], r[3], r[4], r[5]) for r in c_o.fetchall()]
    c_aux.executemany("INSERT INTO aux_semantic_segment_table VALUES (?, ?, ?, ?, ?, ?, ?);", aux_rows)
    conn_aux.commit()
    conn_aux.close()

    conn_o.close()
    print(f"[✓] Compiled Pixel 10 baseline ODLH storage + aux DB: {len(insert_rows):,} rows.")

if __name__ == '__main__':
    main()
