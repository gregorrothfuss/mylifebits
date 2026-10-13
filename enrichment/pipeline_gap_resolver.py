"""
High-Speed Master Timeline Continuity & Gap Resolution Pipeline
Parallelized with ThreadPoolExecutor & Batch SQLite Transactions
"""

import sqlite3
import json
import urllib.request
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from enrichment.local_timezone import get_timezone_offset_hours
from life_periods import get_date_aware_label

DEFAULT_DB = "timeline_viewer.db"
API_KEY = ""


def reverse_geocode_coord(lat: float, lng: float, api_key: str = API_KEY) -> Dict[str, str]:
    url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lng}&key={api_key}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'GoogleTimelineStudio/2.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data.get('status') == 'OK' and data.get('results'):
                top = data['results'][0]
                fmt_addr = top.get('formatted_address', '')
                first_name = fmt_addr.split(',')[0]
                return {"name": first_name, "address": fmt_addr}
    except Exception:
        pass
    return {"name": "Stationary Dwell", "address": f"{lat:.4f}, {lng:.4f}"}


def convert_zero_distance_activities_to_visits(db_path: str = DEFAULT_DB, workers: int = 12) -> int:
    """Converts stationary 0.0m activities (>30m) into real visit segments."""
    conn = sqlite3.connect(db_path, timeout=60.0)
    c = conn.cursor()

    c.execute("""
    SELECT id, date, duration_minutes, start_time, end_time, start_ts, end_ts, latitude, longitude
    FROM segments
    WHERE segment_type = 'activity'
      AND duration_minutes >= 30.0
      AND (distance_meters IS NULL OR distance_meters < 50.0)
      AND latitude IS NOT NULL AND longitude IS NOT NULL;
    """)
    rows = c.fetchall()
    total = len(rows)
    print(f"[*] Converting {total} zero-distance activities to stationary visits...")

    def resolve_one(r):
        sid, date, dur_m, st, et, sts, ets, lat, lng = r
        label, cat = get_date_aware_label(db_path, "Stationary Location", lat, lng, date)
        if not label or label == "Stationary Location":
            geo = reverse_geocode_coord(lat, lng)
            return sid, geo['name'], geo['address'], cat or 'Other / POI'
        else:
            return sid, label, label, cat or 'Home & Residence'

    updates = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(resolve_one, r) for r in rows]
        for f in as_completed(futures):
            try:
                updates.append(f.result())
            except Exception:
                pass

    for sid, pname, paddr, cat in updates:
        c.execute("""
        UPDATE segments
        SET segment_type = 'visit',
            activity_type = NULL,
            place_name = ?,
            place_address = ?,
            category = ?,
            has_snapped_path = 0,
            path_points_json = NULL
        WHERE id = ?;
        """, (pname, paddr, cat, sid))

    conn.commit()
    conn.close()
    return len(updates)


def batch_apply_all_valid_breadcrumb_proposals(db_path: str = DEFAULT_DB) -> int:
    """Applies all pending breadcrumb visit reconstruction proposals."""
    from enrichment.engine import TimelineEnrichmentEngine
    conn = sqlite3.connect(db_path, timeout=60.0)
    c = conn.cursor()

    c.execute("SELECT id FROM fix_proposals WHERE proposed_action = 'RECONSTRUCT_FROM_BREADCRUMBS' AND status = 'PENDING';")
    pids = [r[0] for r in c.fetchall()]
    conn.close()

    print(f"[*] Applying {len(pids)} breadcrumb visit reconstructions...")
    engine = TimelineEnrichmentEngine(db_path=db_path)
    applied = 0
    for pid in pids:
        try:
            if engine.apply_fix_proposal(pid):
                applied += 1
        except Exception:
            pass
    return applied


def batch_apply_all_dwell_extensions(db_path: str = DEFAULT_DB) -> int:
    """Applies all pending stationary dwell extensions."""
    from enrichment.engine import TimelineEnrichmentEngine
    conn = sqlite3.connect(db_path, timeout=60.0)
    c = conn.cursor()

    c.execute("SELECT id FROM fix_proposals WHERE proposed_action = 'EXTEND_STATIONARY_DWELL' AND status = 'PENDING';")
    pids = [r[0] for r in c.fetchall()]
    conn.close()

    print(f"[*] Applying {len(pids)} stationary dwell extensions...")
    engine = TimelineEnrichmentEngine(db_path=db_path)
    applied = 0
    for pid in pids:
        try:
            if engine.apply_fix_proposal(pid):
                applied += 1
        except Exception:
            pass
    return applied


def linear_consolidate_adjacent_identical_visits(db_path: str = DEFAULT_DB) -> int:
    """Consolidates adjacent identical visits across the entire database."""
    conn = sqlite3.connect(db_path, timeout=60.0)
    c = conn.cursor()

    c.execute("""
    SELECT id, date, segment_type, place_name, start_time, start_ts, end_time, end_ts, hierarchy_level
    FROM segments
    ORDER BY start_ts ASC;
    """)
    rows = c.fetchall()

    to_delete = []
    to_update = []
    prev = None

    for r in rows:
        sid, d, stype, pname, st, sts, et, ets, hlevel = r
        if prev:
            p_sid, p_d, p_stype, p_pname, p_st, p_sts, p_et, p_ets, p_hlevel = prev
            if stype == 'visit' and p_stype == 'visit' and pname and p_pname and pname == p_pname and hlevel == 0 and p_hlevel == 0:
                if abs(sts - p_ets) <= 120:
                    new_dur = (ets - p_sts) / 60.0
                    to_update.append((et, ets, new_dur, p_sid))
                    to_delete.append(sid)
                    prev = (p_sid, p_d, p_stype, p_pname, p_st, p_sts, et, ets, p_hlevel)
                    continue
        prev = r

    for et, ets, dur, p_sid in to_update:
        c.execute('UPDATE segments SET end_time = ?, end_ts = ?, duration_minutes = ? WHERE id = ?;', (et, ets, dur, p_sid))

    for sid in to_delete:
        c.execute('DELETE FROM segments WHERE id = ?;', (sid,))

    conn.commit()
    conn.close()
    return len(to_delete)


if __name__ == "__main__":
    t0 = time.time()
    print("[*] High-Speed Master Gap Resolution Pipeline Starting...")
    c1 = convert_zero_distance_activities_to_visits()
    print(f"[✓] Converted {c1} zero-distance activities to stationary visits.")
    c2 = batch_apply_all_valid_breadcrumb_proposals()
    print(f"[✓] Reconstructed {c2} visits from raw GPS breadcrumbs.")
    c3 = batch_apply_all_dwell_extensions()
    print(f"[✓] Applied {c3} stationary dwell extensions.")
    c4 = linear_consolidate_adjacent_identical_visits()
    print(f"[✓] Consolidated {c4} adjacent split visits.")
    print(f"\n[✓] Master Pipeline Completed in {time.time() - t0:.1f}s!")
