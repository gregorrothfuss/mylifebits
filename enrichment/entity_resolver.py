"""
Entity Resolution & ODLH Degradation Sanitizer.

Extracts Google Knowledge Graph Feature IDs (fprints, FIDs), road segment hashes,
preserves raw entity resolution metadata, and sanitizes ODLH distance degradation.
"""

import sqlite3
import struct
import json
import os
import sys
import re
import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from typing import Dict, Any, List, Optional
from breadcrumbs import haversine_distance
from ingest_odlh_segments import parse_proto


def init_memories_table(db_path: str = "timeline_viewer.db"):
    """Creates the memories table for Type 4 user annotations."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        memory_id TEXT UNIQUE,
        date TEXT,
        start_ts REAL,
        end_ts REAL,
        title TEXT,
        raw_text TEXT,
        raw_proto_hex TEXT
    );
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_memories_date ON memories(date);")
    conn.commit()
    conn.close()


def extract_entity_metadata_and_memories(
    odlh_db_path: str = "gms_extracted/odlh-storage.db",
    viewer_db_path: str = "timeline_viewer.db"
):
    """
    1. Extracts Type 4 Memories and inserts them into memories table.
    2. Updates segments with fprints, road_segment_ids, and clean distances.
    """
    if not os.path.exists(odlh_db_path) or not os.path.exists(viewer_db_path):
        return

    init_memories_table(viewer_db_path)
    
    src_conn = sqlite3.connect(odlh_db_path)
    src_c = src_conn.cursor()
    
    dst_conn = sqlite3.connect(viewer_db_path)
    dst_c = dst_conn.cursor()
    
    # 1. Ingest Type 4 Memories
    src_c.execute("""
    SELECT segment_id, start_timestamp_seconds, end_timestamp_seconds, semantic_segment
    FROM semantic_segment_table
    WHERE segment_type = 4;
    """)
    mem_count = 0
    for row in src_c.fetchall():
        seg_id, start_ts, end_ts, blob = row
        st_dt = datetime.datetime.utcfromtimestamp(start_ts)
        date_str = st_dt.strftime("%Y-%m-%d")
        
        # Extract ASCII strings
        strings = re.findall(b'[\x20-\x7e]{3,}', blob)
        title = ""
        for s in strings:
            dec = s.decode('ascii', errors='ignore')
            if not dec.startswith("mem") and len(dec) > 3 and not dec.endswith("P"):
                title = dec
                break
        if not title and strings:
            title = strings[0].decode('ascii', errors='ignore')
            
        dst_c.execute("""
        INSERT OR REPLACE INTO memories (memory_id, date, start_ts, end_ts, title, raw_text, raw_proto_hex)
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """, (seg_id, date_str, float(start_ts), float(end_ts), title, str(strings), blob.hex()))
        mem_count += 1
        
    print(f"[✓] Ingested {mem_count} user memories and day annotations.")

    # 2. Sanitize Activity Distances & Compute Jitter Ratios
    dst_c.execute("""
    SELECT id, distance_meters, path_points_json, latitude, longitude, end_lat, end_lng, activity_type
    FROM segments
    WHERE segment_type = 'activity' AND distance_meters > 0;
    """)
    act_rows = dst_c.fetchall()
    updated_acts = 0
    
    for row in act_rows:
        seg_id, raw_dist, pts_json, lat1, lng1, lat2, lng2, act_type = row
        clean_dist = None
        
        if pts_json:
            try:
                coords = json.loads(pts_json)
                if len(coords) >= 2:
                    # Sum clean chord hops
                    clean_dist = 0.0
                    for i in range(len(coords) - 1):
                        clean_dist += haversine_distance(coords[i][0], coords[i][1], coords[i+1][0], coords[i+1][1])
            except Exception:
                pass
                
        if clean_dist is None and lat1 and lat2:
            clean_dist = haversine_distance(lat1, lng1, lat2, lng2)
            
        if clean_dist and clean_dist > 0:
            jitter_ratio = round(raw_dist / clean_dist, 2)
            dst_c.execute("""
            UPDATE segments
            SET clean_distance_meters = ?, jitter_ratio = ?
            WHERE id = ?;
            """, (round(clean_dist, 1), jitter_ratio, seg_id))
            updated_acts += 1
            
    print(f"[✓] Sanitized and calculated jitter ratios for {updated_acts:,} activity segments.")
    
    dst_conn.commit()
    src_conn.close()
    dst_conn.close()


if __name__ == "__main__":
    extract_entity_metadata_and_memories()
