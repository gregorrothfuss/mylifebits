import os, sys, json, sqlite3, struct, hashlib, urllib.parse, time, datetime, base64, math
from typing import List, Tuple, Dict, Any

WORKSPACE_DIR = os.getcwd()
sys.path.insert(0, WORKSPACE_DIR)
import odlh_path_engine as pe

VIEWER_DB = os.path.join(WORKSPACE_DIR, 'timeline_viewer.db')
OUT_ODLH_DB = os.path.join(WORKSPACE_DIR, 'scratch', 'odlh_master_pure.db')
OUT_AUX_DB = os.path.join(WORKSPACE_DIR, 'scratch', 'aux-odlh-storage.db')
OUT_MYPLACES_DB = os.path.join(WORKSPACE_DIR, 'scratch', 'gmm_myplaces_pure.db')
OUT_SYNC_DB = os.path.join(WORKSPACE_DIR, 'scratch', 'gmm_sync_pure.db')
OUT_PLACES2_PATH = os.path.join(WORKSPACE_DIR, 'scratch', 'places_2_pure')

GAIA_ID = '104819208193648646391'

# Official Google Maps APK Dex Bytecode Activity Enum Specification
ACTIVITY_ENUM_MAP = {
    "IN_PASSENGER_VEHICLE": 1,
    "DRIVING": 1,
    "WALKING": 2,
    "CYCLING": 3,
    "FLYING": 5,
    "RUNNING": 6,
    "IN_BUS": 7,
    "IN_TRAIN": 8,
    "IN_SUBWAY": 9,      # Verified APK bytecode: 9 = IN_SUBWAY ("On subway" / "In subway")
    "IN_TRAM": 10,       # 10 = IN_TRAM ("On a tram")
    "IN_FERRY": 11,
    "MOTORCYCLING": 30
}

def ramer_douglas_peucker(pts: List[List[float]], epsilon: float = 0.00004) -> List[List[float]]:
    if not pts or len(pts) <= 2:
        return pts
    def pt_line_dist(pt, start, end):
        if start == end:
            return math.hypot(pt[0] - start[0], pt[1] - start[1])
        n = abs((end[1] - start[1])*pt[0] - (end[0] - start[0])*pt[1] + end[0]*start[1] - end[1]*start[0])
        d = math.hypot(end[1] - start[1], end[0] - start[0])
        return n / d if d > 0 else 0

    dmax = 0.0
    index = 0
    for i in range(1, len(pts) - 1):
        d = pt_line_dist(pts[i], pts[0], pts[-1])
        if d > dmax:
            index = i
            dmax = d
    if dmax > epsilon:
        rec1 = ramer_douglas_peucker(pts[:index+1], epsilon)
        rec2 = ramer_douglas_peucker(pts[index:], epsilon)
        res = rec1[:-1] + rec2
    else:
        res = [pts[0], pts[-1]]

    if len(res) > 35:
        step = max(1, len(res) // 30)
        res = res[::step][:30] + [res[-1]]
    return res

def encode_varint_64(val: int) -> bytes:
    if val < 0:
        val = (1 << 64) + val
    buf = bytearray()
    while val >= 0x80:
        buf.append((val & 0x7F) | 0x80)
        val >>= 7
    buf.append(val & 0x7F)
    return bytes(buf)

def encode_tag_varint(tag: int, val: int) -> bytes:
    return encode_varint_64((tag << 3) | 0) + encode_varint_64(val)

def encode_len(tag: int, val: bytes) -> bytes:
    return encode_varint_64((tag << 3) | 2) + encode_varint_64(len(val)) + val

def get_place_fprint_and_cell(place_id: str, name: str, addr: str, lat: float, lng: float) -> Tuple[int, int, int]:
    if place_id and place_id.startswith('ChIJ') and len(place_id) == 27 and not place_id.startswith('ChIJAAAAAAAAAAA'):
        raw_b64 = place_id[4:].replace('-', '+').replace('_', '/')
        pad = len(raw_b64) % 4
        if pad: raw_b64 += '=' * (4 - pad)
        try:
            b = base64.b64decode(raw_b64)
            if len(b) >= 17 and b[8] == 0x11:
                cid = struct.unpack('<Q', b[:8])[0]
                fp = struct.unpack('<Q', b[9:17])[0]
                if fp != 0 and cid != 0:
                    fp_signed = struct.unpack('<q', struct.pack('<Q', fp))[0]
                    return cid, fp, fp_signed
            elif len(b) >= 16:
                cid = struct.unpack('<Q', b[:8])[0]
                fp = struct.unpack('<Q', b[8:16])[0]
                if fp != 0 and cid != 0:
                    fp_signed = struct.unpack('<q', struct.pack('<Q', fp))[0]
                    return cid, fp, fp_signed
        except Exception:
            pass

    seed = f'{place_id}_{name}_{addr}_{lat:.6f}_{lng:.6f}'
    h = hashlib.sha256(seed.encode('utf-8')).digest()
    cid = struct.unpack('<Q', h[:8])[0] & 0xffffffffffffffff
    fp = struct.unpack('<Q', h[8:16])[0] & 0xffffffffffffffff
    if fp == 0: fp = 0x123456789abcdef0
    if cid == 0: cid = 0xfedcba9876543210
    fp_signed = struct.unpack('<q', struct.pack('<Q', fp))[0]
    return cid, fp, fp_signed

def build_myplaces_proto(fprint: int, cell_id: int, name: str, address: str, lat: float, lng: float) -> bytes:
    sub1 = encode_tag_varint(1, 3) + encode_tag_varint(2, fprint)
    lat_e6 = int(round(lat * 1e6))
    lng_e6 = int(round(lng * 1e6))
    sub4 = encode_tag_varint(1, lat_e6) + encode_tag_varint(2, lng_e6)
    
    ftid_str = f'0x{cell_id:016x}:0x{fprint:016x}'
    q_str = urllib.parse.quote_plus(f'{name}, {address}')
    url = f'http://maps.google.com/?q={q_str}&ftid={ftid_str}'
    
    tag6 = bytearray()
    tag6 += encode_len(1, sub1)
    tag6 += encode_len(2, address.encode('utf-8'))
    tag6 += encode_len(3, ftid_str.encode('utf-8'))
    tag6 += encode_len(4, sub4)
    tag6 += encode_tag_varint(5, 1758324769602)
    tag6 += encode_len(7, name.encode('utf-8'))
    tag6 += encode_len(6, url.encode('utf-8'))
    
    payload = bytearray()
    payload += encode_len(2, f'3:{fprint}'.encode('utf-8'))
    payload += encode_len(6, bytes(tag6))
    return bytes(payload)

def build_sync_proto(fprint_str: str, name: str, address: str) -> bytes:
    tag1 = encode_tag_varint(1, 3) + encode_len(3, fprint_str.encode('utf-8'))
    tag5 = encode_len(1, address.encode('utf-8'))
    tag6 = encode_tag_varint(1, 1675553544915)
    
    payload = bytearray()
    payload += encode_len(1, tag1)
    payload += encode_len(3, name.encode('utf-8'))
    payload += encode_len(5, tag5)
    payload += encode_len(6, tag6)
    return bytes(payload)

def build_places2_entry(fprint: int, name: str, address: str) -> bytes:
    rec = bytearray()
    rec += encode_tag_varint(2, fprint)
    rec += bytes.fromhex('190000000000000000')
    rec += bytes.fromhex('210000000000000000')
    rec += encode_len(5, name.encode('utf-8'))
    if address:
        rec += encode_len(6, address.encode('utf-8'))
    rec += encode_tag_varint(7, 49)
    rec += encode_tag_varint(8, 3)
    rec += encode_tag_varint(11, 10)
    return encode_len(1, bytes(rec))

def build_visit_proto(start_ts: int, end_ts: int, cell_id: int, fprint: int, lat: float, lng: float, segment_id: str, tz_offset_m: int = -240) -> bytes:
    lat_e7 = int(round(lat * 1e7))
    lng_e7 = int(round(lng * 1e7))
    
    feature_id_bytes = b'\x09' + struct.pack('<Q', fprint & 0xffffffffffffffff) + b'\x11' + struct.pack('<Q', cell_id & 0xffffffffffffffff)
    pt_bytes = b'\x0d' + struct.pack('<i', lat_e7) + b'\x15' + struct.pack('<i', lng_e7)
    
    cand = bytearray()
    cand += encode_len(1, feature_id_bytes)
    cand += b'\x10\x00' # semantic_type = 0 (POI)
    cand += b'\x1d\x00\x00\x80?' # score = 1.0
    cand += encode_len(5, pt_bytes)
    
    vseg = bytearray()
    vseg += b'\x08\x00'
    vseg += b'\x15\x00\x00\x80?'
    vseg += encode_len(4, bytes(cand))
    
    s_ts_bytes = b'\x08' + encode_varint_64(start_ts)
    e_ts_bytes = b'\x08' + encode_varint_64(end_ts)
    
    seg = bytearray()
    seg += encode_len(1, s_ts_bytes)
    seg += encode_len(2, e_ts_bytes)
    seg += encode_len(3, encode_len(1, bytes(vseg)))
    if segment_id:
        seg += encode_len(6, segment_id.encode('utf-8'))
    
    tz_bytes = encode_varint_64(tz_offset_m)
    seg += b'\x38' + tz_bytes
    seg += b'\x40' + tz_bytes
    seg += b'\x50\x01'
    return bytes(seg)

def build_raw_path_segment_proto(start_s: int, end_s: int, coords: list, seg_id: str) -> bytes:
    s_ts_bytes = b"\x08" + encode_varint_64(start_s)
    e_ts_bytes = b"\x08" + encode_varint_64(end_s)
    
    lats_bytes = bytearray()
    lngs_bytes = bytearray()
    time_deltas = bytearray()
    
    for pt in coords:
        lat_e7 = int(round(float(pt[0]) * 1e7))
        lng_e7 = int(round(float(pt[1]) * 1e7))
        lats_bytes.extend(struct.pack("<i", lat_e7))
        lngs_bytes.extend(struct.pack("<i", lng_e7))
        time_deltas.append(0x50)
        
    path_details = bytearray()
    path_details += encode_len(4, bytes(lats_bytes))
    path_details += encode_len(5, bytes(lngs_bytes))
    path_details += encode_len(6, bytes(time_deltas))
    
    tag3_body = encode_len(3, bytes(path_details))
    
    seg = bytearray()
    seg += encode_len(1, s_ts_bytes)
    seg += encode_len(2, e_ts_bytes)
    seg += encode_len(3, tag3_body)
    seg += encode_len(6, seg_id.encode("utf-8"))
    seg += b"\x50\x01"
    return bytes(seg)

def build_activity_proto_snapped(start_ts: int, end_ts: int, act_type_code: int, dist_m: float, segment_id: str, snapped_coords: list, s_lat: float, s_lng: float, e_lat: float, e_lng: float, tz_offset_m: int = -240) -> bytes:
    s_ts_bytes = b'\x08' + encode_varint_64(start_ts)
    e_ts_bytes = b'\x08' + encode_varint_64(end_ts)
    
    acand = b'\x08' + encode_varint_64(act_type_code) + b'\x15\x00\x00\x80?'
    
    dur = max(1, end_ts - start_ts)
    wp_list = []
    for idx, pt in enumerate(snapped_coords):
        frac = idx / float(max(1, len(snapped_coords) - 1))
        ts = int((start_ts + frac * dur) * 1000)
        wp_list.append({"lat": float(pt[0]), "lng": float(pt[1]), "ts": ts})
    
    wp_bytes = pe.encode_waypoint_list_proto(wp_list)

    act_details = bytearray()
    s_pt = b'\x0d' + struct.pack('<i', int(round(s_lat * 1e7))) + b'\x15' + struct.pack('<i', int(round(s_lng * 1e7)))
    e_pt = b'\x0d' + struct.pack('<i', int(round(e_lat * 1e7))) + b'\x15' + struct.pack('<i', int(round(e_lng * 1e7)))
    act_details += encode_len(1, s_pt)
    act_details += encode_len(2, e_pt)
    act_details += b'\x1d' + struct.pack('<f', float(dist_m))
    act_details += encode_len(4, wp_bytes)
    act_details += encode_len(6, acand)
    
    tag3_body = encode_len(2, bytes(act_details))
    
    seg = bytearray()
    seg += encode_len(1, s_ts_bytes)
    seg += encode_len(2, e_ts_bytes)
    seg += encode_len(3, tag3_body)
    if segment_id:
        seg += encode_len(6, segment_id.encode('utf-8'))
    
    tz_bytes = encode_varint_64(tz_offset_m)
    seg += b'\x38' + tz_bytes
    seg += b'\x40' + tz_bytes
    seg += b'\x50\x01'
    return bytes(seg)

def main():
    print("=================================================================")
    print("[*] COMPILING COMPLETE 11K-PLACES MASTER ODLH DATABASE")
    print("=================================================================")
    t0 = time.time()

    conn_v = sqlite3.connect(VIEWER_DB)
    c_v = conn_v.cursor()

    # 1. Compile 11,014 Unique Places Catalog
    c_v.execute('SELECT place_id, name, address, latitude, longitude, category, city FROM places;')
    all_places = c_v.fetchall()
    print(f"[1/5] Compiling {len(all_places):,} catalog places...")

    if os.path.exists(OUT_MYPLACES_DB): os.remove(OUT_MYPLACES_DB)
    if os.path.exists(OUT_SYNC_DB): os.remove(OUT_SYNC_DB)

    conn_mp = sqlite3.connect(OUT_MYPLACES_DB)
    c_mp = conn_mp.cursor()
    c_mp.execute('CREATE TABLE sync_item (corpus INTEGER, key_string TEXT, timestamp INTEGER, merge_key TEXT, feature_fprint INTEGER, latitude INTEGER, longitude INTEGER, is_local INTEGER, sync_item BLOB, PRIMARY KEY (corpus, key_string));')

    conn_gs = sqlite3.connect(OUT_SYNC_DB)
    c_gs = conn_gs.cursor()
    c_gs.execute('CREATE TABLE sync_item_data (corpus INTEGER, client_id TEXT, server_id TEXT, timestamp INTEGER, feature_fprint INTEGER, latitude_e6 INTEGER, longitude_e6 INTEGER, numerical_index INTEGER, string_index TEXT, sync_state INTEGER, item_proto BLOB, PRIMARY KEY (corpus, client_id));')

    places2_entries = []
    pid_to_fp = {}

    for pid, name, addr, lat, lng, cat, city in all_places:
        lat = float(lat or 0.0)
        lng = float(lng or 0.0)
        name = name or 'Location'
        addr = addr or ''
        cid, fp, fp_signed = get_place_fprint_and_cell(pid, name, addr, lat, lng)
        pid_to_fp[pid] = (cid, fp, fp_signed, name, addr, lat, lng)

        mp_blob = build_myplaces_proto(fp, cid, name, addr, lat, lng)
        lat_e7 = int(round(lat * 1e7))
        lng_e7 = int(round(lng * 1e7))
        for k_str in [f'3:{fp}', f'3:{fp_signed}']:
            c_mp.execute('''
            INSERT OR REPLACE INTO sync_item (corpus, key_string, timestamp, merge_key, feature_fprint, latitude, longitude, is_local, sync_item)
            VALUES (8, ?, 1758324769602, 0, ?, ?, ?, 0, ?);
            ''', (k_str, fp_signed, lat_e7, lng_e7, mp_blob))

        gs_blob = build_sync_proto(str(fp), name, addr)
        lat_e6 = int(round(lat * 1e6))
        lng_e6 = int(round(lng * 1e6))
        for c_id in [f'3:{fp}', f'3:{fp_signed}']:
            c_gs.execute('''
            INSERT OR REPLACE INTO sync_item_data (corpus, client_id, server_id, timestamp, feature_fprint, latitude_e6, longitude_e6, numerical_index, string_index, sync_state, item_proto)
            VALUES (11, ?, ?, 1675553544915, ?, ?, ?, 0, ?, 0, ?);
            ''', (c_id, c_id, fp_signed, lat_e6, lng_e6, name, gs_blob))

        places2_entries.append(build_places2_entry(fp, name, addr))

    conn_mp.commit()
    conn_mp.close()
    conn_gs.commit()
    conn_gs.close()

    with open(OUT_PLACES2_PATH, 'wb') as f:
        for entry in places2_entries:
            f.write(entry)
    print(f"  [✓] Places catalogs compiled ({len(places2_entries):,} entries).")

    # 2. Build pure semantic_segment_table schema
    print("[2/5] Creating pure semantic_segment_table schema with composite query indexes...")
    if os.path.exists(OUT_ODLH_DB):
        os.remove(OUT_ODLH_DB)

    conn_o = sqlite3.connect(OUT_ODLH_DB)
    c_o = conn_o.cursor()
    c_o.execute("""
    CREATE TABLE semantic_segment_table (
        _id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp_millis INTEGER NOT NULL,
        database_id INTEGER NOT NULL,
        origin_id INTEGER NOT NULL,
        segment_id TEXT NOT NULL,
        semantic_segment BLOB,
        obfuscated_gaia_id TEXT NOT NULL,
        shown_in_timeline INTEGER NOT NULL,
        is_finalized INTEGER NOT NULL,
        start_timestamp_seconds INTEGER NOT NULL,
        end_timestamp_seconds INTEGER NOT NULL,
        segment_type INTEGER NOT NULL,
        hierarchy_level INTEGER NOT NULL,
        fprint INTEGER
    );
    """)
    c_o.execute("CREATE INDEX index_semantic_segment_table_obfuscated_gaia_id ON semantic_segment_table (obfuscated_gaia_id);")
    c_o.execute("CREATE INDEX index_semantic_segment_table_segment_id ON semantic_segment_table (segment_id);")
    c_o.execute("CREATE INDEX index_semantic_segment_table_start_timestamp_seconds ON semantic_segment_table (start_timestamp_seconds);")
    c_o.execute("CREATE INDEX index_semantic_segment_table_type_fprint ON semantic_segment_table (segment_type, fprint);")
    c_o.execute("CREATE INDEX index_semantic_segment_table_type_start ON semantic_segment_table (segment_type, start_timestamp_seconds);")
    c_o.execute("CREATE INDEX index_semantic_segment_table_time_range ON semantic_segment_table (start_timestamp_seconds, end_timestamp_seconds);")

    # 3. Extract authentic segments from timeline_viewer.db
    print("[3/5] Compiling authentic segments with RDP decimation...")
    c_v.execute("""
    SELECT id, segment_type, activity_type, place_name, place_address, place_id,
           latitude, longitude, end_lat, end_lng, start_ts, end_ts, distance_meters, path_points_json
    FROM segments
    WHERE end_ts > start_ts
    ORDER BY start_ts ASC;
    """)
    all_segs = c_v.fetchall()

    insert_rows = []
    curr_origin = 100000

    for sid, stype, atype, pname, paddr, pid, lat, lng, elat, elng, sts, ets, dist_m, path_json in all_segs:
        sts = int(sts)
        ets = int(ets)
        if ets <= sts:
            continue

        seg_id = f"qg_seg_{sid}"

        if stype == 'visit':
            pname = pname or "Location"
            paddr = paddr or ""
            lat = float(lat or 0.0)
            lng = float(lng or 0.0)
            pid = pid or f"place_{sid}"
            if pid in pid_to_fp:
                cid, fp, fp_signed, _, _, _, _ = pid_to_fp[pid]
            else:
                cid, fp, fp_signed = get_place_fprint_and_cell(pid, pname, paddr, lat, lng)

            # Determine timezone offset (EST -300 vs EDT -240)
            dt_check = datetime.datetime.fromtimestamp(sts, datetime.timezone.utc)
            tz_offset_m = -240 if (dt_check.month > 3 and dt_check.month < 11) else -300
            tz = datetime.timezone(datetime.timedelta(minutes=tz_offset_m))

            st_dt = datetime.datetime.fromtimestamp(sts, tz)
            et_dt = datetime.datetime.fromtimestamp(ets, tz)

            # Split visit slices across local midnights
            slices = []
            curr_dt = st_dt
            while True:
                next_midnight = datetime.datetime(curr_dt.year, curr_dt.month, curr_dt.day, tzinfo=tz) + datetime.timedelta(days=1)
                if next_midnight >= et_dt:
                    slices.append((int(curr_dt.timestamp()), int(et_dt.timestamp())))
                    break
                else:
                    slices.append((int(curr_dt.timestamp()), int(next_midnight.timestamp())))
                    curr_dt = next_midnight

            for slice_idx, (slice_sts, slice_ets) in enumerate(slices):
                if slice_ets <= slice_sts: continue
                slice_seg_id = seg_id if len(slices) == 1 else f"{seg_id}_d{slice_idx+1}"
                blob_vis = build_visit_proto(slice_sts, slice_ets, cid, fp, lat, lng, slice_seg_id, tz_offset_m=tz_offset_m)
                insert_rows.append((
                    None, slice_sts * 1000, 1787254103124001536, curr_origin, slice_seg_id, blob_vis,
                    GAIA_ID, 1, 1, slice_sts, slice_ets, 1, 0, fp_signed
                ))
                curr_origin += 1

        elif stype == 'activity':
            act_code = ACTIVITY_ENUM_MAP.get((atype or 'WALKING').upper(), 2)
            lat = float(lat or 0.0)
            lng = float(lng or 0.0)
            elat = float(elat or lat)
            elng = float(elng or lng)
            dist_m = float(dist_m or 0.0)

            try:
                raw_coords = json.loads(path_json) if path_json else [[lat, lng], [elat, elng]]
            except Exception:
                raw_coords = [[lat, lng], [elat, elng]]

            # Refined RDP decimation preserving road turns while capping max points to 50
            coords = ramer_douglas_peucker(raw_coords, epsilon=0.000008)
            if len(coords) > 50:
                coords = ramer_douglas_peucker(raw_coords, epsilon=0.00002)
            if len(coords) < 2:
                coords = [[lat, lng], [elat, elng]]
            else:
                coords[0] = [lat, lng]
                coords[-1] = [elat, elng]

            # ActivitySegment (type = 2) - Native single entry with embedded waypoints
            blob_act = build_activity_proto_snapped(sts, ets, act_code, dist_m, seg_id, coords, lat, lng, elat, elng, tz_offset_m=-240)
            insert_rows.append((
                None, sts * 1000, 1787254103124001536, curr_origin, seg_id, blob_act,
                GAIA_ID, 1, 1, sts, ets, 2, 0, None
            ))
            curr_origin += 1

    print(f"[4/5] Inserting {len(insert_rows):,} rows into pure semantic_segment_table...")
    c_o.executemany("""
    INSERT INTO semantic_segment_table
    (_id, timestamp_millis, database_id, origin_id, segment_id, semantic_segment, obfuscated_gaia_id, shown_in_timeline, is_finalized, start_timestamp_seconds, end_timestamp_seconds, segment_type, hierarchy_level, fprint)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, insert_rows)
    conn_o.commit()

    c_o.execute("VACUUM;")
    c_o.execute("PRAGMA optimize;")

    # 5. Build aux-odlh-storage.db
    print("[5/5] Generating aux-odlh-storage.db...")
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

    c_o.execute("SELECT COUNT(*), COUNT(DISTINCT fprint) FROM semantic_segment_table WHERE segment_type = 1;")
    vis_count, distinct_places = c_o.fetchone()

    c_o.execute('PRAGMA page_size;')
    ps = c_o.fetchone()[0]
    c_o.execute('PRAGMA page_count;')
    pc = c_o.fetchone()[0]
    db_size_mb = ps * pc / 1024 / 1024

    print(f"  [✓] Master ODLH Compiled in {time.time() - t0:.1f}s!")
    print(f"      Total rows: {len(aux_rows):,} | Total DB Size: {db_size_mb:.2f} MB")
    print(f"      Visits: {vis_count:,} | Distinct Places: {distinct_places:,}")

    conn_o.close()
    conn_v.close()

if __name__ == '__main__':
    main()
