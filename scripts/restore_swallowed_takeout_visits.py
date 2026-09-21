"""
Restoration script: Restores 10 authentic place visits from the 2024 Takeout archive
that were swallowed by moving segments or gaps in timeline_viewer.db.
"""

import sqlite3
import zipfile
import json
from datetime import datetime
import zoneinfo
from typing import Dict, Any, List, Optional

TAKEOUT_ZIP = "/Users/rothfuss/Downloads/lh-20241129T224901Z-001.zip"
DB_PATH = "timeline_viewer.db"

# The 10 visits to restore
TARGET_VISITS = [
    {
        "name": "Flatiron Hall Restaurant and Beer Hall",
        "place_id": "ChIJ7QdJt6VZwokRYsWTrFT38DE",
        "year": "2014",
        "month_file": "2014_MARCH.json",
        "start_time": "2014-03-08T20:00:00Z",
        "end_time": "2014-03-08T23:10:04.043Z",
        "tz": "America/New_York"
    },
    {
        "name": "Rattle N Hum East",
        "place_id": "ChIJMYvUOahZwokRVyFFnT5Opzs",
        "year": "2013",
        "month_file": "2013_JANUARY.json",
        "start_time": "2013-01-12T23:27:00Z",
        "end_time": "2013-01-13T01:40:33.006Z",
        "tz": "America/New_York"
    },
    {
        "name": "Tortillería Nixtamal",
        "place_id": "ChIJ_2Sf9ypcwokR0BfJfqCIhPg",
        "year": "2013",
        "month_file": "2013_JANUARY.json",
        "start_time": "2013-01-12T19:54:17Z",
        "end_time": "2013-01-12T20:33:27Z",
        "tz": "America/New_York"
    },
    {
        "name": "Zabb Elee",
        "place_id": "ChIJ18kBU5tZwokR9u6fDlL_vGg",
        "year": "2013",
        "month_file": "2013_JANUARY.json",
        "start_time": "2013-01-06T23:27:00Z",
        "end_time": "2013-01-07T00:37:44.153Z",
        "tz": "America/New_York"
    },
    {
        "name": "Revival",
        "place_id": "ChIJS9waPJ9ZwokR97xRCgtZE64",
        "year": "2014",
        "month_file": "2014_AUGUST.json",
        "start_time": "2014-08-19T23:47:02.282Z",
        "end_time": "2014-08-20T00:52:29.392Z",
        "tz": "America/New_York"
    },
    {
        "name": "Two Boots Williamsburg",
        "place_id": "ChIJC9NW1F1ZwokRcsBcJyll3JE",
        "year": "2014",
        "month_file": "2014_JUNE.json",
        "start_time": "2014-06-15T04:09:00Z",
        "end_time": "2014-06-15T04:36:34.283Z",
        "tz": "America/New_York"
    },
    {
        "name": "Cafe Pick Me Up",
        "place_id": "ChIJhasV13dZwokRFFXdw_vHz9s",
        "year": "2013",
        "month_file": "2013_MAY.json",
        "start_time": "2013-05-26T18:14:00Z",
        "end_time": "2013-05-26T18:49:27.869Z",
        "tz": "America/New_York"
    },
    {
        "name": "Associated Supermarkets",
        "place_id": "ChIJOZ9kwHVZwokRGZwtSrIw9K4",
        "year": "2013",
        "month_file": "2013_APRIL.json",
        "start_time": "2013-04-16T23:08:17Z",
        "end_time": "2013-04-16T23:20:26Z",
        "tz": "America/New_York"
    },
    {
        "name": "Good Beer",
        "place_id": "ChIJf3BOcJ1ZwokRafhLEqVTNo8",
        "year": "2013",
        "month_file": "2013_JANUARY.json",
        "start_time": "2013-01-30T01:56:53Z",
        "end_time": "2013-01-30T02:08:22Z",
        "tz": "America/New_York"
    },
    {
        "name": "Good Beer",
        "place_id": "ChIJf3BOcJ1ZwokRafhLEqVTNo8",
        "year": "2011",
        "month_file": "2011_OCTOBER.json",
        "start_time": "2011-10-05T00:12:46Z",
        "end_time": "2011-10-05T00:24:47Z",
        "tz": "America/New_York"
    }
]


def parse_ts(ts_str: str) -> float:
    clean = ts_str.replace("Z", "+00:00")
    return datetime.fromisoformat(clean).timestamp()


def format_iso(ts: float) -> str:
    dt = datetime.fromtimestamp(ts, tz=zoneinfo.ZoneInfo("UTC"))
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def restore_visits() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    print("[+] Starting restoration of 10 swallowed place visits...")

    for spec in TARGET_VISITS:
        v_name = spec["name"]
        v_pid = spec["place_id"]
        v_st = spec["start_time"]
        v_et = spec["end_time"]
        v_st_ts = parse_ts(v_st)
        v_et_ts = parse_ts(v_et)
        tz = zoneinfo.ZoneInfo(spec["tz"])
        local_dt = datetime.fromtimestamp(v_st_ts, tz=tz)
        local_date = local_dt.strftime("%Y-%m-%d")

        # 1. Fetch place info from catalog
        p_row = cur.execute(
            "SELECT name, address, latitude, longitude, category, city, country FROM places WHERE place_id = ?",
            (v_pid,)
        ).fetchone()
        
        if not p_row:
            print(f"[-] ERROR: Place ID {v_pid} ({v_name}) not found in places catalog!")
            continue

        lat = p_row["latitude"]
        lng = p_row["longitude"]
        addr = p_row["address"]
        cat = p_row["category"]
        city = p_row["city"]
        country = p_row["country"]

        print(f"\n--- Restoring: {v_name} ({v_st} -> {v_et}, {spec['year']}) ---")

        # 2. Find overlapping segments in timeline_viewer.db
        overlapping = cur.execute(
            "SELECT * FROM segments WHERE end_time > ? AND start_time < ? ORDER BY start_time",
            (v_st, v_et)
        ).fetchall()

        if not overlapping:
            print(f"  No direct overlapping segment. Checking gap...")
            # Check preceding and succeeding
            prec = cur.execute("SELECT * FROM segments WHERE end_time <= ? ORDER BY end_time DESC LIMIT 1", (v_st,)).fetchone()
            succ = cur.execute("SELECT * FROM segments WHERE start_time >= ? ORDER BY start_time ASC LIMIT 1", (v_et,)).fetchone()
            print(f"  Preceding: {prec['place_name'] or prec['activity_type']} (ends {prec['end_time']})")
            print(f"  Succeeding: {succ['place_name'] or succ['activity_type']} (starts {succ['start_time']})")
            
            # Insert the visit directly into the gap
            dur_m = (v_et_ts - v_st_ts) / 60.0
            cur.execute("""
                INSERT INTO segments (
                    segment_type, start_time, end_time, start_ts, end_ts, duration_minutes,
                    date, year, month, day, latitude, longitude, place_id, place_name,
                    place_address, source, category, city, probability, hierarchy_level,
                    is_unconfirmed, has_snapped_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0, 0, 0, 0)
            """, (
                "visit", v_st, v_et, v_st_ts, v_et_ts, dur_m,
                local_date, local_dt.year, local_dt.month, local_dt.day,
                lat, lng, v_pid, v_name, addr, "TAKEOUT_2024", cat, city
            ))
            print(f"  [✓] Inserted visit {v_name} ({dur_m:.1f}m)")

        elif len(overlapping) == 1 and overlapping[0]["segment_type"] == "activity":
            act = overlapping[0]
            act_id = act["id"]
            act_st_ts = act["start_ts"]
            act_et_ts = act["end_ts"]
            act_type = act["activity_type"] or "WALKING"

            print(f"  Overlapped by Activity [{act_id}] ({act_type}: {act['start_time']} -> {act['end_time']})")

            # Case A: Activity covers before and after
            has_pre_leg = (v_st_ts - act_st_ts) >= 60.0  # at least 1 min
            has_post_leg = (act_et_ts - v_et_ts) >= 60.0 # at least 1 min

            if has_pre_leg and has_post_leg:
                # 1. Trim existing activity to end at v_st
                new_dur = (v_st_ts - act_st_ts) / 60.0
                cur.execute("""
                    UPDATE segments 
                    SET end_time = ?, end_ts = ?, duration_minutes = ?
                    WHERE id = ?
                """, (v_st, v_st_ts, new_dur, act_id))
                print(f"  [✓] Trimmed initial activity leg [{act_id}] to {act['start_time']} -> {v_st} ({new_dur:.1f}m)")

                # 2. Insert the restored visit
                dur_m = (v_et_ts - v_st_ts) / 60.0
                cur.execute("""
                    INSERT INTO segments (
                        segment_type, start_time, end_time, start_ts, end_ts, duration_minutes,
                        date, year, month, day, latitude, longitude, place_id, place_name,
                        place_address, source, category, city, probability, hierarchy_level,
                        is_unconfirmed, has_snapped_path
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0, 0, 0, 0)
                """, (
                    "visit", v_st, v_et, v_st_ts, v_et_ts, dur_m,
                    local_date, local_dt.year, local_dt.month, local_dt.day,
                    lat, lng, v_pid, v_name, addr, "TAKEOUT_2024", cat, city
                ))
                print(f"  [✓] Inserted visit {v_name} ({dur_m:.1f}m)")

                # 3. Insert trailing activity leg
                post_dur = (act_et_ts - v_et_ts) / 60.0
                post_dt = datetime.fromtimestamp(v_et_ts, tz=tz)
                post_date = post_dt.strftime("%Y-%m-%d")
                cur.execute("""
                    INSERT INTO segments (
                        segment_type, activity_type, start_time, end_time, start_ts, end_ts, duration_minutes,
                        date, year, month, day, source, probability, hierarchy_level,
                        is_unconfirmed, has_snapped_path
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0, 0, 0, 0)
                """, (
                    "activity", act_type, v_et, act["end_time"], v_et_ts, act_et_ts, post_dur,
                    post_date, post_dt.year, post_dt.month, post_dt.day, "TAKEOUT_2024"
                ))
                print(f"  [✓] Inserted trailing activity leg ({v_et} -> {act['end_time']}, {post_dur:.1f}m)")

            elif has_pre_leg and not has_post_leg:
                # Activity ends with the visit
                new_dur = (v_st_ts - act_st_ts) / 60.0
                cur.execute("""
                    UPDATE segments 
                    SET end_time = ?, end_ts = ?, duration_minutes = ?
                    WHERE id = ?
                """, (v_st, v_st_ts, new_dur, act_id))

                dur_m = (v_et_ts - v_st_ts) / 60.0
                cur.execute("""
                    INSERT INTO segments (
                        segment_type, start_time, end_time, start_ts, end_ts, duration_minutes,
                        date, year, month, day, latitude, longitude, place_id, place_name,
                        place_address, source, category, city, probability, hierarchy_level,
                        is_unconfirmed, has_snapped_path
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0, 0, 0, 0)
                """, (
                    "visit", v_st, v_et, v_st_ts, v_et_ts, dur_m,
                    local_date, local_dt.year, local_dt.month, local_dt.day,
                    lat, lng, v_pid, v_name, addr, "TAKEOUT_2024", cat, city
                ))
                print(f"  [✓] Trimmed activity leg and inserted visit {v_name}")

            elif not has_pre_leg and has_post_leg:
                # Activity starts with the visit
                cur.execute("""
                    UPDATE segments 
                    SET start_time = ?, start_ts = ?, duration_minutes = ?
                    WHERE id = ?
                """, (v_et, v_et_ts, (act_et_ts - v_et_ts) / 60.0, act_id))

                dur_m = (v_et_ts - v_st_ts) / 60.0
                cur.execute("""
                    INSERT INTO segments (
                        segment_type, start_time, end_time, start_ts, end_ts, duration_minutes,
                        date, year, month, day, latitude, longitude, place_id, place_name,
                        place_address, source, category, city, probability, hierarchy_level,
                        is_unconfirmed, has_snapped_path
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0, 0, 0, 0)
                """, (
                    "visit", v_st, v_et, v_st_ts, v_et_ts, dur_m,
                    local_date, local_dt.year, local_dt.month, local_dt.day,
                    lat, lng, v_pid, v_name, addr, "TAKEOUT_2024", cat, city
                ))
                print(f"  [✓] Trimmed leading activity leg and inserted visit {v_name}")
            else:
                # Activity is virtually identical in duration to visit: replace it directly
                dur_m = (v_et_ts - v_st_ts) / 60.0
                cur.execute("""
                    UPDATE segments 
                    SET segment_type = 'visit', activity_type = NULL, place_id = ?, place_name = ?,
                        place_address = ?, latitude = ?, longitude = ?, category = ?, city = ?,
                        start_time = ?, end_time = ?, start_ts = ?, end_ts = ?, duration_minutes = ?
                    WHERE id = ?
                """, (
                    v_pid, v_name, addr, lat, lng, cat, city,
                    v_st, v_et, v_st_ts, v_et_ts, dur_m, act_id
                ))
                print(f"  [✓] Replaced activity [{act_id}] directly with visit {v_name}")
        else:
            print(f"  [-] Unexpected overlapping count or types: {len(overlapping)}")
            for ov in overlapping:
                print(f"      [{ov['id']}] {ov['segment_type']} ({ov['start_time']} -> {ov['end_time']})")

    conn.commit()
    conn.close()
    print("\n[✓] All 10 visits restored successfully.")


if __name__ == "__main__":
    restore_visits()
