#!/usr/bin/env python3
"""
Automated Screenshot Generator for Documentation & GitHub README.

By default, spins up an ephemeral TimelineViewerHandler backed by a temporary,
100% synthetic SQLite database (zero personal data) and uses Playwright to
capture three privacy-compliant 1440x900 screenshots:
1. Daily Timeline View (Arches & Canyonlands National Parks, Utah)
2. Transcontinental Flight & Excursion (Mérida, Yucatán to Newark)
3. Universal Global Search (FTS5 Popover query for "National Park")
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from typing import Iterator

from PIL import Image
from playwright.sync_api import Browser, Playwright, sync_playwright

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from api.db import close_all_connections  # noqa: E402
from db import get_db_connection, init_db  # noqa: E402
from server import DaemonThreadingTCPServer, TimelineViewerHandler  # noqa: E402

OUTPUT_DIR = ROOT_DIR / "docs" / "screenshots"


def seed_synthetic_screenshot_db(db_path: Path) -> None:
    """Seeds an isolated synthetic dataset showcasing parks, flights, and FTS5 search."""
    db_str = str(db_path)
    init_db(db_str)
    conn = get_db_connection(db_str)
    c = conn.cursor()

    places = [
        (
            "ChIJ_demo_arches_vc",
            "Arches National Park Visitor Center",
            "Arches Entrance Rd, Moab, UT 84532",
            "PARK",
            "Arts & Entertainment",
            "Moab",
            "United States",
            1,
            38.6166,
            -109.6198,
            6,
            "2024-10-18T08:00:00-06:00",
            "2024-10-18T09:00:00-06:00",
            "2024-10-18",
            60.0,
            "DEMO_SYNTHETIC",
            5,
            "Red rock sandstone exhibits and trailhead orientation.",
            2,
            1,
        ),
        (
            "ChIJ_demo_delicate_arch",
            "Delicate Arch — Arches National Park",
            "Delicate Arch Trail, Moab, UT 84532",
            "PARK",
            "Arts & Entertainment",
            "Moab",
            "United States",
            1,
            38.7436,
            -109.4993,
            4,
            "2024-10-18T10:30:00-06:00",
            "2024-10-18T12:30:00-06:00",
            "2024-10-18",
            120.0,
            "DEMO_SYNTHETIC",
            5,
            "Iconic freestanding natural sandstone amphitheater arch.",
            3,
            1,
        ),
        (
            "ChIJ_demo_canyonlands_mesa",
            "Mesa Arch — Canyonlands National Park",
            "Grand View Point Rd, Moab, UT 84532",
            "PARK",
            "Arts & Entertainment",
            "Moab",
            "United States",
            1,
            38.3889,
            -109.8636,
            3,
            "2024-10-18T14:00:00-06:00",
            "2024-10-18T16:30:00-06:00",
            "2024-10-18",
            150.0,
            "DEMO_SYNTHETIC",
            5,
            "Dramatic cliff-edge arch framing Washer Woman Spire.",
            2,
            1,
        ),
        (
            "ChIJ_demo_moab_bistro",
            "Canyon Rim Trailhead Café",
            "120 N Main St, Moab, UT 84532",
            "RESTAURANT",
            "Food & Drink",
            "Moab",
            "United States",
            1,
            38.5738,
            -109.5508,
            5,
            "2024-10-18T17:30:00-06:00",
            "2024-10-18T19:00:00-06:00",
            "2024-10-18",
            90.0,
            "DEMO_SYNTHETIC",
            5,
            "Post-hike southwest bowls and espresso.",
            1,
            1,
        ),
        (
            "ChIJ_demo_merida_plaza",
            "Plaza Grande Historic Center",
            "Calle 60, Centro, 97000 Mérida, Yuc., Mexico",
            "PARK",
            "Arts & Entertainment",
            "Mérida",
            "Mexico",
            1,
            20.9671,
            -89.6237,
            4,
            "2025-02-14T08:30:00-06:00",
            "2025-02-14T10:15:00-06:00",
            "2025-02-14",
            105.0,
            "DEMO_SYNTHETIC",
            5,
            "Laurel-shaded central plaza surrounded by limestone arcades.",
            1,
            1,
        ),
        (
            "ChIJ_demo_mid_airport",
            "Mérida International Airport (MID)",
            " Carretera Mérida-Campeche Km 4.5, Mérida, Mexico",
            "AIRPORT",
            "Travel & Transit",
            "Mérida",
            "Mexico",
            1,
            20.9370,
            -89.6577,
            2,
            "2025-02-14T10:45:00-06:00",
            "2025-02-14T12:15:00-06:00",
            "2025-02-14",
            90.0,
            "DEMO_SYNTHETIC",
            4,
            "Regional terminal serving the Yucatán Peninsula.",
            1,
            1,
        ),
        (
            "ChIJ_demo_ewr_airport",
            "Newark Liberty International Airport (EWR)",
            "3 Brewster Rd, Newark, NJ 07114",
            "AIRPORT",
            "Travel & Transit",
            "Newark",
            "United States",
            1,
            40.6895,
            -74.1745,
            9,
            "2025-02-14T17:10:00-05:00",
            "2025-02-14T18:00:00-05:00",
            "2025-02-14",
            50.0,
            "DEMO_SYNTHETIC",
            4,
            "International arrivals concourse and AirTrain link.",
            1,
            1,
        ),
        (
            "ChIJ_demo_nwk_penn",
            "Newark Penn Station",
            "1 Raymond Plaza W, Newark, NJ 07102",
            "TRANSIT_STATION",
            "Travel & Transit",
            "Newark",
            "United States",
            1,
            40.7347,
            -74.1642,
            7,
            "2025-02-14T18:25:00-05:00",
            "2025-02-14T19:00:00-05:00",
            "2025-02-14",
            35.0,
            "DEMO_SYNTHETIC",
            4,
            "Art Deco rail hub on the Northeast Corridor.",
            1,
            1,
        ),
        (
            "ChIJ_demo_zion_np",
            "Zion National Park — Angels Landing",
            "1 Zion Park Blvd, Springdale, UT 84767",
            "PARK",
            "Arts & Entertainment",
            "Springdale",
            "United States",
            1,
            37.2692,
            -112.9471,
            5,
            "2024-10-15T09:00:00-06:00",
            "2024-10-15T15:00:00-06:00",
            "2024-10-15",
            240.0,
            "DEMO_SYNTHETIC",
            5,
            "Towering Navajo sandstone canyon walls along the Virgin River.",
            2,
            1,
        ),
        (
            "ChIJ_demo_yosemite_np",
            "Yosemite National Park — Tunnel View",
            "Wawona Rd, Yosemite Valley, CA 95389",
            "PARK",
            "Arts & Entertainment",
            "Yosemite Valley",
            "United States",
            1,
            37.7156,
            -119.6776,
            6,
            "2024-06-10T08:30:00-07:00",
            "2024-06-10T14:00:00-07:00",
            "2024-06-10",
            180.0,
            "DEMO_SYNTHETIC",
            5,
            "Granite panorama of El Capitan, Half Dome, and Bridalveil Fall.",
            3,
            1,
        ),
        (
            "ChIJ_demo_banff_np",
            "Banff National Park — Lake Louise",
            "111 Lake Louise Dr, Lake Louise, AB, Canada",
            "PARK",
            "Arts & Entertainment",
            "Banff",
            "Canada",
            1,
            51.4167,
            -116.2167,
            3,
            "2024-08-21T09:00:00-06:00",
            "2024-08-21T13:30:00-06:00",
            "2024-08-21",
            210.0,
            "DEMO_SYNTHETIC",
            5,
            "Turquoise glacial lake framed by Victoria Glacier.",
            2,
            1,
        ),
        (
            "ChIJ_demo_acadia_np",
            "Acadia National Park — Cadillac Summit",
            "Cadillac Mountain Rd, Bar Harbor, ME 04609",
            "PARK",
            "Arts & Entertainment",
            "Bar Harbor",
            "United States",
            1,
            44.3526,
            -68.2251,
            4,
            "2024-09-12T06:30:00-04:00",
            "2024-09-12T10:30:00-04:00",
            "2024-09-12",
            120.0,
            "DEMO_SYNTHETIC",
            5,
            "Pink granite coastal ridges overlooking Frenchman Bay.",
            1,
            1,
        ),
    ]

    c.executemany(
        """
        INSERT OR REPLACE INTO places (
            place_id, name, address, semantic_type, category, city, country,
            user_confirmed, latitude, longitude, visit_count, first_visit_time,
            last_visit_time, latest_visit_date, median_dwell_minutes, source,
            review_rating, review_text, review_count, has_review
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        places,
    )

    drive_vc_to_delicate = json.dumps(
        [
            [38.6166, -109.6198],
            [38.6425, -109.6050],
            [38.6850, -109.5690],
            [38.7180, -109.5420],
            [38.7356, -109.5205],
            [38.7436, -109.4993],
        ]
    )
    drive_delicate_to_mesa = json.dumps(
        [
            [38.7436, -109.4993],
            [38.6650, -109.5850],
            [38.6020, -109.6310],
            [38.5450, -109.7280],
            [38.4680, -109.8120],
            [38.3889, -109.8636],
        ]
    )
    drive_mesa_to_moab = json.dumps(
        [
            [38.3889, -109.8636],
            [38.4720, -109.7950],
            [38.5560, -109.6710],
            [38.5738, -109.5508],
        ]
    )
    drive_merida_to_mid = json.dumps(
        [
            [20.9671, -89.6237],
            [20.9550, -89.6390],
            [20.9460, -89.6495],
            [20.9370, -89.6577],
        ]
    )
    flight_mid_to_ewr = json.dumps(
        [
            [20.9370, -89.6577],
            [24.4500, -86.9000],
            [28.6000, -83.4000],
            [32.9500, -79.8000],
            [36.8500, -76.7500],
            [40.6895, -74.1745],
        ]
    )
    rail_ewr_to_nwk = json.dumps(
        [
            [40.6895, -74.1745],
            [40.7080, -74.1695],
            [40.7220, -74.1665],
            [40.7347, -74.1642],
        ]
    )

    segments = [
        # --- Day 1: 2024-10-18 (Utah National Parks Loop) ---
        (
            "visit",
            "2024-10-18T08:00:00-06:00",
            "2024-10-18T09:00:00-06:00",
            1729260000.0,
            1729263600.0,
            60.0,
            "2024-10-18",
            2024,
            10,
            18,
            38.6166,
            -109.6198,
            None,
            None,
            "ChIJ_demo_arches_vc",
            "Arches National Park Visitor Center",
            "Arches Entrance Rd, Moab, UT 84532",
            "PARK",
            "Arts & Entertainment",
            "Moab",
            None,
            0.0,
            0.0,
            1.0,
            0,
            None,
            0,
            0,
            "DEMO_SYNTHETIC",
        ),
        (
            "activity",
            "2024-10-18T09:00:00-06:00",
            "2024-10-18T09:40:00-06:00",
            1729263600.0,
            1729266000.0,
            40.0,
            "2024-10-18",
            2024,
            10,
            18,
            38.6166,
            -109.6198,
            38.7436,
            -109.4993,
            None,
            None,
            None,
            None,
            "Travel & Transit",
            "Moab",
            "IN_PASSENGER_VEHICLE",
            28400.0,
            28400.0,
            1.0,
            0,
            drive_vc_to_delicate,
            1,
            0,
            "DEMO_SYNTHETIC",
        ),
        (
            "visit",
            "2024-10-18T09:40:00-06:00",
            "2024-10-18T12:20:00-06:00",
            1729266000.0,
            1729275600.0,
            160.0,
            "2024-10-18",
            2024,
            10,
            18,
            38.7436,
            -109.4993,
            None,
            None,
            "ChIJ_demo_delicate_arch",
            "Delicate Arch — Arches National Park",
            "Delicate Arch Trail, Moab, UT 84532",
            "PARK",
            "Arts & Entertainment",
            "Moab",
            None,
            0.0,
            0.0,
            1.0,
            0,
            None,
            0,
            0,
            "DEMO_SYNTHETIC",
        ),
        (
            "activity",
            "2024-10-18T12:20:00-06:00",
            "2024-10-18T13:35:00-06:00",
            1729275600.0,
            1729280100.0,
            75.0,
            "2024-10-18",
            2024,
            10,
            18,
            38.7436,
            -109.4993,
            38.3889,
            -109.8636,
            None,
            None,
            None,
            None,
            "Travel & Transit",
            "Moab",
            "IN_PASSENGER_VEHICLE",
            67500.0,
            67500.0,
            1.0,
            0,
            drive_delicate_to_mesa,
            1,
            0,
            "DEMO_SYNTHETIC",
        ),
        (
            "visit",
            "2024-10-18T13:35:00-06:00",
            "2024-10-18T16:15:00-06:00",
            1729280100.0,
            1729289700.0,
            160.0,
            "2024-10-18",
            2024,
            10,
            18,
            38.3889,
            -109.8636,
            None,
            None,
            "ChIJ_demo_canyonlands_mesa",
            "Mesa Arch — Canyonlands National Park",
            "Grand View Point Rd, Moab, UT 84532",
            "PARK",
            "Arts & Entertainment",
            "Moab",
            None,
            0.0,
            0.0,
            1.0,
            0,
            None,
            0,
            0,
            "DEMO_SYNTHETIC",
        ),
        (
            "activity",
            "2024-10-18T16:15:00-06:00",
            "2024-10-18T17:10:00-06:00",
            1729289700.0,
            1729293000.0,
            55.0,
            "2024-10-18",
            2024,
            10,
            18,
            38.3889,
            -109.8636,
            38.5738,
            -109.5508,
            None,
            None,
            None,
            None,
            "Travel & Transit",
            "Moab",
            "IN_PASSENGER_VEHICLE",
            51200.0,
            51200.0,
            1.0,
            0,
            drive_mesa_to_moab,
            1,
            0,
            "DEMO_SYNTHETIC",
        ),
        (
            "visit",
            "2024-10-18T17:10:00-06:00",
            "2024-10-18T19:00:00-06:00",
            1729293000.0,
            1729299600.0,
            110.0,
            "2024-10-18",
            2024,
            10,
            18,
            38.5738,
            -109.5508,
            None,
            None,
            "ChIJ_demo_moab_bistro",
            "Canyon Rim Trailhead Café",
            "120 N Main St, Moab, UT 84532",
            "RESTAURANT",
            "Food & Drink",
            "Moab",
            None,
            0.0,
            0.0,
            1.0,
            0,
            None,
            0,
            0,
            "DEMO_SYNTHETIC",
        ),
        # --- Day 2: 2025-02-14 (Mérida Yucatán -> Newark Flight) ---
        (
            "visit",
            "2025-02-14T08:30:00-06:00",
            "2025-02-14T10:15:00-06:00",
            1739543400.0,
            1739549700.0,
            105.0,
            "2025-02-14",
            2025,
            2,
            14,
            20.9671,
            -89.6237,
            None,
            None,
            "ChIJ_demo_merida_plaza",
            "Plaza Grande Historic Center",
            "Calle 60, Centro, 97000 Mérida, Yuc., Mexico",
            "PARK",
            "Arts & Entertainment",
            "Mérida",
            None,
            0.0,
            0.0,
            1.0,
            0,
            None,
            0,
            0,
            "DEMO_SYNTHETIC",
        ),
        (
            "activity",
            "2025-02-14T10:15:00-06:00",
            "2025-02-14T10:45:00-06:00",
            1739549700.0,
            1739551500.0,
            30.0,
            "2025-02-14",
            2025,
            2,
            14,
            20.9671,
            -89.6237,
            20.9370,
            -89.6577,
            None,
            None,
            None,
            None,
            "Travel & Transit",
            "Mérida",
            "IN_PASSENGER_VEHICLE",
            7400.0,
            7400.0,
            1.0,
            0,
            drive_merida_to_mid,
            1,
            0,
            "DEMO_SYNTHETIC",
        ),
        (
            "visit",
            "2025-02-14T10:45:00-06:00",
            "2025-02-14T12:15:00-06:00",
            1739551500.0,
            1739556900.0,
            90.0,
            "2025-02-14",
            2025,
            2,
            14,
            20.9370,
            -89.6577,
            None,
            None,
            "ChIJ_demo_mid_airport",
            "Mérida International Airport (MID)",
            "Carretera Mérida-Campeche Km 4.5, Mérida, Mexico",
            "AIRPORT",
            "Travel & Transit",
            "Mérida",
            None,
            0.0,
            0.0,
            1.0,
            0,
            None,
            0,
            0,
            "DEMO_SYNTHETIC",
        ),
        (
            "activity",
            "2025-02-14T12:15:00-06:00",
            "2025-02-14T17:10:00-05:00",
            1739556900.0,
            1739571000.0,
            235.0,
            "2025-02-14",
            2025,
            2,
            14,
            20.9370,
            -89.6577,
            40.6895,
            -74.1745,
            None,
            None,
            None,
            None,
            "Travel & Transit",
            "Newark",
            "FLYING",
            2485000.0,
            2485000.0,
            1.0,
            0,
            flight_mid_to_ewr,
            1,
            0,
            "DEMO_SYNTHETIC",
        ),
        (
            "visit",
            "2025-02-14T17:10:00-05:00",
            "2025-02-14T18:00:00-05:00",
            1739571000.0,
            1739574000.0,
            50.0,
            "2025-02-14",
            2025,
            2,
            14,
            40.6895,
            -74.1745,
            None,
            None,
            "ChIJ_demo_ewr_airport",
            "Newark Liberty International Airport (EWR)",
            "3 Brewster Rd, Newark, NJ 07114",
            "AIRPORT",
            "Travel & Transit",
            "Newark",
            None,
            0.0,
            0.0,
            1.0,
            0,
            None,
            0,
            0,
            "DEMO_SYNTHETIC",
        ),
        (
            "activity",
            "2025-02-14T18:00:00-05:00",
            "2025-02-14T18:25:00-05:00",
            1739574000.0,
            1739575500.0,
            25.0,
            "2025-02-14",
            2025,
            2,
            14,
            40.6895,
            -74.1745,
            40.7347,
            -74.1642,
            None,
            None,
            None,
            None,
            "Travel & Transit",
            "Newark",
            "IN_TRAIN",
            7200.0,
            7200.0,
            1.0,
            0,
            rail_ewr_to_nwk,
            1,
            0,
            "DEMO_SYNTHETIC",
        ),
        (
            "visit",
            "2025-02-14T18:25:00-05:00",
            "2025-02-14T19:00:00-05:00",
            1739575500.0,
            1739577600.0,
            35.0,
            "2025-02-14",
            2025,
            2,
            14,
            40.7347,
            -74.1642,
            None,
            None,
            "ChIJ_demo_nwk_penn",
            "Newark Penn Station",
            "1 Raymond Plaza W, Newark, NJ 07102",
            "TRANSIT_STATION",
            "Travel & Transit",
            "Newark",
            None,
            0.0,
            0.0,
            1.0,
            0,
            None,
            0,
            0,
            "DEMO_SYNTHETIC",
        ),
    ]

    c.executemany(
        """
        INSERT INTO segments (
            segment_type, start_time, end_time, start_ts, end_ts, duration_minutes,
            date, year, month, day, latitude, longitude, end_lat, end_lng,
            place_id, place_name, place_address, semantic_type, category, city,
            activity_type, distance_meters, clean_distance_meters, probability,
            hierarchy_level, path_points_json, has_snapped_path, is_unconfirmed, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        segments,
    )

    c.executemany(
        """
        INSERT OR REPLACE INTO trips (
            trip_id, title, country, country_flag, theme, start_date, end_date,
            start_ts, end_ts, duration_days, total_distance_km, flights_count,
            visits_count, activities_count, highlights_json, is_inferred
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        [
            (
                "demo_trip_utah_parks",
                "Utah Mighty Five National Parks Expedition",
                "United States",
                "🇺🇸",
                "NATIONAL_PARKS",
                "2024-10-15",
                "2024-10-20",
                1729000800.0,
                1729432800.0,
                5.0,
                642.0,
                0,
                12,
                9,
                json.dumps(
                    [
                        "Arches National Park",
                        "Delicate Arch",
                        "Mesa Arch — Canyonlands National Park",
                        "Zion National Park",
                    ]
                ),
                1,
            ),
            (
                "demo_trip_yucatan_flight",
                "Yucatán Cultural Week & Return Flight",
                "Mexico",
                "🇲🇽",
                "INTERNATIONAL",
                "2025-02-10",
                "2025-02-14",
                1739197800.0,
                1739577600.0,
                4.0,
                2510.0,
                1,
                8,
                6,
                json.dumps(
                    [
                        "Plaza Grande Historic Center",
                        "Mérida International Airport (MID)",
                        "Newark Liberty International Airport (EWR)",
                    ]
                ),
                1,
            ),
        ],
    )

    c.execute("INSERT INTO places_fts(places_fts) VALUES('rebuild')")
    conn.commit()
    conn.close()


@contextlib.contextmanager
def ephemeral_demo_server() -> Iterator[str]:
    """Starts an ephemeral local HTTP server backed by a temporary synthetic SQLite DB."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="mylifebits_screenshots_"))
    db_file = tmp_dir / "synthetic_screenshots.db"
    prev_db_env = os.environ.get("TIMELINE_DB_PATH")

    seed_synthetic_screenshot_db(db_file)
    close_all_connections()
    os.environ["TIMELINE_DB_PATH"] = str(db_file)

    loopback_host = "127.0.0.1"
    httpd = DaemonThreadingTCPServer((loopback_host, 0), TimelineViewerHandler)
    bound_host, bound_port = httpd.server_address[0], httpd.server_address[1]
    host_str = bound_host.decode("utf-8") if isinstance(bound_host, bytes) else str(bound_host)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    try:
        yield f"http://{host_str}:{bound_port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        close_all_connections()
        if prev_db_env is None:
            os.environ.pop("TIMELINE_DB_PATH", None)
        else:
            os.environ["TIMELINE_DB_PATH"] = prev_db_env
        shutil.rmtree(tmp_dir, ignore_errors=True)


def launch_browser(playwright: Playwright) -> Browser:
    """Launches headless Chromium, preferring installed Chrome when available."""
    launch_args = ["--ignore-certificate-errors", "--disable-gpu"]
    try:
        return playwright.chromium.launch(
            channel="chrome",
            headless=True,
            args=launch_args,
        )
    except Exception:
        return playwright.chromium.launch(headless=True, args=launch_args)


def optimize_image(src_path: Path, max_width: int = 1440) -> None:
    """Resizes and compresses PNG image for crisp rendering and compact file size."""
    with Image.open(src_path) as img:
        rgb_img: Image.Image = img.convert("RGB")
        if rgb_img.width > max_width:
            ratio = max_width / float(rgb_img.width)
            new_height = int(float(rgb_img.height) * ratio)
            rgb_img = rgb_img.resize((max_width, new_height), Image.Resampling.LANCZOS)
        rgb_img.save(src_path, format="PNG", optimize=True)


def capture_screenshots(base_url: str, day_parks: str, day_flight: str) -> None:
    """Navigates the UI via Playwright and writes the three documentation screenshots."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    page_errors: list[str] = []

    print("[*] Launching headless browser for documentation screenshots...")
    with sync_playwright() as p:
        browser = launch_browser(p)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=2,
            ignore_https_errors=True,
        )
        page = context.new_page()
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on(
            "console",
            lambda msg: page_errors.append(msg.text) if msg.type == "error" else None,
        )

        # 1. Timeline Day View: Arches & Canyonlands National Parks
        print(f"    [1/3] Capturing Timeline Day View ({day_parks})...")
        page.goto(f"{base_url}/?date={day_parks}", wait_until="networkidle")
        page.wait_for_selector("#itinerary-container .segment-card", timeout=8000)
        page.wait_for_timeout(1800)
        shot1 = OUTPUT_DIR / "timeline_day_view.png"
        page.screenshot(path=str(shot1))
        optimize_image(shot1)

        # 2. Transcontinental Flight & Trip (Mérida Yucatán to Newark)
        print(f"    [2/3] Capturing Transcontinental Flight & Travel Day ({day_flight})...")
        page.goto(f"{base_url}/?date={day_flight}", wait_until="networkidle")
        page.wait_for_selector("#itinerary-container .segment-card", timeout=8000)
        page.wait_for_timeout(1800)
        shot2 = OUTPUT_DIR / "timeline_flight_trip.png"
        page.screenshot(path=str(shot2))
        optimize_image(shot2)

        # 3. Universal Global Search Dropdown (Top-Layer Popover + FTS5)
        print("    [3/3] Capturing Universal Global Search ('National Park' query)...")
        page.goto(f"{base_url}/?date={day_parks}", wait_until="networkidle")
        page.wait_for_selector("#global-search-input", timeout=8000)
        page.click("#global-search-input")
        page.fill("#global-search-input", "National Park")
        page.wait_for_selector("#global-search-dropdown .search-result-item", timeout=6000)
        page.wait_for_timeout(800)
        shot3 = OUTPUT_DIR / "universal_search.png"
        page.screenshot(path=str(shot3))
        optimize_image(shot3)

        browser.close()

    if page_errors:
        raise RuntimeError(f"Browser console/page errors detected during capture: {page_errors}")

    print("[✓] All screenshots generated cleanly in docs/screenshots/:")
    for f in (shot1, shot2, shot3):
        size_kb = f.stat().st_size / 1024.0
        print(f"    - {f.name} ({size_kb:.1f} KB)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate privacy-clean documentation screenshots via Playwright.")
    parser.add_argument(
        "--live-url",
        type=str,
        default="",
        help="Optional live server URL (defaults to ephemeral synthetic demo server).",
    )
    args = parser.parse_args()

    if args.live_url:
        capture_screenshots(args.live_url.rstrip("/"), "2010-11-22", "2017-01-14")
    else:
        with ephemeral_demo_server() as demo_url:
            capture_screenshots(demo_url, "2024-10-18", "2025-02-14")


if __name__ == "__main__":
    main()
