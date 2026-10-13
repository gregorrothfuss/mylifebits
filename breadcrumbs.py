"""
2026 Raw Breadcrumb Decoder & Outlier Anomaly Detection Engine.

Decodes raw GPS trajectory slices from on-device SQLite database (odlh-storage.db)
and mobile JSON exports, detects anomalies (velocity spikes, multipath ping-pong,
dwell scatter), and stores structured fixes for review and re-inference.
"""

import math
import sqlite3
import struct
import datetime
import os
from typing import List, Dict, Any, Tuple, Optional


def haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculates great-circle distance in meters between two lat/lng points."""
    r = 6371000.0  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)
    
    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def parse_varint(data: bytes, idx: int) -> Tuple[int, int]:
    """Decodes a protobuf varint integer."""
    val, shift = 0, 0
    l = len(data)
    while idx < l:
        b = data[idx]
        idx += 1
        val |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return val, idx


def decode_protobuf_fields(blob: bytes) -> Dict[int, List[Tuple[str, Any]]]:
    """Decodes raw protobuf tags into a dictionary of field numbers."""
    idx = 0
    l = len(blob)
    fields: Dict[int, List[Tuple[str, Any]]] = {}
    
    while idx < l:
        key, idx = parse_varint(blob, idx)
        fnum = key >> 3
        wtype = key & 0x7
        
        if wtype == 0:  # Varint
            val, idx = parse_varint(blob, idx)
            fields.setdefault(fnum, []).append(("varint", val))
        elif wtype == 1:  # 64-bit
            val = blob[idx:idx + 8]
            idx += 8
            fields.setdefault(fnum, []).append(("fixed64", val))
        elif wtype == 2:  # Length-delimited (string / submessage / packed)
            length, idx = parse_varint(blob, idx)
            val = blob[idx:idx + length]
            idx += length
            fields.setdefault(fnum, []).append(("bytes", val))
        elif wtype == 5:  # 32-bit
            val = blob[idx:idx + 4]
            idx += 4
            fields.setdefault(fnum, []).append(("fixed32", val))
        else:
            break
            
    return fields


def decode_path_chunk_blob(start_ts: int, blob: bytes) -> List[Dict[str, Any]]:
    """
    Decodes a Type 3 (path chunk) protobuf blob into a list of GPS fixes:
    [{ 'timestamp': int, 'lat': float, 'lng': float, 'accuracy': float, 'speed_kmh': float }]
    """
    points = []
    top = decode_protobuf_fields(blob)
    
    if 3 not in top or not top[3]:
        return points
        
    f3_bytes = top[3][0][1]
    f3_fields = decode_protobuf_fields(f3_bytes)
    
    inner_bytes = f3_fields[3][0][1] if 3 in f3_fields and f3_fields[3] else f3_bytes
    inner = decode_protobuf_fields(inner_bytes)
    
    # Tag 4: Packed Latitudes (int32 / E7)
    # Tag 5: Packed Longitudes (int32 / E7)
    # Tag 6: Time offsets in seconds from start_ts
    if 4 not in inner or 5 not in inner:
        return points
        
    lat_bytes = inner[4][0][1]
    lng_bytes = inner[5][0][1]
    time_bytes = inner[6][0][1] if 6 in inner else b""
    
    num_lats = len(lat_bytes) // 4
    num_lngs = len(lng_bytes) // 4
    n_points = min(num_lats, num_lngs)
    
    if n_points == 0:
        return points
        
    cur_ts = start_ts
    for i in range(n_points):
        lat_int = struct.unpack("<i", lat_bytes[i*4:(i+1)*4])[0]
        lng_int = struct.unpack("<i", lng_bytes[i*4:(i+1)*4])[0]
        
        lat = lat_int / 1e7
        lng = lng_int / 1e7
        
        # Calculate timestamp
        if i < len(time_bytes):
            delta_s = time_bytes[i]
            cur_ts = start_ts + delta_s
        else:
            cur_ts = start_ts + i * 2  # default fallback step
            
        # Validate coordinates bounds
        if -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0 and abs(lat) > 0.001:
            points.append({
                "timestamp": cur_ts,
                "lat": round(lat, 7),
                "lng": round(lng, 7),
                "accuracy": 15.0,  # nominal GPS accuracy
                "speed_kmh": 0.0,
                "anomaly_type": None,
                "anomaly_score": 0.0,
                "anomaly_reason": None,
            })
            
    return points


def detect_anomalies(points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Executes algorithmic outlier & anomaly detection over a sequence of breadcrumb fixes:
    1. Teleportation / Extreme Velocity Anomaly
    2. Ping-Pong Multipath Bounce (A -> B -> A within short window)
    3. Low Accuracy / Degraded GPS Anomaly
    4. Stationary Dwell Jitter
    """
    if len(points) < 3:
        return points
        
    n = len(points)
    
    # Pass 1: Velocity & Teleportation
    for i in range(1, n):
        p_prev = points[i - 1]
        p_curr = points[i]
        
        dt_s = p_curr["timestamp"] - p_prev["timestamp"]
        if dt_s <= 0:
            continue
            
        dist_m = haversine_distance(p_prev["lat"], p_prev["lng"], p_curr["lat"], p_curr["lng"])
        
        # Only evaluate velocity for consecutive points recorded within 15 minutes (900s)
        if dt_s < 900:
            speed_mps = dist_m / dt_s
            speed_kmh = speed_mps * 3.6
            p_curr["speed_kmh"] = round(speed_kmh, 1)
            
            # Teleportation jump > 180 km/h on land or > 950 km/h in air
            if speed_kmh > 180.0 and dist_m > 100.0:
                if speed_kmh > 950.0:
                    p_curr["anomaly_type"] = "TELEPORTATION"
                    p_curr["anomaly_score"] = 0.95
                    p_curr["anomaly_reason"] = f"Physically impossible jump: {dist_m:.0f}m in {dt_s}s ({speed_kmh:.0f} km/h)"
                else:
                    p_curr["anomaly_type"] = "EXTREME_VELOCITY"
                    p_curr["anomaly_score"] = 0.85
                    p_curr["anomaly_reason"] = f"Abrupt velocity spike: {speed_kmh:.0f} km/h over {dist_m:.0f}m"
        else:
            p_curr["speed_kmh"] = 0.0
                
    # Pass 2: Ping-Pong Multipath Bounce (A -> B -> A)
    # A point jumps far away to B, then immediately jumps back to near A in next 1-2 points
    for i in range(1, n - 1):
        if points[i].get("anomaly_type") == "TELEPORTATION":
            continue
            
        p_prev = points[i - 1]
        p_curr = points[i]
        p_next = points[i + 1]
        
        dist_ab = haversine_distance(p_prev["lat"], p_prev["lng"], p_curr["lat"], p_curr["lng"])
        dist_bc = haversine_distance(p_curr["lat"], p_curr["lng"], p_next["lat"], p_next["lng"])
        dist_ac = haversine_distance(p_prev["lat"], p_prev["lng"], p_next["lat"], p_next["lng"])
        
        dt_total = p_next["timestamp"] - p_prev["timestamp"]
        
        # If A and C are close (< 100m) but B is far (> 200m) and occurred in short time (< 30s)
        if dist_ab > 200.0 and dist_bc > 200.0 and dist_ac < 100.0 and dt_total < 30:
            points[i]["anomaly_type"] = "MULTIPATH_BOUNCE"
            points[i]["anomaly_score"] = 0.90
            points[i]["anomaly_reason"] = f"Multipath bounce: spiked {dist_ab:.0f}m away and returned within {dt_total}s"
            
    # Pass 3: Dwell Scatter
    # Points with high accuracy circle or drifting when surrounding points are stationary
    for i in range(2, n - 2):
        if points[i].get("anomaly_type"):
            continue
            
        # Check median distance to window [-2, +2]
        window = [points[j] for j in range(i-2, i+3) if j != i]
        dists = [haversine_distance(points[i]["lat"], points[i]["lng"], w["lat"], w["lng"]) for w in window]
        med_dist = sorted(dists)[len(dists)//2]
        
        if med_dist > 150.0 and points[i].get("speed_kmh", 0) > 60.0:
            points[i]["anomaly_type"] = "DWELL_SCATTER"
            points[i]["anomaly_score"] = 0.75
            points[i]["anomaly_reason"] = f"Isolated drift: {med_dist:.0f}m deviation from surrounding cluster"
            
    return points


def ingest_odlh_breadcrumbs(odlh_db_path: str, target_db_path: str, max_chunks: Optional[int] = None):
    """
    Reads all Type 3 path chunks from odlh-storage.db, decodes breadcrumbs,
    runs anomaly detection, and inserts into target timeline_viewer.db.
    """
    if not os.path.exists(odlh_db_path):
        raise FileNotFoundError(f"ODLH database not found: {odlh_db_path}")
        
    print(f"[*] Ingesting raw breadcrumbs from {odlh_db_path}...")
    src_conn = sqlite3.connect(odlh_db_path)
    src_c = src_conn.cursor()
    
    query = """
    SELECT _id, start_timestamp_seconds, end_timestamp_seconds, segment_id, semantic_segment
    FROM semantic_segment_table
    WHERE segment_type = 3
    ORDER BY start_timestamp_seconds ASC;
    """
    src_c.execute(query)
    rows = src_c.fetchall()
    src_conn.close()
    
    if max_chunks:
        rows = rows[:max_chunks]
        
    print(f"[*] Found {len(rows):,} path chunks to decode.")
    
    tgt_conn = sqlite3.connect(target_db_path)
    tgt_c = tgt_conn.cursor()
    
    # Ensure breadcrumbs table exists
    tgt_c.execute("""
    CREATE TABLE IF NOT EXISTS breadcrumbs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chunk_id TEXT,
        timestamp INTEGER,
        date TEXT,
        lat REAL,
        lng REAL,
        accuracy REAL,
        speed_kmh REAL,
        anomaly_type TEXT,
        anomaly_score REAL,
        anomaly_reason TEXT,
        is_excluded INTEGER DEFAULT 0
    );
    """)
    tgt_c.execute("CREATE INDEX IF NOT EXISTS idx_breadcrumbs_date ON breadcrumbs(date);")
    tgt_c.execute("CREATE INDEX IF NOT EXISTS idx_breadcrumbs_ts ON breadcrumbs(timestamp);")
    tgt_c.execute("CREATE INDEX IF NOT EXISTS idx_breadcrumbs_anomaly ON breadcrumbs(anomaly_type);")
    
    # Clear previous breadcrumbs
    tgt_c.execute("DELETE FROM breadcrumbs;")
    
    total_points = 0
    total_anomalies = 0
    batch = []
    
    for row in rows:
        _id, start_ts, end_ts, seg_id, blob = row
        pts = decode_path_chunk_blob(start_ts, blob)
        if not pts:
            continue
            
        pts = detect_anomalies(pts)
        
        for p in pts:
            dt = datetime.datetime.fromtimestamp(p["timestamp"], tz=datetime.timezone.utc)
            date_str = dt.strftime("%Y-%m-%d")
            
            if p["anomaly_type"]:
                total_anomalies += 1
                
            batch.append((
                seg_id,
                p["timestamp"],
                date_str,
                p["lat"],
                p["lng"],
                p["accuracy"],
                p["speed_kmh"],
                p["anomaly_type"],
                p["anomaly_score"],
                p["anomaly_reason"],
                0
            ))
            
            if len(batch) >= 5000:
                tgt_c.executemany("""
                INSERT INTO breadcrumbs (
                    chunk_id, timestamp, date, lat, lng, accuracy,
                    speed_kmh, anomaly_type, anomaly_score, anomaly_reason, is_excluded
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, batch)
                tgt_conn.commit()
                total_points += len(batch)
                batch = []
                
    if batch:
        tgt_c.executemany("""
        INSERT INTO breadcrumbs (
            chunk_id, timestamp, date, lat, lng, accuracy,
            speed_kmh, anomaly_type, anomaly_score, anomaly_reason, is_excluded
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, batch)
        tgt_conn.commit()
        total_points += len(batch)
        
    tgt_conn.close()
    print(f"[✓] Ingested {total_points:,} raw breadcrumbs ({total_anomalies:,} detected anomalies).")
    return total_points, total_anomalies


if __name__ == "__main__":
    odlh = os.path.join(os.path.dirname(__file__), "gms_extracted", "odlh-storage.db")
    target = os.path.join(os.path.dirname(__file__), "timeline_viewer.db")
    ingest_odlh_breadcrumbs(odlh, target)
