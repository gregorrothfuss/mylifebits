"""
LinkedIn-Style Residency, Education, and Career Chronology Engine (1976 – Present).

Manages temporal 'From -> To' life periods for Home, Education, and Work locations, and provides
dynamic, date-aware labeling for all historical visits across your lifetime.
"""

import sqlite3
import datetime
from typing import List, Dict, Any, Optional, Tuple
from breadcrumbs import haversine_distance


DEFAULT_PERIODS = [
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
        "description": "Primary Home Residence"
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
        "description": "Engineering Office"
    }
]


def init_life_periods_table(db_path: str, force_reseed: bool = False):
    """Initializes the life_periods table and seeds the complete 50-year chronology."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    c.execute("""
    CREATE TABLE IF NOT EXISTS life_periods (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        type TEXT NOT NULL,           -- 'HOME', 'EDUCATION', or 'WORK'
        role_title TEXT,
        address TEXT,
        start_date TEXT NOT NULL,     -- 'YYYY-MM-DD'
        end_date TEXT NOT NULL,       -- 'YYYY-MM-DD'
        lat REAL NOT NULL,
        lng REAL NOT NULL,
        is_current INTEGER DEFAULT 0,
        description TEXT
    );
    """)
    
    c.execute("SELECT COUNT(*) FROM life_periods;")
    cnt = c.fetchone()[0]
    if cnt == 0 or force_reseed:
        c.execute("DELETE FROM life_periods;")
        for p in DEFAULT_PERIODS:
            c.execute("""
            INSERT INTO life_periods (
                name, type, role_title, address, start_date, end_date, lat, lng, is_current, description
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                p["name"], p["type"], p["role_title"], p["address"],
                p["start_date"], p["end_date"], p["lat"], p["lng"],
                p["is_current"], p["description"]
            ))
        conn.commit()
        
    conn.close()


def get_all_life_periods(db_path: str) -> List[Dict[str, Any]]:
    """Returns all residency, education, and career periods sorted chronologically."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    init_life_periods_table(db_path)
    c.execute("SELECT * FROM life_periods ORDER BY start_date DESC;")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_date_aware_label(
    db_path: str,
    raw_name: Optional[str],
    lat: Optional[float],
    lng: Optional[float],
    visit_date: str
) -> Tuple[Optional[str], Optional[str]]:
    """
    Returns (date_aware_title, category) for a visit based on the user's historical life period.
    """
    if lat is None or lng is None:
        return None, None

    if raw_name:
        name_clean = raw_name.strip()
        generic_names = ['place', 'home/place', 'unconfirmed location', 'point of interest', 'type_home', 'location']
        is_generic = any(name_clean.lower() == g or name_clean.lower().startswith('location (') for g in generic_names)
        is_explicit_home = name_clean.lower().startswith('home') or name_clean.lower().startswith('work')
        
        if not is_generic and not is_explicit_home:
            return None, None

    periods = get_all_life_periods(db_path)
    
    for p in periods:
        dist_m = haversine_distance(lat, lng, p["lat"], p["lng"])
        if dist_m <= 50.0:
            is_active_period = (p["start_date"] <= visit_date <= p["end_date"])
            
            if is_active_period:
                if p["type"] == "HOME":
                    return f"Home ({p['name']})", "Home & Residence"
                elif p["type"] == "EDUCATION":
                    return f"{p['name']}", "Services & Civic"
                elif p["type"] == "WORK":
                    return f"Work ({p['name']})", "Work & Office"
                    
    return None, None
