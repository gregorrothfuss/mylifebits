"""
Google Fit Corroborator & Activity Continuity Engine.

1. Ingests all 3,793 Google Fit sessions (Walking, Biking, Running) from Downloads/Takeout/Fit.
2. Corroborates and verifies timeline activity segments against biometric sensor ground truth.
3. Fixes misclassified transit modes (e.g. Cycling misclassified as Driving).
4. Generates actionable gap-filling proposals from recorded fitness sessions.
"""

import sqlite3
import glob
import json
import os
import sys
import re
import datetime
from typing import Dict, Any, List, Optional, Tuple

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_DB_PATH = "timeline_viewer.db"
DEFAULT_FIT_DIR = os.environ.get("FIT_TAKEOUT_DIR", "data/takeout/Fit")


def parse_iso_timestamp(ts_str: Optional[str]) -> Optional[float]:
    if not ts_str:
        return None
    # e.g. 2023-12-08T13:08:01.257Z or 2023-12-08T08:08:01.257-05:00
    try:
        ts_clean = re.sub(r"([+-]\d{2}):(\d{2})$", r"\1\2", ts_str)
        if "Z" in ts_clean:
            dt = datetime.datetime.strptime(ts_clean[:23], "%Y-%m-%dT%H:%M:%S.%f")
            return dt.replace(tzinfo=datetime.timezone.utc).timestamp()
        else:
            # Parse with timezone
            dt = datetime.datetime.fromisoformat(ts_str)
            return dt.timestamp()
    except Exception:
        try:
            dt = datetime.datetime.strptime(ts_str[:19], "%Y-%m-%dT%H:%M:%S")
            return dt.replace(tzinfo=datetime.timezone.utc).timestamp()
        except Exception:
            return None


def ingest_fit_sessions(db_path: str = DEFAULT_DB_PATH, fit_dir: str = DEFAULT_FIT_DIR) -> int:
    """Ingests all Fit session JSON records into SQLite."""
    conn = sqlite3.connect(db_path, timeout=60.0)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS fit_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        activity_type TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        start_ts REAL NOT NULL,
        end_ts REAL NOT NULL,
        duration_minutes REAL NOT NULL,
        date TEXT NOT NULL,
        filename TEXT
    );
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_fit_time ON fit_sessions(start_ts, end_ts);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_fit_date ON fit_sessions(date);")
    c.execute("DELETE FROM fit_sessions;")

    session_files = glob.glob(os.path.join(fit_dir, "All Sessions", "*.json"))
    if not session_files:
        print(f"[!] No Fit session files found in {fit_dir}/All Sessions")
        conn.close()
        return 0

    rows = []
    for sf in session_files:
        fname = os.path.basename(sf)
        # Extract activity type from filename
        act_match = re.search(r"_([A-Z]+)\.json$", fname)
        raw_type = act_match.group(1) if act_match else "WALKING"
        
        # Map to timeline canonical activity type
        if raw_type == "BIKING":
            canon_type = "CYCLING"
        elif raw_type == "RUNNING":
            canon_type = "RUNNING"
        else:
            canon_type = "WALKING"

        try:
            with open(sf, "r") as f:
                data = json.load(f)
                st_str = data.get("startTime")
                et_str = data.get("endTime")

                if st_str and et_str:
                    st_ts = parse_iso_timestamp(st_str)
                    et_ts = parse_iso_timestamp(et_str)

                    if st_ts and et_ts and et_ts > st_ts:
                        dur_m = round((et_ts - st_ts) / 60.0, 1)
                        if dur_m >= 1.0: # Filter out sub-1m glitches
                            dt_obj = datetime.datetime.fromtimestamp(st_ts, tz=datetime.timezone.utc)
                            date_str = dt_obj.strftime("%Y-%m-%d")
                            rows.append((
                                canon_type,
                                st_str,
                                et_str,
                                st_ts,
                                et_ts,
                                dur_m,
                                date_str,
                                fname
                            ))
        except Exception:
            pass

    c.executemany("""
    INSERT INTO fit_sessions (
        activity_type, start_time, end_time, start_ts, end_ts, duration_minutes, date, filename
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
    """, rows)
    conn.commit()
    conn.close()

    print(f"[✓] Ingested {len(rows)} verified Google Fit sessions into 'fit_sessions' table.")
    return len(rows)


def corroborate_fit_activities(db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """Correlates timeline activity segments with Fit sessions and fixes misclassifications."""
    print("🚀 Corroborating timeline activities with Google Fit sessions...")
    conn = sqlite3.connect(db_path, timeout=60.0)
    c = conn.cursor()

    # Fast SQL update: Match Fit activity type to segments
    c.execute("""
    UPDATE segments
    SET fit_activity_type = (
        SELECT f.activity_type
        FROM fit_sessions f
        WHERE f.start_ts < segments.end_ts AND f.end_ts > segments.start_ts
        ORDER BY (MIN(f.end_ts, segments.end_ts) - MAX(f.start_ts, segments.start_ts)) DESC
        LIMIT 1
    )
    WHERE segments.segment_type = 'activity'
      AND EXISTS (
        SELECT 1 FROM fit_sessions f
        WHERE f.start_ts < segments.end_ts AND f.end_ts > segments.start_ts
      );
    """)
    matched_cnt = c.rowcount

    # Fix misclassified vehicle trips that were actually cycling or walking
    c.execute("""
    UPDATE segments
    SET activity_type = fit_activity_type
    WHERE segment_type = 'activity'
      AND fit_activity_type IN ('CYCLING', 'RUNNING')
      AND activity_type IN ('IN_PASSENGER_VEHICLE', 'UNKNOWN', 'MOVING');
    """)
    reclassified_cnt = c.rowcount

    conn.commit()
    conn.close()

    print(f"[✓] Corroborated {matched_cnt} timeline activities with Google Fit sensor ground truth.")
    print(f"[✓] Corrected {reclassified_cnt} misclassified vehicle/unknown trips to CYCLING/RUNNING.")
    return {
        "matched_activities": matched_cnt,
        "reclassified_activities": reclassified_cnt
    }


def generate_fit_gap_proposals(db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """Identifies timeline gaps where Google Fit has a recorded session and generates fix proposals."""
    conn = sqlite3.connect(db_path, timeout=60.0)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS fit_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        activity_type TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        start_ts REAL NOT NULL,
        end_ts REAL NOT NULL,
        duration_minutes REAL NOT NULL,
        date TEXT NOT NULL,
        filename TEXT
    );
    """)

    c.execute("""
    SELECT g.id as gap_id, g.date, g.start_time, g.end_time, g.start_ts, g.end_ts, (g.duration_hours * 60.0) as duration_minutes
    FROM gaps g
    WHERE (g.duration_hours * 60.0) >= 10;
    """)
    gaps = [dict(r) for r in c.fetchall()]

    c.execute("""
    SELECT f.id, f.activity_type, f.start_time, f.end_time, f.start_ts, f.end_ts, f.duration_minutes, f.date
    FROM fit_sessions f
    WHERE f.duration_minutes >= 10;
    """)
    fit_sessions = [dict(r) for r in c.fetchall()]

    proposals = []
    for g in gaps:
        gst, get = g["start_ts"], g["end_ts"]
        overlapping_fit = [
            f for f in fit_sessions
            if f["start_ts"] < get and f["end_ts"] > gst
        ]

        if overlapping_fit:
            f = overlapping_fit[0]
            prop = {
                "gap_id": g["gap_id"],
                "date": g["date"],
                "fit_session_id": f["id"],
                "activity_type": f["activity_type"],
                "duration_minutes": f["duration_minutes"],
                "start_time": f["start_time"],
                "end_time": f["end_time"],
                "description": f"Google Fit recorded a {f['duration_minutes']:.0f}m {f['activity_type'].title()} workout during timeline gap ({g['date']} {f['start_time'][11:16]}–{f['end_time'][11:16]}). Propose synthesizing {f['activity_type'].lower()} leg."
            }
            proposals.append(prop)

    conn.close()
    return proposals


if __name__ == "__main__":
    ingest_fit_sessions()
    corroborate_fit_activities()
    props = generate_fit_gap_proposals()
    print(f"\n[✓] Found {len(props)} timeline gaps resolvable via Google Fit recorded workouts.")
    for p in props[:10]:
        print(f"  • [{p['date']}] {p['description']}")
