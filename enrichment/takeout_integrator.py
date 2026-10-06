"""
Google Takeout Deep Multi-Modal Integrator.
Integrates:
1. Calendar (.ics) -> Calendar events, attendee names, 'with who' / event inference.
2. Google Maps Labeled Places & My Maps (.kmz) -> Custom labeled venues, points of interest, vacation notes.
3. Google Fit -> Steps, activity metrics, sessions correlation.
"""

import sqlite3
import glob
import zipfile
import json
import os
import sys
import re
import datetime
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional, Tuple

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from breadcrumbs import haversine_distance

DEFAULT_DB_PATH = os.environ.get(
    "TIMELINE_DB_PATH",
    "timeline_viewer.db" if os.path.exists("timeline_viewer.db") else "timeline.db",
)
DEFAULT_TAKEOUT_DIR = os.environ.get(
    "TAKEOUT_DIR",
    os.path.expanduser("~/Downloads/Takeout"),
)
_SELF_NAMES = {
    s.strip().lower()
    for s in os.environ.get("SELF_NAMES", "me,myself,user").split(",")
    if s.strip()
}


def parse_ics_date(val: str) -> Optional[float]:
    """Parses standard ICS DTSTART / DTEND date strings to UTC epoch timestamp."""
    val = re.sub(r"^.*:", "", val).strip()
    if "T" in val:
        val = val.replace("Z", "")
        if len(val) >= 15:
            try:
                dt = datetime.datetime.strptime(val[:15], "%Y%m%dT%H%M%S")
                return dt.replace(tzinfo=datetime.timezone.utc).timestamp()
            except Exception:
                pass
    elif len(val) >= 8:
        try:
            dt = datetime.datetime.strptime(val[:8], "%Y%m%d")
            return dt.replace(tzinfo=datetime.timezone.utc).timestamp()
        except Exception:
            pass
    return None


def extract_people_from_summary(summary: str, attendees: List[str]) -> List[str]:
    """Extracts person names from calendar summary and attendee list."""
    people = []

    # 1. Clean attendee names
    for a in attendees:
        clean_a = re.sub(r"<[^>]+>", "", a).strip()
        if "@" in clean_a:
            name_part = clean_a.split("@")[0].replace(".", " ").replace("_", " ").title()
            if len(name_part) >= 3 and name_part.lower() not in _SELF_NAMES:
                people.append(name_part)
        elif len(clean_a) >= 2 and clean_a.lower() not in _SELF_NAMES:
            people.append(clean_a)

    # 2. Extract from "with / w/ Person Name" in summary
    w_match = re.search(r"\b(?:w/|with|meet)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*(?:\s*(?:,|&|and)\s*[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)*)", summary, re.IGNORECASE)
    if w_match:
        names_block = w_match.group(1)
        for chunk in re.split(r",|&|\band\b", names_block):
            c_name = chunk.strip()
            if len(c_name) >= 2 and c_name not in people and c_name.lower() not in ("lunch", "dinner", "drinks", "breakfast", "coffee", "team", "all"):
                people.append(c_name)

    # Deduplicate preserving order
    seen = set()
    deduped = []
    for p in people:
        p_low = p.lower()
        if p_low not in seen:
            seen.add(p_low)
            deduped.append(p)

    return deduped


def ingest_calendar(db_path: str = DEFAULT_DB_PATH, takeout_dir: str = DEFAULT_TAKEOUT_DIR) -> int:
    """Ingests all Calendar ICS files into calendar_events table in SQLite."""
    conn = sqlite3.connect(db_path, timeout=60.0)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS calendar_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        summary TEXT NOT NULL,
        description TEXT,
        location TEXT,
        start_ts REAL NOT NULL,
        end_ts REAL NOT NULL,
        start_time TEXT,
        end_time TEXT,
        date TEXT,
        with_people_json TEXT,
        attendees_json TEXT,
        calendar_source TEXT
    );
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_cal_time ON calendar_events(start_ts, end_ts);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_cal_date ON calendar_events(date);")
    c.execute("DELETE FROM calendar_events;")

    cal_dir = os.path.join(takeout_dir, "Calendar")
    ics_files = glob.glob(os.path.join(cal_dir, "*.ics"))
    if not ics_files:
        print(f"[!] No ICS calendar files found in {cal_dir}")
        conn.close()
        return 0

    total_events = 0
    event_rows = []

    for ics_path in ics_files:
        cal_name = os.path.basename(ics_path)
        with open(ics_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()

        unfolded = re.sub(r"\r?\n[ \t]", "", text)
        for block in unfolded.split("BEGIN:VEVENT")[1:]:
            if "END:VEVENT" not in block:
                continue

            vevent_body = block.split("END:VEVENT")[0]
            summary = ""
            loc = ""
            desc = ""
            st_ts = None
            et_ts = None
            rrule = ""
            attendees = []

            for line in vevent_body.splitlines():
                if line.startswith("SUMMARY:"):
                    summary = line[8:].strip().replace(r"\,", ",").replace(r"\n", " ")
                elif line.startswith("LOCATION:"):
                    loc = line[9:].strip().replace(r"\,", ",").replace(r"\n", " ")
                elif line.startswith("DESCRIPTION:"):
                    desc = line[12:].strip().replace(r"\,", ",").replace(r"\n", " ")
                elif line.startswith("DTSTART"):
                    st_ts = parse_ics_date(line)
                elif line.startswith("DTEND"):
                    et_ts = parse_ics_date(line)
                elif line.startswith("RRULE:"):
                    rrule = line[6:].strip()
                elif "ATTENDEE" in line:
                    cn_m = re.search(r'CN="?([^";]+)"?', line)
                    if cn_m:
                        attendees.append(cn_m.group(1).strip())
                    else:
                        em_m = re.search(r"mailto:([^;:]+)", line, re.IGNORECASE)
                        if em_m:
                            attendees.append(em_m.group(1).strip())

            if summary and st_ts:
                if not et_ts:
                    et_ts = st_ts + 3600.0

                duration_sec = max(300.0, et_ts - st_ts)
                with_people = extract_people_from_summary(summary, attendees)
                wp_json = json.dumps(with_people) if with_people else None
                att_json = json.dumps(attendees) if attendees else None

                dt_obj = datetime.datetime.fromtimestamp(st_ts, tz=datetime.timezone.utc)
                start_year = dt_obj.year

                # Check for recurring yearly events (e.g. Birthdays, Anniversaries)
                if "FREQ=YEARLY" in rrule:
                    until_year = 2026
                    until_m = re.search(r"UNTIL=(\d{4})", rrule)
                    if until_m:
                        until_year = min(2026, int(until_m.group(1)))

                    for yr in range(max(2010, start_year), until_year + 1):
                        try:
                            occ_dt = dt_obj.replace(year=yr)
                            occ_st_ts = occ_dt.timestamp()
                            occ_et_ts = occ_st_ts + min(86400.0, duration_sec)
                            st_time_str = occ_dt.strftime("%Y-%m-%d %H:%M:%S")
                            et_time_str = datetime.datetime.fromtimestamp(occ_et_ts, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                            date_str = occ_dt.strftime("%Y-%m-%d")

                            event_rows.append((
                                summary,
                                desc[:500] if desc else None,
                                loc[:300] if loc else None,
                                occ_st_ts,
                                occ_et_ts,
                                st_time_str,
                                et_time_str,
                                date_str,
                                wp_json,
                                att_json,
                                cal_name
                            ))
                        except Exception:
                            pass
                else:
                    # Cap single event duration to 7 days to avoid runaway timezone bugs
                    if duration_sec > 86400 * 7:
                        duration_sec = 86400.0
                        et_ts = st_ts + duration_sec

                    st_time_str = dt_obj.strftime("%Y-%m-%d %H:%M:%S")
                    date_str = dt_obj.strftime("%Y-%m-%d")
                    et_time_str = datetime.datetime.fromtimestamp(et_ts, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

                    event_rows.append((
                        summary,
                        desc[:500] if desc else None,
                        loc[:300] if loc else None,
                        st_ts,
                        et_ts,
                        st_time_str,
                        et_time_str,
                        date_str,
                        wp_json,
                        att_json,
                        cal_name
                    ))

    c.executemany("""
    INSERT INTO calendar_events (
        summary, description, location, start_ts, end_ts,
        start_time, end_time, date, with_people_json, attendees_json, calendar_source
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, event_rows)
    conn.commit()
    conn.close()

    print(f"[✓] Ingested {len(event_rows)} historical calendar events into 'calendar_events' table.")
    return len(event_rows)


def ingest_my_maps_and_labeled_places(db_path: str = DEFAULT_DB_PATH, takeout_dir: str = DEFAULT_TAKEOUT_DIR) -> int:
    """Ingests Google Maps Labeled Places and My Maps KMZs into labeled_places table."""
    conn = sqlite3.connect(db_path, timeout=60.0)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS custom_labeled_places (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        address TEXT,
        description TEXT,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL,
        source_map TEXT,
        source_type TEXT
    );
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_custom_coords ON custom_labeled_places(latitude, longitude);")
    c.execute("DELETE FROM custom_labeled_places;")

    rows = []

    # 1. Maps/My labeled places/Labeled places.json
    json_path = os.path.join(takeout_dir, "Maps", "My labeled places", "Labeled places.json")
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8", errors="ignore") as f:
            data = json.load(f)
            for feat in data.get("features", []):
                prop = feat.get("properties", {})
                geom = feat.get("geometry", {})
                coords = geom.get("coordinates", [])
                if len(coords) >= 2 and coords[0] and coords[1]:
                    name = prop.get("title") or prop.get("name") or prop.get("address")
                    addr = prop.get("address")
                    if name:
                        rows.append((name, addr, None, float(coords[1]), float(coords[0]), "My Labeled Places", "labeled_places_json"))

    # 2. My Maps/*.kmz
    kmz_files = glob.glob(os.path.join(takeout_dir, "My Maps", "*.kmz"))
    for kf in kmz_files:
        map_title = os.path.splitext(os.path.basename(kf))[0]
        try:
            with zipfile.ZipFile(kf, "r") as z:
                for zname in z.namelist():
                    if zname.endswith(".kml"):
                        kml_bytes = z.read(zname)
                        root = ET.fromstring(kml_bytes)
                        for pm in root.iter("{http://www.opengis.net/kml/2.2}Placemark"):
                            pm_name = pm.find("{http://www.opengis.net/kml/2.2}name")
                            pm_desc = pm.find("{http://www.opengis.net/kml/2.2}description")
                            coords = pm.find(".//{http://www.opengis.net/kml/2.2}coordinates")
                            if pm_name is not None and pm_name.text and coords is not None and coords.text:
                                c_parts = coords.text.strip().split(",")
                                if len(c_parts) >= 2:
                                    try:
                                        lng, lat = float(c_parts[0]), float(c_parts[1])
                                        d_text = pm_desc.text if pm_desc is not None else None
                                        rows.append((pm_name.text.strip(), None, d_text, lat, lng, map_title, "my_maps_kmz"))
                                    except Exception:
                                        pass
        except Exception:
            pass

    c.executemany("""
    INSERT INTO custom_labeled_places (name, address, description, latitude, longitude, source_map, source_type)
    VALUES (?, ?, ?, ?, ?, ?, ?);
    """, rows)
    conn.commit()
    conn.close()

    print(f"[✓] Ingested {len(rows)} custom labeled places and My Maps pins into 'custom_labeled_places' table.")
    return len(rows)


def correlate_and_enrich_timeline_segments(db_path: str = DEFAULT_DB_PATH):
    """Correlates calendar events, with-people, and custom labeled places into segments and places."""
    print("🚀 Correlating Calendar events and custom labeled places with timeline visits...")
    conn = sqlite3.connect(db_path, timeout=60.0)
    c = conn.cursor()

    # Ensure columns exist on segments
    c.execute("PRAGMA table_info(segments);")
    col_names = [r[1] for r in c.fetchall()]
    new_cols = [
        ("event_title", "TEXT"),
        ("with_people", "TEXT"),
        ("event_location", "TEXT"),
        ("fit_steps", "INTEGER"),
        ("fit_activity_type", "TEXT")
    ]
    for col, col_type in new_cols:
        if col not in col_names:
            c.execute(f"ALTER TABLE segments ADD COLUMN {col} {col_type};")

    conn.commit()

    # Ensure time index exists on segments for sub-millisecond correlation
    c.execute("CREATE INDEX IF NOT EXISTS idx_segments_time ON segments(start_ts, end_ts);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_segments_date ON segments(date);")

    # Reset all old correlation values to remove tainted multi-decade matches
    c.execute("UPDATE segments SET event_title = NULL, with_people = NULL, event_location = NULL;")
    conn.commit()

    # 1. Fast indexed event-driven loop (longer events run first, shorter specific events overwrite with precision)
    c.execute("SELECT summary, with_people_json, location, start_ts, end_ts FROM calendar_events WHERE (end_ts - start_ts) <= 86400.0 ORDER BY (end_ts - start_ts) DESC;")
    cal_events = c.fetchall()

    for summary, wp_json, loc, st_ts, et_ts in cal_events:
        c.execute("""
        UPDATE segments
        SET event_title = ?, with_people = ?, event_location = ?
        WHERE segment_type = 'visit'
          AND start_ts < ? AND end_ts > ?;
        """, (summary, wp_json, loc, et_ts, st_ts))

    conn.commit()

    c.execute("SELECT COUNT(*) FROM segments WHERE with_people IS NOT NULL AND with_people != '[]';")
    with_people_cnt = c.fetchone()[0]

    # 2. Correlate Custom Labeled Places to Disambiguate Generic/Unconfirmed Venues
    c.execute("""
    SELECT clp.name, clp.latitude, clp.longitude
    FROM custom_labeled_places clp
    WHERE clp.name IS NOT NULL AND clp.name != '';
    """)
    custom_pins = c.fetchall()

    enriched_places_cnt = 0
    for pin_name, plat, plng in custom_pins:
        c.execute("""
        UPDATE places
        SET name = ?, source = 'my_maps_custom_label'
        WHERE (name IS NULL OR name LIKE 'Location (%' OR name = 'Unconfirmed Location' OR name LIKE 'Point of Interest%')
          AND latitude BETWEEN ? AND ?
          AND longitude BETWEEN ? AND ?;
        """, (pin_name, plat - 0.0008, plat + 0.0008, plng - 0.0008, plng + 0.0008))
        enriched_places_cnt += c.rowcount

    c.execute("""
    UPDATE segments
    SET place_name = (SELECT p.name FROM places p WHERE p.place_id = segments.place_id)
    WHERE place_id IS NOT NULL AND EXISTS (SELECT 1 FROM places p WHERE p.place_id = segments.place_id AND p.source = 'my_maps_custom_label');
    """)
    conn.commit()
    conn.close()

    print(f"[✓] Correlated visits with Calendar events ({with_people_cnt} with specific attendees/people).")
    print(f"[✓] Enriched {enriched_places_cnt} unconfirmed/generic places using custom My Maps labels.")


def run_full_takeout_integration(db_path: str = DEFAULT_DB_PATH, takeout_dir: str = DEFAULT_TAKEOUT_DIR):
    """Runs end-to-end integration of Calendar, My Maps, and Labeled Places."""
    print("=" * 70)
    print("🚀 Google Takeout Deep Integration Pipeline Started")
    print(f"[*] Database: {db_path}")
    print(f"[*] Takeout Directory: {takeout_dir}")
    print("=" * 70)

    ingest_calendar(db_path, takeout_dir)
    ingest_my_maps_and_labeled_places(db_path, takeout_dir)
    correlate_and_enrich_timeline_segments(db_path)

    print("\n[✓] Google Takeout integration complete.")


if __name__ == "__main__":
    run_full_takeout_integration()
