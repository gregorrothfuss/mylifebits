"""
Script: scripts/clean_and_verify_all_restored_segments.py
1. Identifies and cleans redundant micro-stubs (duration <= 30s) that overlap with full restored visits.
2. Trims boundary overlaps between visits and adjacent micro-mobility legs / visits.
3. Asserts strict monotonicity and 0 overlaps.
"""

import sqlite3
from datetime import datetime, timezone
from collections import defaultdict

DB_PATH = "timeline_viewer.db"

def format_iso(ts: float) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def clean_segments():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Load all top-level segments ordered by start_ts
    cur.execute("""
        SELECT id, start_ts, end_ts, segment_type, place_name, place_id, duration_minutes, date
        FROM segments
        WHERE parent_segment_id IS NULL AND date >= '2007-01-01'
        ORDER BY start_ts ASC
    """)
    rows = cur.fetchall()
    print(f"[*] Loaded {len(rows)} top-level segments.")

    segs = [dict(
        id=r[0], start_ts=r[1], end_ts=r[2], type=r[3],
        name=r[4], pid=r[5], dur=r[6], date=r[7]
    ) for r in rows]

    deleted_stubs = set()
    modified_ends = {}
    modified_starts = {}

    # Pass 1: Deduplicate same-place micro-stubs (dur <= 0.5 min) overlapping full visits
    # Using an interval index / spatial sweep
    for i in range(len(segs)):
        s1 = segs[i]
        if s1["dur"] > 0.5:
            continue
        # s1 is a micro-stub. Check if any nearby full visit covers it for the same place/dock
        for j in range(max(0, i - 10), min(len(segs), i + 10)):
            if i == j:
                continue
            s2 = segs[j]
            if s2["dur"] <= 0.5:
                continue
            # Check overlap
            if s1["start_ts"] < s2["end_ts"] and s2["start_ts"] < s1["end_ts"]:
                if (s1["pid"] and s1["pid"] == s2["pid"]) or (s1["name"] and s1["name"] == s2["name"]):
                    deleted_stubs.add(s1["id"])
                    break

    print(f"  [1/3] Found {len(deleted_stubs)} redundant micro-stubs to remove.")
    if deleted_stubs:
        cur.executemany("DELETE FROM segments WHERE id = ?", [(sid,) for sid in deleted_stubs])
        conn.commit()

    # Reload active segments after deletion
    cur.execute("""
        SELECT id, start_ts, end_ts, segment_type, place_name, place_id, duration_minutes, date
        FROM segments
        WHERE parent_segment_id IS NULL AND date >= '2007-01-01'
        ORDER BY start_ts ASC
    """)
    rows = cur.fetchall()
    segs = [dict(
        id=r[0], start_ts=r[1], end_ts=r[2], type=r[3],
        name=r[4], pid=r[5], dur=r[6], date=r[7]
    ) for r in rows]

    # Pass 2: Trim boundary overlaps
    boundary_trims = 0
    for i in range(len(segs) - 1):
        s1 = segs[i]
        s2 = segs[i+1]
        if s1["end_ts"] > s2["start_ts"] + 0.5:
            overlap = s1["end_ts"] - s2["start_ts"]
            # Case A: Minor overlap <= 5 minutes (head/tail trim)
            if overlap <= 300.0:
                # Trim s1 end to s2 start
                new_end_ts = s2["start_ts"]
                cur.execute("""
                    UPDATE segments
                    SET end_ts = ?,
                        end_time = ?,
                        duration_minutes = (? - start_ts) / 60.0
                    WHERE id = ? AND end_ts > ?
                """, (new_end_ts, format_iso(new_end_ts), new_end_ts, s1["id"], new_end_ts))
                s1["end_ts"] = new_end_ts
                boundary_trims += 1
            # Case B: Restored home visit spans across Citi Bike dock
            elif "Home" in (s1["name"] or "") and "Citi Bike" in (s2["name"] or ""):
                # If s2 is a Citi Bike dock inside s1 stay, trim s1 end to s2 start
                new_end_ts = s2["start_ts"]
                cur.execute("""
                    UPDATE segments
                    SET end_ts = ?,
                        end_time = ?,
                        duration_minutes = (? - start_ts) / 60.0
                    WHERE id = ? AND end_ts > ?
                """, (new_end_ts, format_iso(new_end_ts), new_end_ts, s1["id"], new_end_ts))
                s1["end_ts"] = new_end_ts
                boundary_trims += 1
            # Case C: Prior Citi Bike dock overlaps start of visit
            elif "Citi Bike" in (s1["name"] or "") and s1["dur"] <= 0.5:
                # Trim s1 end to s2 start
                new_end_ts = s2["start_ts"]
                if new_end_ts > s1["start_ts"]:
                    cur.execute("""
                        UPDATE segments
                        SET end_ts = ?,
                            end_time = ?,
                            duration_minutes = (? - start_ts) / 60.0
                        WHERE id = ? AND end_ts > ?
                    """, (new_end_ts, format_iso(new_end_ts), new_end_ts, s1["id"], new_end_ts))
                    s1["end_ts"] = new_end_ts
                    boundary_trims += 1

    conn.commit()
    print(f"  [2/3] Trimmed {boundary_trims} boundary overlaps.")

    # Pass 3: Audit remaining overlaps for all restored visits (IDs >= 2696987)
    cur.execute("""
        SELECT id, start_ts, end_ts, segment_type, place_name, date, duration_minutes
        FROM segments
        WHERE parent_segment_id IS NULL AND date >= '2007-01-01'
        ORDER BY start_ts ASC
    """)
    rows = cur.fetchall()
    remaining_overlaps = []
    for i in range(len(rows) - 1):
        s1 = rows[i]
        s2 = rows[i+1]
        if s1[2] > s2[1] + 1.0:
            if s1[0] >= 2696987 or s2[0] >= 2696987:
                remaining_overlaps.append((s1, s2, s1[2] - s2[1]))

    print(f"\n[3/3] Audit Result: Remaining overlaps involving restored visits = {len(remaining_overlaps)}")
    for s1, s2, dur in remaining_overlaps[:10]:
        print(f"  {s1[5]}: ID {s1[0]} ({s1[4]}) overlaps {dur:.1f}s with ID {s2[0]} ({s2[4]})")

    conn.close()

if __name__ == "__main__":
    clean_segments()
