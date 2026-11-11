"""
Hermetic SQLite Test Fixture for End-to-End & Integration Verification.

Guarantees:
1. Zero contact with or mutation of any production/local database (e.g., timeline_viewer.db).
2. Deterministic synthetic multi-day, multi-timezone, zero-PII dataset exercising:
   - Visited places (visit_count >= 1) and zero-visit clutter places (visit_count = 0)
   - Cross-midnight continuous overnight stays
   - Road-snapped activities across 2024 and 2026 periods (WALKING, CYCLING, IN_SUBWAY, FLYING)
   - Pending, accepted, and rejected fix proposals
   - Gaps, raw signals, breadcrumbs, trips, country stats, life periods, and reviews
3. Emits repeatable JSON verification artifacts to .agent/scratch/e2e_verification_artifact.json.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from db import get_db_connection, init_db
from scripts.init_db import populate_demo_data

REPO_ROOT = Path(__file__).resolve().parent.parent


def create_hermetic_db(target_path: Optional[Path] = None) -> Path:
    """Creates and seeds an isolated WAL SQLite database for E2E testing."""
    if target_path is None:
        tmp_dir = Path(tempfile.mkdtemp(prefix="mylifebits_hermetic_"))
        db_file = tmp_dir / "hermetic_timeline.db"
    else:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        db_file = target_path

    db_str = str(db_file)
    init_db(db_str)
    populate_demo_data(db_str)

    conn = get_db_connection(db_str)
    c = conn.cursor()

    # Seed deterministic historical dates (2024-10-01..2024-10-03 and 2026-06-15) for E2E contracts
    c.execute(
        """
        INSERT OR REPLACE INTO places (
            place_id, name, address, semantic_type, category, city, country,
            user_confirmed, latitude, longitude, visit_count, first_visit_time,
            last_visit_time, latest_visit_date, median_dwell_minutes, source,
            review_rating, review_text, review_count, has_review, review_photos
        ) VALUES
        (
            'ChIJmQJIxlVYwokRLgeuocVOGVU', 'Central Station Plaza', '89 E 42nd St, New York, NY 10017',
            'TRANSIT_STATION', 'Travel & Transit', 'New York', 'United States',
            1, 40.7527, -73.9772, 8, '2024-10-01T09:00:00-04:00',
            '2026-06-15T18:30:00-04:00', '2026-06-15', 45.0, 'HERMETIC_SEED',
            5, 'Iconic concourse architecture.', 1, 1, '["https://lh3.googleusercontent.com/example_photo_1"]'
        ),
        (
            'ChIJ4zGFAZpYwokRGUGph3Mf37k', 'Central Park Conservatory', '105th St & 5th Ave, New York, NY 10029',
            'PARK', 'Arts & Entertainment', 'New York', 'United States',
            1, 40.7942, -73.9525, 4, '2024-10-01T12:00:00-04:00',
            '2026-06-15T15:00:00-04:00', '2026-06-15', 90.0, 'HERMETIC_SEED',
            5, 'Peaceful formal gardens.', 1, 1, '[]'
        ),
        (
            'ChIJGaK-SZcLkEcRA9wf5_GNbuY', 'Café Zürich Hauptbahnhof', 'Bahnhofplatz, 8001 Zürich, Switzerland',
            'CAFE', 'Food & Drink', 'Zürich', 'Switzerland',
            1, 47.3779, 8.5402, 2, '2024-10-03T09:00:00+02:00',
            '2024-10-03T10:00:00+02:00', '2024-10-03', 60.0, 'HERMETIC_SEED',
            5, 'Fresh espresso near platforms.', 1, 1, '[]'
        ),
        (
            'ChIJ_zero_visit_clutter_01', 'Unvisited Ghost Catalog Entry', '999 Nowhere Rd',
            'OTHER', 'airport', 'Unknown', 'United States',
            0, 40.7000, -74.0000, 0, NULL,
            NULL, NULL, 0.0, 'HERMETIC_SEED',
            NULL, NULL, 0, 0, NULL
        );
        """
    )

    snapped_curve = json.dumps([
        [40.7527, -73.9772],
        [40.7680, -73.9680],
        [40.7810, -73.9600],
        [40.7942, -73.9525],
    ])

    # 2024-10-01 visits + activity + cross-midnight stay into 2024-10-02
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
        [
            (
                "visit", "2024-10-01T09:00:00-04:00", "2024-10-01T10:30:00-04:00",
                1727787600.0, 1727793000.0, 90.0, "2024-10-01", 2024, 10, 1,
                40.7527, -73.9772, None, None, "ChIJmQJIxlVYwokRLgeuocVOGVU",
                "Central Station Plaza", "89 E 42nd St, New York, NY 10017",
                "TRANSIT_STATION", "Travel & Transit", "New York",
                None, 0.0, 0.0, 1.0, 0, None, 0, 0, "HERMETIC_SEED",
            ),
            (
                "activity", "2024-10-01T10:30:00-04:00", "2024-10-01T11:00:00-04:00",
                1727793000.0, 1727794800.0, 30.0, "2024-10-01", 2024, 10, 1,
                40.7527, -73.9772, 40.7942, -73.9525, None, None, None, None,
                "Travel & Transit", "New York", "CYCLING", 5100.0, 5100.0, 1.0,
                0, snapped_curve, 1, 0, "HERMETIC_SEED",
            ),
            (
                "visit", "2024-10-01T11:00:00-04:00", "2024-10-01T13:00:00-04:00",
                1727794800.0, 1727802000.0, 120.0, "2024-10-01", 2024, 10, 1,
                40.7942, -73.9525, None, None, "ChIJ4zGFAZpYwokRGUGph3Mf37k",
                "Central Park Conservatory", "105th St & 5th Ave, New York, NY 10029",
                "PARK", "Arts & Entertainment", "New York",
                None, 0.0, 0.0, 1.0, 0, None, 0, 0, "HERMETIC_SEED",
            ),
            # Continuous overnight stay spanning 2024-10-01 22:00 -> 2024-10-02 07:30
            (
                "visit", "2024-10-01T22:00:00-04:00", "2024-10-02T07:30:00-04:00",
                1727834400.0, 1727868600.0, 570.0, "2024-10-01", 2024, 10, 1,
                42.3872, -71.1163, None, None, "ChIJ_demo_home_01",
                "Home (Highland Ave)", "124 Highland Ave, Somerville, MA",
                "TYPE_HOME", "Home & Residence", "Somerville",
                None, 0.0, 0.0, 1.0, 0, None, 0, 0, "HERMETIC_SEED",
            ),
            # 2026 activity & visit so period=2026 summaries & nuggets always have realistic modes
            (
                "activity", "2026-06-15T14:00:00-04:00", "2026-06-15T15:00:00-04:00",
                1781546400.0, 1781550000.0, 60.0, "2026-06-15", 2026, 6, 15,
                40.7527, -73.9772, 40.7942, -73.9525, None, None, None, None,
                "Travel & Transit", "New York", "WALKING", 5100.0, 5100.0, 1.0,
                0, snapped_curve, 1, 0, "HERMETIC_SEED",
            ),
            (
                "visit", "2026-06-15T15:00:00-04:00", "2026-06-15T18:30:00-04:00",
                1781550000.0, 1781562600.0, 210.0, "2026-06-15", 2026, 6, 15,
                40.7942, -73.9525, None, None, "ChIJ4zGFAZpYwokRGUGph3Mf37k",
                "Central Park Conservatory", "105th St & 5th Ave, New York, NY 10029",
                "PARK", "Arts & Entertainment", "New York",
                None, 0.0, 0.0, 1.0, 0, None, 0, 0, "HERMETIC_SEED",
            ),
            (
                "visit", "2024-10-03T09:00:00+02:00", "2024-10-03T10:00:00+02:00",
                1727938800.0, 1727942400.0, 60.0, "2024-10-03", 2024, 10, 3,
                47.3779, 8.5402, None, None, "ChIJGaK-SZcLkEcRA9wf5_GNbuY",
                "Café Zürich Hauptbahnhof", "Bahnhofplatz, 8001 Zürich, Switzerland",
                "CAFE", "Food & Drink", "Zürich",
                None, 0.0, 0.0, 1.0, 0, None, 0, 0, "HERMETIC_SEED",
            ),
        ],
    )

    # Seed gaps, raw_signals, and fix_proposals (PENDING, ACCEPTED, REJECTED)
    c.execute(
        """
        INSERT INTO gaps (
            start_time, end_time, start_ts, end_ts, duration_hours, date, year,
            prev_lat, prev_lng, next_lat, next_lng, jump_distance_km, status
        ) VALUES (
            '2024-10-01T13:00:00-04:00', '2024-10-01T15:30:00-04:00',
            1727802000.0, 1727811000.0, 2.5, '2024-10-01', 2024,
            40.7942, -73.9525, 40.7527, -73.9772, 5.1, 'OPEN'
        );
        """
    )
    gap_id = c.lastrowid

    c.execute(
        """
        INSERT INTO raw_signals (
            timestamp, ts, latitude, longitude, accuracy_meters, source, date, year
        ) VALUES (
            '2024-10-01T10:45:00Z', 1727793900.0, 40.7740, -73.9650, 8.5, 'GPS', '2024-10-01', 2024
        );
        """
    )

    now_iso = "2026-06-15T12:00:00Z"
    c.executemany(
        """
        INSERT INTO fix_proposals (
            target_type, target_id, date, proposed_action, source, reasoning,
            confidence, status, patch_data_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        [
            (
                "GAP", gap_id, "2024-10-01", "INSERT_VISIT", "PHOTOS_EXIF",
                "Geotagged photo cluster inside Central Station Plaza.", 0.92, "PENDING",
                json.dumps({
                    "place_id": "ChIJmQJIxlVYwokRLgeuocVOGVU",
                    "place_name": "Central Station Plaza",
                    "latitude": 40.7527,
                    "longitude": -73.9772,
                    "start_time": "2024-10-01T13:15:00-04:00",
                    "end_time": "2024-10-01T14:45:00-04:00",
                }),
                now_iso,
            ),
            (
                "GAP", gap_id, "2024-10-01", "INSERT_ACTIVITY", "ROUTING_OSRM",
                "Road-snapped return leg.", 0.88, "ACCEPTED",
                json.dumps({"activity_type": "SUBWAY"}),
                now_iso,
            ),
            (
                "GAP", gap_id, "2024-10-01", "INSERT_VISIT", "TAKEOUT_FUSION",
                "Low-confidence Wi-Fi ping.", 0.35, "REJECTED",
                json.dumps({"place_id": "ChIJ4zGFAZpYwokRGUGph3Mf37k"}),
                now_iso,
            ),
        ],
    )

    c.execute(
        """
        INSERT OR REPLACE INTO trips (
            trip_id, title, country, country_flag, theme, start_date, end_date,
            start_ts, end_ts, duration_days, total_distance_km,
            flights_count, visits_count, activities_count, highlights_json
        ) VALUES (
            'trip_hermetic_nyc_2024', 'New York Architecture Tour', 'United States', '🇺🇸',
            'CITY_BREAK', '2024-10-01', '2024-10-02', 1727787600.0, 1727868600.0,
            2.0, 12.4, 0, 3, 1, '["Central Station Plaza", "Central Park Conservatory"]'
        );
        """
    )

    conn.commit()
    conn.close()
    return db_file


@contextlib.contextmanager
def hermetic_db_environment() -> Iterator[Path]:
    """Context manager activating an isolated TIMELINE_DB_PATH and cleaning up on exit."""
    prev_env = os.environ.get("TIMELINE_DB_PATH")
    prod_db = REPO_ROOT / "timeline_viewer.db"
    prod_stat_before = (prod_db.stat().st_mtime_ns, prod_db.stat().st_size) if prod_db.exists() else None

    db_file = create_hermetic_db()
    os.environ["TIMELINE_DB_PATH"] = str(db_file)
    try:
        yield db_file
    finally:
        from api.db import close_all_connections

        close_all_connections()
        if prev_env is None:
            os.environ.pop("TIMELINE_DB_PATH", None)
        else:
            os.environ["TIMELINE_DB_PATH"] = prev_env
        shutil.rmtree(db_file.parent, ignore_errors=True)

        if prod_stat_before is not None and prod_db.exists():
            prod_stat_after = (prod_db.stat().st_mtime_ns, prod_db.stat().st_size)
            if prod_stat_after != prod_stat_before:
                raise AssertionError(
                    f"Hermeticity violation: timeline_viewer.db mutated during test! "
                    f"before={prod_stat_before}, after={prod_stat_after}"
                )


def write_verification_artifact(suite_name: str, details: Dict[str, Any]) -> Path:
    """Writes a repeatable E2E verification artifact to .agent/scratch/."""
    scratch_dir = REPO_ROOT / ".agent" / "scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = scratch_dir / "e2e_verification_artifact.json"
    existing: Dict[str, Any] = {}
    if artifact_path.exists():
        try:
            existing = json.loads(artifact_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    existing.setdefault("suites", {})[suite_name] = {
        "verified_at_epoch": round(time.time(), 3),
        **details,
    }
    artifact_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    return artifact_path
