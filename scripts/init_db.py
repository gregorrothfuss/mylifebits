#!/usr/bin/env python3
"""
Database Schema Initialization & Demo Data Generator.

Usage:
    uv run python scripts/init_db.py                  # Initialize empty database schema
    uv run python scripts/init_db.py --demo           # Initialize and populate rich demo dataset
    uv run python scripts/init_db.py --db my.db --demo # Custom target database
"""

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from db import DEFAULT_DB_PATH, get_db_connection, init_db


def populate_demo_data(db_path: str = DEFAULT_DB_PATH) -> None:
    """Populates an anonymized, realistic multi-day timeline dataset for exploration."""
    conn = get_db_connection(db_path)
    c = conn.cursor()

    print(f"[*] Populating demo dataset into {db_path}...")

    # 1. Sources
    c.execute("""
    INSERT OR REPLACE INTO sources (source_name, file_path, imported_at, record_count, metadata_json)
    VALUES (?, ?, ?, ?, ?);
    """, (
        "DEMO_SYNTHETIC_DATASET",
        "scripts/init_db.py",
        datetime.datetime.now(datetime.timezone.utc).isoformat(),
        42,
        json.dumps({"environment": "demo", "license": "CC0", "generator": "MyLifeBits Demo Seeder"}),
    ))

    # 2. Places Catalog
    demo_places = [
        (
            "ChIJ_demo_home_01",
            "Home (Highland Ave)",
            "124 Highland Ave, Somerville, MA 02143",
            "TYPE_HOME",
            "Home & Residence",
            "Somerville",
            "United States",
            1,
            42.3872,
            -71.1163,
            120,
            "DEMO",
            5,
            "Primary residential sanctuary.",
            1,
            1,
        ),
        (
            "ChIJ_demo_cafe_01",
            "Diesel Cafe",
            "257 Elm St, Somerville, MA 02144",
            "CAFE",
            "Food & Drink",
            "Somerville",
            "United States",
            1,
            42.3965,
            -71.1225,
            45,
            "DEMO",
            5,
            "Fantastic cold brew and breakfast sandwiches in Davis Square.",
            3,
            1,
        ),
        (
            "ChIJ_demo_work_01",
            "Tech Innovation Hub",
            "100 Binney St, Cambridge, MA 02142",
            "TYPE_WORK",
            "Work & Office",
            "Cambridge",
            "United States",
            1,
            42.3654,
            -71.0852,
            88,
            "DEMO",
            4,
            "Engineering office and design studio.",
            2,
            1,
        ),
        (
            "ChIJ_demo_park_01",
            "Boston Common & Public Garden",
            "139 Tremont St, Boston, MA 02111",
            "PARK",
            "Arts & Entertainment",
            "Boston",
            "United States",
            1,
            42.3550,
            -71.0656,
            18,
            "DEMO",
            5,
            "Historic central park, weeping willows, and swan boats.",
            5,
            1,
        ),
        (
            "ChIJ_demo_transit_01",
            "South Station Transit Center",
            "700 Atlantic Ave, Boston, MA 02110",
            "TRANSIT_STATION",
            "Travel & Transit",
            "Boston",
            "United States",
            1,
            42.3523,
            -71.0552,
            32,
            "DEMO",
            4,
            "Major multi-modal rail hub and bus terminal.",
            1,
            1,
        ),
        (
            "ChIJ_demo_food_02",
            "Tatte Bakery & Cafe",
            "318 Third St, Cambridge, MA 02142",
            "BAKERY",
            "Food & Drink",
            "Cambridge",
            "United States",
            1,
            42.3648,
            -71.0825,
            24,
            "DEMO",
            5,
            "Fresh shakshuka, halloumi salad, and pistachio croissants.",
            4,
            1,
        ),
        (
            "ChIJ_demo_museum_01",
            "Museum of Fine Arts",
            "465 Huntington Ave, Boston, MA 02115",
            "MUSEUM",
            "Arts & Entertainment",
            "Boston",
            "United States",
            1,
            42.3394,
            -71.0940,
            12,
            "DEMO",
            5,
            "World-class art collections from Impressionism to contemporary sculpture.",
            6,
            1,
        ),
    ]

    c.executemany("""
    INSERT OR REPLACE INTO places (
        place_id, name, address, semantic_type, category, city, country,
        user_confirmed, latitude, longitude, visit_count, source,
        review_rating, review_text, review_count, has_review
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, demo_places)

    # 3. Multi-day Continuous Timeline Segments
    # We generate 2 complete realistic days: yesterday and today (local timezone)
    today = datetime.date.today()
    day1 = today - datetime.timedelta(days=1)
    day2 = today

    def dt_utc(d: datetime.date, hour: int, minute: int) -> tuple[str, float]:
        dt = datetime.datetime(d.year, d.month, d.day, hour, minute, 0, tzinfo=datetime.timezone.utc)
        return dt.isoformat(), dt.timestamp()

    # Pre-calculated road snapped polyline coordinates between Somerville & Cambridge
    route_home_to_cafe = [
        [42.3872, -71.1163],
        [42.3895, -71.1180],
        [42.3930, -71.1205],
        [42.3965, -71.1225],
    ]
    route_cafe_to_work = [
        [42.3965, -71.1225],
        [42.3900, -71.1150],
        [42.3800, -71.1050],
        [42.3700, -71.0950],
        [42.3654, -71.0852],
    ]
    route_work_to_park = [
        [42.3654, -71.0852],
        [42.3600, -71.0750],
        [42.3550, -71.0656],
    ]
    route_park_to_home = [
        [42.3550, -71.0656],
        [42.3650, -71.0850],
        [42.3750, -71.1000],
        [42.3872, -71.1163],
    ]

    segments = []

    # --- DAY 1 ---
    d1_str = day1.isoformat()
    # 00:00 - 08:30: Overnight Home
    st, st_ts = dt_utc(day1, 0, 0)
    et, et_ts = dt_utc(day1, 8, 30)
    segments.append((
        "visit", st, et, st_ts, et_ts, 510.0, d1_str, day1.year, day1.month, day1.day,
        42.3872, -71.1163, None, None, "ChIJ_demo_home_01", "Home (Highland Ave)",
        "124 Highland Ave, Somerville, MA", "TYPE_HOME", "Home & Residence", "Somerville",
        None, 0.0, 1.0, 0, None, None, 0, 0, "DEMO"
    ))

    # 08:30 - 08:45: Walk to Diesel Cafe
    st, st_ts = dt_utc(day1, 8, 30)
    et, et_ts = dt_utc(day1, 8, 45)
    segments.append((
        "activity", st, et, st_ts, et_ts, 15.0, d1_str, day1.year, day1.month, day1.day,
        42.3872, -71.1163, 42.3965, -71.1225, None, None, None, None, "Travel & Transit", None,
        "WALKING", 1300.0, 1.0, 0, None, json.dumps(route_home_to_cafe), 1, 0, "DEMO"
    ))

    # 08:45 - 09:30: Breakfast at Diesel Cafe
    st, st_ts = dt_utc(day1, 8, 45)
    et, et_ts = dt_utc(day1, 9, 30)
    segments.append((
        "visit", st, et, st_ts, et_ts, 45.0, d1_str, day1.year, day1.month, day1.day,
        42.3965, -71.1225, None, None, "ChIJ_demo_cafe_01", "Diesel Cafe",
        "257 Elm St, Somerville, MA", "CAFE", "Food & Drink", "Somerville",
        None, 0.0, 1.0, 0, None, None, 0, 0, "DEMO"
    ))

    # 09:30 - 10:00: Cycling commute to Tech Hub
    st, st_ts = dt_utc(day1, 9, 30)
    et, et_ts = dt_utc(day1, 10, 0)
    segments.append((
        "activity", st, et, st_ts, et_ts, 30.0, d1_str, day1.year, day1.month, day1.day,
        42.3965, -71.1225, 42.3654, -71.0852, None, None, None, None, "Travel & Transit", None,
        "CYCLING", 5200.0, 1.0, 0, None, json.dumps(route_cafe_to_work), 1, 0, "DEMO"
    ))

    # 10:00 - 18:00: Work at Tech Innovation Hub
    st, st_ts = dt_utc(day1, 10, 0)
    et, et_ts = dt_utc(day1, 18, 0)
    segments.append((
        "visit", st, et, st_ts, et_ts, 480.0, d1_str, day1.year, day1.month, day1.day,
        42.3654, -71.0852, None, None, "ChIJ_demo_work_01", "Tech Innovation Hub",
        "100 Binney St, Cambridge, MA", "TYPE_WORK", "Work & Office", "Cambridge",
        None, 0.0, 1.0, 0, None, None, 0, 0, "DEMO"
    ))

    # 18:00 - 18:30: Subway / Transit to Boston Common
    st, st_ts = dt_utc(day1, 18, 0)
    et, et_ts = dt_utc(day1, 18, 30)
    segments.append((
        "activity", st, et, st_ts, et_ts, 30.0, d1_str, day1.year, day1.month, day1.day,
        42.3654, -71.0852, 42.3550, -71.0656, None, None, None, None, "Travel & Transit", None,
        "IN_SUBWAY", 3100.0, 1.0, 0, None, json.dumps(route_work_to_park), 1, 0, "DEMO"
    ))

    # 18:30 - 19:45: Stroll in Boston Common & Public Garden
    st, st_ts = dt_utc(day1, 18, 30)
    et, et_ts = dt_utc(day1, 19, 45)
    segments.append((
        "visit", st, et, st_ts, et_ts, 75.0, d1_str, day1.year, day1.month, day1.day,
        42.3550, -71.0656, None, None, "ChIJ_demo_park_01", "Boston Common & Public Garden",
        "139 Tremont St, Boston, MA", "PARK", "Arts & Entertainment", "Boston",
        None, 0.0, 1.0, 0, None, None, 0, 0, "DEMO"
    ))

    # 19:45 - 20:30: Drive home to Somerville
    st, st_ts = dt_utc(day1, 19, 45)
    et, et_ts = dt_utc(day1, 20, 30)
    segments.append((
        "activity", st, et, st_ts, et_ts, 45.0, d1_str, day1.year, day1.month, day1.day,
        42.3550, -71.0656, 42.3872, -71.1163, None, None, None, None, "Travel & Transit", None,
        "DRIVING", 6800.0, 1.0, 0, None, json.dumps(route_park_to_home), 1, 0, "DEMO"
    ))

    # 20:30 - 24:00: Evening at Home
    st, st_ts = dt_utc(day1, 20, 30)
    et, et_ts = dt_utc(day1, 23, 59)
    segments.append((
        "visit", st, et, st_ts, et_ts, 209.0, d1_str, day1.year, day1.month, day1.day,
        42.3872, -71.1163, None, None, "ChIJ_demo_home_01", "Home (Highland Ave)",
        "124 Highland Ave, Somerville, MA", "TYPE_HOME", "Home & Residence", "Somerville",
        None, 0.0, 1.0, 0, None, None, 0, 0, "DEMO"
    ))

    # --- DAY 2 (Today) ---
    d2_str = day2.isoformat()
    # 00:00 - 09:00: Overnight Home
    st, st_ts = dt_utc(day2, 0, 0)
    et, et_ts = dt_utc(day2, 9, 0)
    segments.append((
        "visit", st, et, st_ts, et_ts, 540.0, d2_str, day2.year, day2.month, day2.day,
        42.3872, -71.1163, None, None, "ChIJ_demo_home_01", "Home (Highland Ave)",
        "124 Highland Ave, Somerville, MA", "TYPE_HOME", "Home & Residence", "Somerville",
        None, 0.0, 1.0, 0, None, None, 0, 0, "DEMO"
    ))

    # 09:00 - 09:40: Drive to Museum of Fine Arts
    st, st_ts = dt_utc(day2, 9, 0)
    et, et_ts = dt_utc(day2, 9, 40)
    segments.append((
        "activity", st, et, st_ts, et_ts, 40.0, d2_str, day2.year, day2.month, day2.day,
        42.3872, -71.1163, 42.3394, -71.0940, None, None, None, None, "Travel & Transit", None,
        "DRIVING", 8200.0, 1.0, 0, None, json.dumps([[42.3872, -71.1163], [42.3650, -71.1050], [42.3394, -71.0940]]), 1, 0, "DEMO"
    ))

    # 09:40 - 13:00: Museum of Fine Arts Exhibition
    st, st_ts = dt_utc(day2, 9, 40)
    et, et_ts = dt_utc(day2, 13, 0)
    segments.append((
        "visit", st, et, st_ts, et_ts, 200.0, d2_str, day2.year, day2.month, day2.day,
        42.3394, -71.0940, None, None, "ChIJ_demo_museum_01", "Museum of Fine Arts",
        "465 Huntington Ave, Boston, MA", "MUSEUM", "Arts & Entertainment", "Boston",
        None, 0.0, 1.0, 0, None, None, 0, 0, "DEMO"
    ))

    # 13:00 - 13:30: Transit to Tatte Bakery
    st, st_ts = dt_utc(day2, 13, 0)
    et, et_ts = dt_utc(day2, 13, 30)
    segments.append((
        "activity", st, et, st_ts, et_ts, 30.0, d2_str, day2.year, day2.month, day2.day,
        42.3394, -71.0940, 42.3648, -71.0825, None, None, None, None, "Travel & Transit", None,
        "IN_PASSENGER_VEHICLE", 4500.0, 1.0, 0, None, json.dumps([[42.3394, -71.0940], [42.3550, -71.0880], [42.3648, -71.0825]]), 1, 0, "DEMO"
    ))

    # 13:30 - 15:00: Lunch at Tatte Bakery
    st, st_ts = dt_utc(day2, 13, 30)
    et, et_ts = dt_utc(day2, 15, 0)
    segments.append((
        "visit", st, et, st_ts, et_ts, 90.0, d2_str, day2.year, day2.month, day2.day,
        42.3648, -71.0825, None, None, "ChIJ_demo_food_02", "Tatte Bakery & Cafe",
        "318 Third St, Cambridge, MA", "BAKERY", "Food & Drink", "Cambridge",
        None, 0.0, 1.0, 0, None, None, 0, 0, "DEMO"
    ))

    # 15:00 - 15:40: Return walk home
    st, st_ts = dt_utc(day2, 15, 0)
    et, et_ts = dt_utc(day2, 15, 40)
    segments.append((
        "activity", st, et, st_ts, et_ts, 40.0, d2_str, day2.year, day2.month, day2.day,
        42.3648, -71.0825, 42.3872, -71.1163, None, None, None, None, "Travel & Transit", None,
        "WALKING", 3800.0, 1.0, 0, None, json.dumps([[42.3648, -71.0825], [42.3760, -71.0980], [42.3872, -71.1163]]), 1, 0, "DEMO"
    ))

    # 15:40 - 23:59: Home
    st, st_ts = dt_utc(day2, 15, 40)
    et, et_ts = dt_utc(day2, 23, 59)
    segments.append((
        "visit", st, et, st_ts, et_ts, 499.0, d2_str, day2.year, day2.month, day2.day,
        42.3872, -71.1163, None, None, "ChIJ_demo_home_01", "Home (Highland Ave)",
        "124 Highland Ave, Somerville, MA", "TYPE_HOME", "Home & Residence", "Somerville",
        None, 0.0, 1.0, 0, None, None, 0, 0, "DEMO"
    ))

    c.executemany("""
    INSERT INTO segments (
        segment_type, start_time, end_time, start_ts, end_ts, duration_minutes,
        date, year, month, day, latitude, longitude, end_lat, end_lng,
        place_id, place_name, place_address, semantic_type, category, city,
        activity_type, distance_meters, probability, hierarchy_level,
        parent_segment_id, path_points_json, has_snapped_path, is_unconfirmed, source
    ) VALUES (
        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
        ?, ?, ?, ?, ?, ?, ?, ?, ?
    );
    """, segments)

    # 4. Breadcrumbs
    breadcrumbs = []
    for coord in route_cafe_to_work:
        breadcrumbs.append((
            d1_str, coord[0], coord[1], 10.0, 0
        ))
    c.executemany("""
    INSERT INTO breadcrumbs (date, lat, lng, accuracy, is_excluded)
    VALUES (?, ?, ?, ?, ?);
    """, breadcrumbs)

    # 5. Trips & Expeditions
    c.execute("""
    INSERT OR REPLACE INTO trips (
        id, name, destination_label, primary_city, country, start_date, end_date,
        duration_days, total_distance_km, visit_count, top_places_json, highlight_poi, status
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, (
        "demo_trip_boston_autumn",
        "Boston & Cambridge Cultural Weekend",
        "Boston & Cambridge",
        "Boston",
        "United States",
        d1_str,
        d2_str,
        2,
        45.2,
        6,
        json.dumps(["Museum of Fine Arts", "Boston Common", "Diesel Cafe", "Tatte Bakery"]),
        "Museum of Fine Arts",
        "completed",
    ))

    # 6. Life Periods
    c.execute("""
    INSERT OR REPLACE INTO life_periods (
        id, name, type, role_title, address, start_date, end_date,
        lat, lng, is_current, description
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, (
        1,
        "Greater Boston Area",
        "HOME",
        "Software Engineer",
        "124 Highland Ave, Somerville, MA 02143",
        "2023-01-01",
        "2030-12-31",
        42.3872,
        -71.1163,
        1,
        "Engineering and research residence.",
    ))

    # 7. Country Stats
    c.execute("""
    INSERT OR REPLACE INTO country_stats (
        country, flag, trips_count, total_days, total_visits, first_visit, latest_visit
    ) VALUES (?, ?, ?, ?, ?, ?, ?);
    """, (
        "United States",
        "🇺🇸",
        1,
        2.0,
        15,
        d1_str,
        d2_str,
    ))

    conn.commit()
    conn.close()
    print(f"[✓] Successfully seeded demo dataset ({len(demo_places)} places, {len(segments)} segments across 2 days)!")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Initialize Timeline Studio database schema and optional demo dataset."
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Path to SQLite database (default: TIMELINE_DB_PATH or ./timeline.db)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Seed an anonymized, realistic multi-day sample dataset for immediate UI exploration.",
    )
    args = parser.parse_args()

    db_path = args.db or DEFAULT_DB_PATH
    print(f"[*] Initializing database schema: {db_path}")
    init_db(db_path)
    print(f"[✓] Database tables and indexes verified.")

    if args.demo:
        populate_demo_data(db_path)


if __name__ == "__main__":
    main()
