"""
Lifetime Residency, Education, and Career Chronology Engine.

Manages temporal 'From -> To' life periods for Home, Education, and Work locations,
and provides dynamic, date-aware labeling for historical visits.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from breadcrumbs import haversine_distance
from db import get_db_connection

DEFAULT_PERIODS: List[Dict[str, Any]] = [
    {
        "name": "Urban Residence",
        "type": "HOME",
        "role_title": "Primary Residence",
        "address": "124 Highland Ave, Somerville, MA 02143, USA",
        "start_date": "2020-01-01",
        "end_date": "2030-12-31",
        "lat": 42.3872,
        "lng": -71.1163,
        "is_current": 1,
        "description": "Primary Home Residence",
    },
    {
        "name": "Tech Innovation Hub",
        "type": "WORK",
        "role_title": "Software Engineer",
        "address": "100 Binney St, Cambridge, MA 02142, USA",
        "start_date": "2020-01-01",
        "end_date": "2030-12-31",
        "lat": 42.3654,
        "lng": -71.0852,
        "is_current": 1,
        "description": "Engineering Office",
    },
]


def init_life_periods_table(db_path: str, force_reseed: bool = False) -> None:
    """Initializes the life_periods table and optionally seeds synthetic demo periods."""
    conn = get_db_connection(db_path, readonly=False)
    try:
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS life_periods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                role_title TEXT,
                address TEXT,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                lat REAL NOT NULL,
                lng REAL NOT NULL,
                is_current INTEGER DEFAULT 0,
                description TEXT
            );
            """
        )
        c.execute("SELECT COUNT(*) FROM life_periods;")
        cnt = int(c.fetchone()[0])
        if cnt == 0 or force_reseed:
            c.execute("DELETE FROM life_periods;")
            for p in DEFAULT_PERIODS:
                c.execute(
                    """
                    INSERT INTO life_periods (
                        name, type, role_title, address, start_date, end_date,
                        lat, lng, is_current, description
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        p["name"],
                        p["type"],
                        p["role_title"],
                        p["address"],
                        p["start_date"],
                        p["end_date"],
                        p["lat"],
                        p["lng"],
                        p["is_current"],
                        p["description"],
                    ),
                )
            conn.commit()
    finally:
        conn.close()


def get_all_life_periods(
    db_path: str,
    conn: Optional[sqlite3.Connection] = None,
) -> List[Dict[str, Any]]:
    """Returns all residency, education, and career periods sorted chronologically."""
    owns_conn = conn is None
    active_conn = conn if conn is not None else get_db_connection(db_path, readonly=True)
    try:
        c = active_conn.cursor()
        try:
            c.execute("SELECT * FROM life_periods ORDER BY start_date DESC;")
            rows = [dict(r) for r in c.fetchall()]
        except sqlite3.OperationalError:
            rows = []
        finally:
            c.close()
        return rows
    finally:
        if owns_conn:
            active_conn.close()


def get_date_aware_label(
    db_path: str,
    raw_name: Optional[str],
    lat: Optional[float],
    lng: Optional[float],
    visit_date: str,
    *,
    periods: Optional[List[Dict[str, Any]]] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Returns (date_aware_title, category) for a visit based on historical life periods."""
    if lat is None or lng is None:
        return None, None

    if raw_name:
        name_clean = raw_name.strip()
        low = name_clean.lower()
        generic_names = (
            "place",
            "home/place",
            "unconfirmed location",
            "point of interest",
            "type_home",
            "location",
        )
        is_generic = any(low == g or low.startswith("location (") for g in generic_names)
        is_explicit_home = low.startswith("home") or low.startswith("work")
        if not is_generic and not is_explicit_home:
            return None, None

    active_periods = periods if periods is not None else get_all_life_periods(db_path, conn=conn)
    for p in active_periods:
        dist_m = haversine_distance(lat, lng, p["lat"], p["lng"])
        if dist_m <= 50.0 and p["start_date"] <= visit_date <= p["end_date"]:
            if p["type"] == "HOME":
                return f"Home ({p['name']})", "Home & Residence"
            if p["type"] == "EDUCATION":
                return f"{p['name']}", "Services & Civic"
            if p["type"] == "WORK":
                return f"Work ({p['name']})", "Work & Office"

    return None, None
