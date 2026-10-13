"""
Place Catalog & Segment Deduplication Engine.
Merges duplicate places sharing identical name & coordinates, re-links segments, and cleans orphan records.
"""

import sqlite3
import os
import sys

DEFAULT_DB_PATH = "timeline_viewer.db"

def deduplicate_places_and_segments(db_path: str = DEFAULT_DB_PATH):
    print("🚀 Starting Places Catalog Deduplication...")
    conn = sqlite3.connect(db_path, timeout=60.0)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 1. Deduplicate places sharing same name and approximate coordinates (within ~50m)
    c.execute("""
    SELECT name, round(latitude, 3) as lat_r, round(longitude, 3) as lng_r, count(*) as cnt, group_concat(place_id) as pids
    FROM places
    WHERE name IS NOT NULL AND name != '' AND name != 'Saved Location'
    GROUP BY name, round(latitude, 3), round(longitude, 3)
    HAVING count(*) > 1;
    """)
    dup_groups = [dict(r) for r in c.fetchall()]

    merged_count = 0
    for g in dup_groups:
        pid_list = g['pids'].split(',')
        # Pick best canonical place_id: prefer real ChIJ ID over synthetic ChIJAAAA...
        canonical_pid = pid_list[0]
        for p in pid_list:
            if 'AAAAAAAA' not in p and len(p) > 15:
                canonical_pid = p
                break

        other_pids = [p for p in pid_list if p != canonical_pid]
        for op in other_pids:
            # Re-link segments to canonical place_id
            c.execute("UPDATE segments SET place_id = ? WHERE place_id = ?;", (canonical_pid, op))
            # Delete duplicate place
            c.execute("DELETE FROM places WHERE place_id = ?;", (op,))
            merged_count += 1

    # 2. Recalculate true visit_count for all places
    c.execute("""
    UPDATE places
    SET visit_count = (
        SELECT count(*)
        FROM segments s
        WHERE s.place_id = places.place_id
    );
    """)

    # 3. Clean up exact duplicate flight airport insertions (if applied multiple times on same flight)
    c.execute("""
    DELETE FROM segments
    WHERE id NOT IN (
        SELECT min(id)
        FROM segments
        GROUP BY date, start_ts, end_ts, place_name, segment_type
    );
    """)
    deleted_dup_segs = c.rowcount

    conn.commit()
    conn.close()

    print(f"[✓] Successfully merged {merged_count} duplicate places into canonical records.")
    print(f"[✓] Cleaned {deleted_dup_segs} duplicate time-overlapping segments.")
    return {"merged_places": merged_count, "deleted_dup_segments": deleted_dup_segs}

if __name__ == "__main__":
    deduplicate_places_and_segments()
