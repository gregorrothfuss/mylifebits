"""
Database schema, connection management, migrations, and indexing for Google Maps Timeline Viewer.
Includes POI Contributor Reviews, Broad Category taxonomy, and City clustering.
"""

import sqlite3
import os
from typing import Optional, Dict, Any, List

def _resolve_default_db_path() -> str:
    env_path = os.environ.get("TIMELINE_DB_PATH")
    if env_path:
        return os.path.abspath(env_path)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    legacy_path = os.path.join(base_dir, "timeline_viewer.db")
    if os.path.exists(legacy_path):
        return legacy_path
    return os.path.join(base_dir, "timeline.db")


DEFAULT_DB_PATH = _resolve_default_db_path()


def get_db_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Returns a SQLite connection with row factory, 30s busy timeout, and WAL mode enabled."""
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _add_col_if_missing(c: sqlite3.Cursor, table: str, col_def: str) -> None:
    """Helper to safely add columns to existing SQLite tables."""
    try:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {col_def};")
    except sqlite3.OperationalError:
        pass


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Initializes the database schema, tables, migrations, and indexes."""
    conn = get_db_connection(db_path)
    c = conn.cursor()

    # 1. Sources Table (Tracking imported archives and exports)
    c.execute("""
    CREATE TABLE IF NOT EXISTS sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_name TEXT UNIQUE,
        file_path TEXT,
        imported_at TEXT,
        record_count INTEGER DEFAULT 0,
        metadata_json TEXT
    );
    """)

    # 2. Places Catalog (Unified deduplicated places with Categories, Cities, and Reviews)
    c.execute("""
    CREATE TABLE IF NOT EXISTS places (
        place_id TEXT PRIMARY KEY,
        name TEXT,
        address TEXT,
        semantic_type TEXT,
        category TEXT DEFAULT 'Other / POI',
        city TEXT,
        country TEXT,
        user_confirmed INTEGER DEFAULT 0,
        latitude REAL,
        longitude REAL,
        visit_count INTEGER DEFAULT 0,
        first_visit_time TEXT,
        last_visit_time TEXT,
        review_rating INTEGER,
        review_text TEXT,
        review_count INTEGER DEFAULT 0,
        has_review INTEGER DEFAULT 0,
        review_photos TEXT,
        review_photo_count INTEGER DEFAULT 0,
        source TEXT
    );
    """)

    # Migrations for places
    _add_col_if_missing(c, "places", "category TEXT DEFAULT 'Other / POI'")
    _add_col_if_missing(c, "places", "city TEXT")
    _add_col_if_missing(c, "places", "country TEXT")
    _add_col_if_missing(c, "places", "review_rating INTEGER")
    _add_col_if_missing(c, "places", "review_text TEXT")
    _add_col_if_missing(c, "places", "review_count INTEGER DEFAULT 0")
    _add_col_if_missing(c, "places", "has_review INTEGER DEFAULT 0")
    _add_col_if_missing(c, "places", "review_photos TEXT")
    _add_col_if_missing(c, "places", "review_photo_count INTEGER DEFAULT 0")

    # 3. Timeline Segments (Visits and Movement Activities)
    c.execute("""
    CREATE TABLE IF NOT EXISTS segments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        segment_type TEXT NOT NULL,          -- 'visit' | 'activity'
        start_time TEXT NOT NULL,            -- ISO 8601 string
        end_time TEXT NOT NULL,              -- ISO 8601 string
        start_ts REAL NOT NULL,              -- UTC Unix epoch timestamp
        end_ts REAL NOT NULL,                -- UTC Unix epoch timestamp
        duration_minutes REAL NOT NULL,
        date TEXT NOT NULL,                  -- 'YYYY-MM-DD'
        year INTEGER NOT NULL,
        month INTEGER NOT NULL,
        day INTEGER NOT NULL,
        latitude REAL,                       -- start/visit latitude
        longitude REAL,                      -- start/visit longitude
        end_lat REAL,                        -- end latitude (for activities)
        end_lng REAL,                        -- end longitude (for activities)
        place_id TEXT,
        place_name TEXT,
        place_address TEXT,
        semantic_type TEXT,
        category TEXT,
        city TEXT,
        activity_type TEXT,
        distance_meters REAL DEFAULT 0.0,
        probability REAL DEFAULT 1.0,
        hierarchy_level INTEGER DEFAULT 0,   -- 0 = parent visit / normal activity, 1 = child visit
        parent_segment_id INTEGER,
        path_points_json TEXT,               -- GeoJSON / Array of coordinates for road-snapped polyline
        has_snapped_path INTEGER DEFAULT 0,
        is_unconfirmed INTEGER DEFAULT 0,
        review_rating INTEGER,
        review_photos TEXT,
        source TEXT,
        FOREIGN KEY (place_id) REFERENCES places(place_id),
        FOREIGN KEY (parent_segment_id) REFERENCES segments(id)
    );
    """)

    # Migrations for segments
    _add_col_if_missing(c, "segments", "category TEXT")
    _add_col_if_missing(c, "segments", "city TEXT")
    _add_col_if_missing(c, "segments", "review_rating INTEGER")
    _add_col_if_missing(c, "segments", "review_photos TEXT")

    # 4. Gaps Table (Post-2010 tracking drops and missing intervals)
    c.execute("""
    CREATE TABLE IF NOT EXISTS gaps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        start_ts REAL NOT NULL,
        end_ts REAL NOT NULL,
        duration_hours REAL NOT NULL,
        date TEXT NOT NULL,
        year INTEGER NOT NULL,
        prev_segment_id INTEGER,
        next_segment_id INTEGER,
        prev_lat REAL,
        prev_lng REAL,
        next_lat REAL,
        next_lng REAL,
        jump_distance_km REAL,
        raw_signals_count INTEGER DEFAULT 0,
        is_historical INTEGER DEFAULT 0,     -- 1 for pre-2010, 0 for post-2010
        status TEXT DEFAULT 'OPEN',          -- 'OPEN' | 'RESOLVED' | 'DISMISSED'
        FOREIGN KEY (prev_segment_id) REFERENCES segments(id),
        FOREIGN KEY (next_segment_id) REFERENCES segments(id)
    );
    """)

    # 5. Anomalies Table (Top-level collisions, speed outliers, teleportation)
    c.execute("""
    CREATE TABLE IF NOT EXISTS anomalies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        anomaly_type TEXT NOT NULL,          -- 'TOP_LEVEL_OVERLAP', 'UNCONFIRMED_PLACE', 'SPEED_OUTLIER', 'TELEPORTATION', 'STRAIGHT_LINE_ACTIVITY'
        segment_id INTEGER,
        date TEXT NOT NULL,
        description TEXT NOT NULL,
        severity TEXT NOT NULL,              -- 'INFO', 'WARNING', 'ERROR'
        data_json TEXT,
        is_resolved INTEGER DEFAULT 0,
        FOREIGN KEY (segment_id) REFERENCES segments(id)
    );
    """)

    # 6. Raw Signals (GPS, Wi-Fi, Cell Tower fixes)
    c.execute("""
    CREATE TABLE IF NOT EXISTS raw_signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        ts REAL NOT NULL,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL,
        accuracy_meters REAL,
        altitude_meters REAL,
        speed_mps REAL,
        source TEXT,                         -- 'GPS', 'WIFI', 'CELL'
        date TEXT NOT NULL,
        year INTEGER NOT NULL
    );
    """)

    # 7. Fix Proposals & Non-Destructive Patches
    c.execute("""
    CREATE TABLE IF NOT EXISTS fix_proposals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target_type TEXT NOT NULL,          -- 'GAP', 'UNCONFIRMED_PLACE', 'ACTIVITY_PATH', 'TOP_LEVEL_OVERLAP'
        target_id INTEGER,
        date TEXT NOT NULL,
        proposed_action TEXT NOT NULL,      -- 'INSERT_VISIT', 'INSERT_ACTIVITY', 'HYDRATE_PLACE', 'SNAP_ROUTE', 'MERGE_SEGMENTS'
        source TEXT NOT NULL,               -- 'TAKEOUT_FUSION', 'GMM_HARNESS', 'PHOTOS_EXIF', 'GMAIL', 'TRANSACTIONS', 'ROUTING_OSRM', 'REVIEWS_GEOJSON'
        reasoning TEXT NOT NULL,
        confidence REAL DEFAULT 1.0,
        status TEXT DEFAULT 'PENDING',      -- 'PENDING', 'ACCEPTED', 'REJECTED'
        patch_data_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        applied_at TEXT
    );
    """)

    # 8. POI Contributor Reviews Table (from google_contributor_reviews.geojson)
    c.execute("""
    CREATE TABLE IF NOT EXISTS poi_reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        place_name TEXT,
        date TEXT,
        rating INTEGER,
        review_text TEXT,
        google_maps_url TEXT,
        latitude REAL,
        longitude REAL,
        matched_place_id TEXT,
        photo_urls TEXT,
        photo_count INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(matched_place_id) REFERENCES places(place_id) ON DELETE SET NULL
    );
    """)

    _add_col_if_missing(c, "poi_reviews", "photo_urls TEXT")
    _add_col_if_missing(c, "poi_reviews", "photo_count INTEGER DEFAULT 0")

    # 9. Raw GPS Breadcrumbs Table
    c.execute("""
    CREATE TABLE IF NOT EXISTS breadcrumbs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chunk_id TEXT,
        timestamp INTEGER,
        date TEXT,
        lat REAL,
        lng REAL,
        accuracy REAL,
        speed_kmh REAL,
        anomaly_type TEXT,
        anomaly_score REAL,
        anomaly_reason TEXT,
        is_excluded INTEGER DEFAULT 0
    );
    """)

    # 10. Multi-Day Trips Table
    c.execute("""
    CREATE TABLE IF NOT EXISTS trips (
        id TEXT PRIMARY KEY,
        name TEXT,
        destination_label TEXT,
        primary_city TEXT,
        country TEXT,
        start_date TEXT,
        end_date TEXT,
        duration_days INTEGER,
        total_distance_km REAL,
        visit_count INTEGER,
        top_places_json TEXT,
        highlight_poi TEXT,
        status TEXT,
        cover_image_url TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 11. Life Periods Table
    c.execute("""
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
    """)

    # 12. Memories Table
    c.execute("""
    CREATE TABLE IF NOT EXISTS memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        memory_id TEXT UNIQUE,
        date TEXT,
        start_ts REAL,
        end_ts REAL,
        title TEXT,
        raw_text TEXT,
        raw_proto_hex TEXT
    );
    """)

    # 13. Country Stats Table
    c.execute("""
    CREATE TABLE IF NOT EXISTS country_stats (
        country TEXT PRIMARY KEY,
        flag TEXT,
        trips_count INTEGER DEFAULT 0,
        total_days REAL DEFAULT 0,
        total_visits INTEGER DEFAULT 0,
        first_visit TEXT,
        latest_visit TEXT
    );
    """)

    # 14. Contacts Table
    c.execute("""
    CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        organization TEXT,
        street TEXT,
        full_address TEXT,
        email TEXT,
        phone TEXT
    );
    """)

    # 15. Calendar Events Table
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

    # 16. Custom Labeled Places
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

    # 17. Place Aliases Table
    c.execute("""
    CREATE TABLE IF NOT EXISTS place_aliases (
        alias_place_id TEXT PRIMARY KEY,
        canonical_place_id TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 18. Google Place Cache
    c.execute("""
    CREATE TABLE IF NOT EXISTS google_place_cache (
        place_id TEXT PRIMARY KEY,
        name TEXT,
        address TEXT,
        category TEXT,
        city TEXT,
        country TEXT,
        latitude REAL,
        longitude REAL,
        primary_type TEXT,
        types_json TEXT,
        status TEXT NOT NULL,
        raw_payload TEXT,
        queried_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 19. Photos Index Table
    c.execute("""
    CREATE TABLE IF NOT EXISTS photos (
        sha256 TEXT PRIMARY KEY,
        filename TEXT,
        preview_path TEXT,
        timestamp_utc INTEGER,
        timezone_offset TEXT,
        local_date TEXT,
        latitude REAL,
        longitude REAL,
        place_id TEXT,
        place_name TEXT,
        address TEXT,
        city TEXT,
        country TEXT,
        people TEXT,
        face_count INTEGER DEFAULT 0,
        is_partner INTEGER DEFAULT 0
    );
    """)

    # Create Performance Indices
    c.execute("CREATE INDEX IF NOT EXISTS idx_segments_date ON segments(date);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_segments_year_month ON segments(year, month);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_segments_ts ON segments(start_ts, end_ts);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_segments_place ON segments(place_id);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_segments_type ON segments(segment_type);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_segments_activity ON segments(activity_type);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_segments_category ON segments(category);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_segments_city ON segments(city);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_segments_hierarchy ON segments(hierarchy_level, parent_segment_id);")
    
    c.execute("CREATE INDEX IF NOT EXISTS idx_places_name ON places(name);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_places_category ON places(category);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_places_city ON places(city);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_places_rating ON places(review_rating);")
    
    c.execute("CREATE INDEX IF NOT EXISTS idx_gaps_date ON gaps(date);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_gaps_duration ON gaps(duration_hours);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_anomalies_date ON anomalies(date);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_anomalies_type ON anomalies(anomaly_type);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_raw_ts ON raw_signals(ts);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_raw_date ON raw_signals(date);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_fixes_status ON fix_proposals(status);")

    c.execute("CREATE INDEX IF NOT EXISTS idx_poi_reviews_coords ON poi_reviews(latitude, longitude);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_poi_reviews_place_id ON poi_reviews(matched_place_id);")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("Database schema and migrations successfully initialized.")
