-- =============================================================================
-- MyLifeBits / Timeline Studio Canonical SQLite Schema
-- Idempotent DDL for all core, enrichment, raw telemetry, ledger, and FTS5 tables
-- =============================================================================

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 1. Sources Table (Tracking imported archives and exports)
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT UNIQUE,
    file_path TEXT,
    imported_at TEXT,
    record_count INTEGER DEFAULT 0,
    metadata_json TEXT
);

-- 2. Places Catalog (Unified deduplicated places with Categories, Cities, and Reviews)
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
    source TEXT,
    primary_type TEXT,
    types TEXT,
    google_types_json TEXT,
    business_status TEXT DEFAULT 'UNKNOWN',
    verification_status TEXT DEFAULT 'UNVERIFIED',
    last_verified_at TEXT,
    latest_visit_date TEXT,
    median_dwell_minutes REAL
);

-- 3. Timeline Segments (Visits and Movement Activities)
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
    clean_distance_meters REAL,
    jitter_ratio REAL,
    probability REAL DEFAULT 1.0,
    hierarchy_level INTEGER DEFAULT 0,   -- 0 = parent visit / normal activity, 1 = child visit
    parent_segment_id INTEGER,
    path_points_json TEXT,               -- GeoJSON / Array of coordinates for road-snapped polyline
    has_snapped_path INTEGER DEFAULT 0,
    is_unconfirmed INTEGER DEFAULT 0,
    review_rating INTEGER,
    review_photos TEXT,
    fprint INTEGER,
    feature_id TEXT,
    road_segment_ids TEXT,
    entity_metadata_json TEXT,
    primary_type TEXT,
    event_title TEXT,
    with_people TEXT,
    event_location TEXT,
    fit_steps INTEGER,
    fit_activity_type TEXT,
    source TEXT,
    engine_version TEXT,
    inference_run_id INTEGER,
    evidence_json TEXT,
    source_key TEXT,
    FOREIGN KEY (place_id) REFERENCES places(place_id),
    FOREIGN KEY (parent_segment_id) REFERENCES segments(id)
);

-- 4. Gaps Table (Tracking drops and missing intervals)
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
    is_historical INTEGER DEFAULT 0,
    status TEXT DEFAULT 'OPEN',
    FOREIGN KEY (prev_segment_id) REFERENCES segments(id),
    FOREIGN KEY (next_segment_id) REFERENCES segments(id)
);

-- 5. Anomalies Table (Top-level collisions, speed outliers, teleportation)
CREATE TABLE IF NOT EXISTS anomalies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    anomaly_type TEXT NOT NULL,
    segment_id INTEGER,
    date TEXT NOT NULL,
    description TEXT NOT NULL,
    severity TEXT NOT NULL,
    data_json TEXT,
    is_resolved INTEGER DEFAULT 0,
    FOREIGN KEY (segment_id) REFERENCES segments(id)
);

-- 6. Raw Signals (GPS, Wi-Fi, Cell Tower fixes)
CREATE TABLE IF NOT EXISTS raw_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    ts REAL NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    accuracy_meters REAL,
    altitude_meters REAL,
    speed_mps REAL,
    source TEXT,
    date TEXT NOT NULL,
    year INTEGER NOT NULL
);

-- 7. Fix Proposals & Non-Destructive Patches
CREATE TABLE IF NOT EXISTS fix_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type TEXT NOT NULL,
    target_id INTEGER,
    date TEXT NOT NULL,
    proposed_action TEXT NOT NULL,
    source TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    status TEXT DEFAULT 'PENDING',
    patch_data_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    applied_at TEXT,
    engine_version TEXT,
    inference_run_id INTEGER,
    evidence_json TEXT,
    decision_key TEXT
);

-- 8. POI Contributor Reviews Table
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
    FOREIGN KEY (matched_place_id) REFERENCES places(place_id) ON DELETE SET NULL
);

-- 9. Raw GPS Breadcrumbs Table
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

-- 10. Multi-Day Trips Table
CREATE TABLE IF NOT EXISTS trips (
    trip_id TEXT PRIMARY KEY,
    title TEXT,
    country TEXT,
    country_flag TEXT,
    theme TEXT,
    start_date TEXT,
    end_date TEXT,
    start_ts REAL,
    end_ts REAL,
    duration_days REAL,
    total_distance_km REAL,
    flights_count INTEGER DEFAULT 0,
    visits_count INTEGER DEFAULT 0,
    activities_count INTEGER DEFAULT 0,
    highlights_json TEXT,
    is_inferred INTEGER DEFAULT 0,
    summary_markdown TEXT
);

-- 11. Life Periods Table
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

-- 12. Memories Table
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

-- 13. Country Stats Table
CREATE TABLE IF NOT EXISTS country_stats (
    country TEXT PRIMARY KEY,
    flag TEXT,
    trips_count INTEGER DEFAULT 0,
    total_days REAL DEFAULT 0,
    total_visits INTEGER DEFAULT 0,
    first_visit TEXT,
    latest_visit TEXT
);

-- 14. Contacts Table
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    organization TEXT,
    street TEXT,
    full_address TEXT,
    email TEXT,
    phone TEXT
);

-- 15. Calendar Events Table
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

-- 16. Custom Labeled Places
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

-- 17. Google Fit Workout Sessions
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

-- 18. Raw ODLH Path Segments Archive (Tier-1 Protobuf Preservation)
CREATE TABLE IF NOT EXISTS raw_path_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    segment_id TEXT NOT NULL UNIQUE,
    database_id INTEGER NOT NULL,
    origin_id INTEGER,
    start_timestamp_seconds INTEGER NOT NULL,
    end_timestamp_seconds INTEGER NOT NULL,
    start_time TEXT,
    end_time TEXT,
    date TEXT NOT NULL,
    semantic_segment BLOB NOT NULL,
    obfuscated_gaia_id TEXT NOT NULL,
    shown_in_timeline INTEGER,
    is_finalized INTEGER,
    hierarchy_level INTEGER,
    fprint INTEGER
);

-- 19. Rolling Raw Signals Verbatim Buffer (Tier-1 Telemetry Preservation)
CREATE TABLE IF NOT EXISTS raw_signals_buffer (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_export TEXT NOT NULL,
    export_index INTEGER NOT NULL,
    signal_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    ts REAL NOT NULL,
    date TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE(source_export, export_index)
);

-- 20. Place Aliases Table
CREATE TABLE IF NOT EXISTS place_aliases (
    alias_place_id TEXT PRIMARY KEY,
    canonical_place_id TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 21. Google Place Cache
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

-- 22. Photos Index Table
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
    is_partner INTEGER DEFAULT 0,
    blur_score REAL,
    ocr_text TEXT
);

-- 23. Photo Vector Embeddings (CLIP Visual Vector Index)
CREATE TABLE IF NOT EXISTS photo_embeddings (
    sha256 TEXT PRIMARY KEY,
    vector BLOB NOT NULL,
    model TEXT DEFAULT 'open_clip:ViT-B-32',
    dim INTEGER DEFAULT 512,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 24. Layer 0: Immutable Raw Source Segments Ledger
CREATE TABLE IF NOT EXISTS raw_source_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key TEXT UNIQUE NOT NULL,
    source_stream TEXT NOT NULL,
    segment_type TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    start_ts REAL NOT NULL,
    end_ts REAL NOT NULL,
    duration_minutes REAL NOT NULL,
    date TEXT NOT NULL,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    day INTEGER NOT NULL,
    latitude REAL,
    longitude REAL,
    end_lat REAL,
    end_lng REAL,
    place_id TEXT,
    place_name TEXT,
    place_address TEXT,
    semantic_type TEXT,
    category TEXT,
    city TEXT,
    activity_type TEXT,
    distance_meters REAL DEFAULT 0.0,
    probability REAL DEFAULT 1.0,
    hierarchy_level INTEGER DEFAULT 0,
    path_points_json TEXT,
    has_snapped_path INTEGER DEFAULT 0,
    raw_payload_json TEXT,
    ingested_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 25. Layer 1: Versioned Inference Execution Runs
CREATE TABLE IF NOT EXISTS inference_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    engine_version TEXT NOT NULL,
    pass_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    input_summary_json TEXT,
    output_summary_json TEXT,
    status TEXT DEFAULT 'COMPLETED'
);

-- 26. Layer 2: Immutable User Review Decisions Ledger
CREATE TABLE IF NOT EXISTS user_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_key TEXT UNIQUE NOT NULL,
    decision_type TEXT NOT NULL,
    date TEXT,
    start_ts REAL,
    end_ts REAL,
    target_place_id TEXT,
    target_place_name TEXT,
    source_stream TEXT,
    proposal_action TEXT,
    patch_data_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- B-Tree & Partial Performance Indexes (Redundant Prefix/Duplicate Indexes Pruned)
-- =============================================================================

-- Segments
CREATE INDEX IF NOT EXISTS idx_segments_date_start_ts ON segments(date, start_ts);
CREATE INDEX IF NOT EXISTS idx_segments_date_type ON segments(date, segment_type);
CREATE INDEX IF NOT EXISTS idx_segments_year_month ON segments(year, month);
CREATE INDEX IF NOT EXISTS idx_segments_ts ON segments(start_ts, end_ts);
CREATE INDEX IF NOT EXISTS idx_segments_end_ts ON segments(end_ts);
CREATE INDEX IF NOT EXISTS idx_segments_place ON segments(place_id);
CREATE INDEX IF NOT EXISTS idx_segments_place_visit ON segments(place_id, segment_type);
CREATE INDEX IF NOT EXISTS idx_segments_type ON segments(segment_type);
CREATE INDEX IF NOT EXISTS idx_segments_activity ON segments(activity_type);
CREATE INDEX IF NOT EXISTS idx_segments_category ON segments(category);
CREATE INDEX IF NOT EXISTS idx_segments_city ON segments(city);
CREATE INDEX IF NOT EXISTS idx_segments_source ON segments(source);
CREATE INDEX IF NOT EXISTS idx_segments_hierarchy ON segments(hierarchy_level, parent_segment_id);
CREATE INDEX IF NOT EXISTS idx_segments_visit_lat ON segments(latitude) WHERE segment_type = 'visit';
CREATE INDEX IF NOT EXISTS idx_segments_visit_lng ON segments(longitude) WHERE segment_type = 'visit';
CREATE INDEX IF NOT EXISTS idx_segments_type_lat ON segments(segment_type, latitude);
CREATE INDEX IF NOT EXISTS idx_segments_type_lng ON segments(segment_type, longitude);
CREATE INDEX IF NOT EXISTS idx_segments_activity_covering ON segments(segment_type, activity_type, distance_meters, clean_distance_meters, duration_minutes);
CREATE INDEX IF NOT EXISTS idx_segments_visit_ts ON segments(segment_type, start_ts, end_ts);

-- Places
CREATE INDEX IF NOT EXISTS idx_places_name ON places(name);
CREATE INDEX IF NOT EXISTS idx_places_category ON places(category);
CREATE INDEX IF NOT EXISTS idx_places_city ON places(city);
CREATE INDEX IF NOT EXISTS idx_places_rating ON places(review_rating);
CREATE INDEX IF NOT EXISTS idx_places_source ON places(source);
CREATE INDEX IF NOT EXISTS idx_places_visits_desc ON places(visit_count DESC);
CREATE INDEX IF NOT EXISTS idx_places_coords ON places(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_places_filter_8020 ON places(category, latest_visit_date, median_dwell_minutes, visit_count);

-- Gaps, Anomalies, Raw Signals, Proposals
CREATE INDEX IF NOT EXISTS idx_gaps_date ON gaps(date);
CREATE INDEX IF NOT EXISTS idx_gaps_year_date ON gaps(year, date);
CREATE INDEX IF NOT EXISTS idx_gaps_duration ON gaps(duration_hours);
CREATE INDEX IF NOT EXISTS idx_anomalies_date ON anomalies(date);
CREATE INDEX IF NOT EXISTS idx_anomalies_type ON anomalies(anomaly_type);
CREATE INDEX IF NOT EXISTS idx_raw_ts ON raw_signals(ts);
CREATE INDEX IF NOT EXISTS idx_raw_date ON raw_signals(date);
CREATE INDEX IF NOT EXISTS idx_fixes_status ON fix_proposals(status);
CREATE INDEX IF NOT EXISTS idx_fixes_date ON fix_proposals(date);

-- POI Reviews, Breadcrumbs, Trips, Memories, Calendar, Custom Places, Fit
CREATE INDEX IF NOT EXISTS idx_poi_reviews_coords ON poi_reviews(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_poi_reviews_place_id ON poi_reviews(matched_place_id);
CREATE INDEX IF NOT EXISTS idx_breadcrumbs_date ON breadcrumbs(date);
CREATE INDEX IF NOT EXISTS idx_breadcrumbs_ts ON breadcrumbs(timestamp);
CREATE INDEX IF NOT EXISTS idx_breadcrumbs_anomaly ON breadcrumbs(anomaly_type);
CREATE INDEX IF NOT EXISTS idx_memories_date ON memories(date);
CREATE INDEX IF NOT EXISTS idx_trips_start_ts ON trips(start_ts);
CREATE INDEX IF NOT EXISTS idx_trips_country ON trips(country);
CREATE INDEX IF NOT EXISTS idx_cal_time ON calendar_events(start_ts, end_ts);
CREATE INDEX IF NOT EXISTS idx_cal_date ON calendar_events(date);
CREATE INDEX IF NOT EXISTS idx_custom_coords ON custom_labeled_places(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_fit_time ON fit_sessions(start_ts, end_ts);
CREATE INDEX IF NOT EXISTS idx_fit_date ON fit_sessions(date);

-- Raw ODLH Buffers, Aliases, Cache, Photos, Ledgers
CREATE INDEX IF NOT EXISTS idx_rps_start_ts ON raw_path_segments(start_timestamp_seconds);
CREATE INDEX IF NOT EXISTS idx_rps_date ON raw_path_segments(date);
CREATE INDEX IF NOT EXISTS idx_rsb_ts ON raw_signals_buffer(ts);
CREATE INDEX IF NOT EXISTS idx_rsb_date ON raw_signals_buffer(date);
CREATE INDEX IF NOT EXISTS idx_rsb_type ON raw_signals_buffer(signal_type);
CREATE INDEX IF NOT EXISTS idx_rsb_hash ON raw_signals_buffer(payload_hash);
CREATE INDEX IF NOT EXISTS idx_place_aliases_canonical ON place_aliases(canonical_place_id);
CREATE INDEX IF NOT EXISTS idx_google_place_cache_status ON google_place_cache(status);
CREATE INDEX IF NOT EXISTS idx_photos_local_date ON photos(local_date);
CREATE INDEX IF NOT EXISTS idx_photos_timestamp_utc ON photos(timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_photos_place_id ON photos(place_id);
CREATE INDEX IF NOT EXISTS idx_photos_place_name ON photos(place_name);
CREATE INDEX IF NOT EXISTS idx_photos_coords ON photos(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_photos_partner ON photos(is_partner);
CREATE INDEX IF NOT EXISTS idx_photo_embeddings_model ON photo_embeddings(model);
CREATE INDEX IF NOT EXISTS idx_raw_source_segments_date ON raw_source_segments(date);
CREATE INDEX IF NOT EXISTS idx_raw_source_segments_ts ON raw_source_segments(start_ts, end_ts);
CREATE INDEX IF NOT EXISTS idx_raw_source_segments_stream ON raw_source_segments(source_stream);
CREATE INDEX IF NOT EXISTS idx_raw_source_segments_place ON raw_source_segments(place_id);
CREATE INDEX IF NOT EXISTS idx_user_decisions_date ON user_decisions(date);
CREATE INDEX IF NOT EXISTS idx_user_decisions_type ON user_decisions(decision_type);

-- =============================================================================
-- External-Content FTS5 Virtual Tables & Automatic Synchronization Triggers
-- =============================================================================

CREATE VIRTUAL TABLE IF NOT EXISTS places_fts USING fts5(
    place_id UNINDEXED,
    name,
    address,
    city,
    category,
    review_text,
    content='places',
    content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS places_fts_ai AFTER INSERT ON places BEGIN
    INSERT INTO places_fts(rowid, place_id, name, address, city, category, review_text)
    VALUES (new.rowid, new.place_id, new.name, new.address, new.city, new.category, new.review_text);
END;

CREATE TRIGGER IF NOT EXISTS places_fts_ad AFTER DELETE ON places BEGIN
    INSERT INTO places_fts(places_fts, rowid, place_id, name, address, city, category, review_text)
    VALUES ('delete', old.rowid, old.place_id, old.name, old.address, old.city, old.category, old.review_text);
END;

CREATE TRIGGER IF NOT EXISTS places_fts_au AFTER UPDATE OF place_id, name, address, city, category, review_text ON places BEGIN
    INSERT INTO places_fts(places_fts, rowid, place_id, name, address, city, category, review_text)
    VALUES ('delete', old.rowid, old.place_id, old.name, old.address, old.city, old.category, old.review_text);
    INSERT INTO places_fts(rowid, place_id, name, address, city, category, review_text)
    VALUES (new.rowid, new.place_id, new.name, new.address, new.city, new.category, new.review_text);
END;

CREATE VIRTUAL TABLE IF NOT EXISTS photos_fts USING fts5(
    sha256 UNINDEXED,
    filename,
    place_name,
    address,
    city,
    people,
    ocr_text,
    content='photos',
    content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS photos_fts_ai AFTER INSERT ON photos BEGIN
    INSERT INTO photos_fts(rowid, sha256, filename, place_name, address, city, people, ocr_text)
    VALUES (new.rowid, new.sha256, new.filename, new.place_name, new.address, new.city, new.people, new.ocr_text);
END;

CREATE TRIGGER IF NOT EXISTS photos_fts_ad AFTER DELETE ON photos BEGIN
    INSERT INTO photos_fts(photos_fts, rowid, sha256, filename, place_name, address, city, people, ocr_text)
    VALUES ('delete', old.rowid, old.sha256, old.filename, old.place_name, old.address, old.city, old.people, old.ocr_text);
END;

CREATE TRIGGER IF NOT EXISTS photos_fts_au AFTER UPDATE OF sha256, filename, place_name, address, city, people, ocr_text ON photos BEGIN
    INSERT INTO photos_fts(photos_fts, rowid, sha256, filename, place_name, address, city, people, ocr_text)
    VALUES ('delete', old.rowid, old.sha256, old.filename, old.place_name, old.address, old.city, old.people, old.ocr_text);
    INSERT INTO photos_fts(rowid, sha256, filename, place_name, address, city, people, ocr_text)
    VALUES (new.rowid, new.sha256, new.filename, new.place_name, new.address, new.city, new.people, new.ocr_text);
END;

CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(
    place_name,
    place_address,
    city,
    category,
    event_title,
    with_people,
    content='segments',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS segments_fts_ai AFTER INSERT ON segments BEGIN
    INSERT INTO segments_fts(rowid, place_name, place_address, city, category, event_title, with_people)
    VALUES (new.id, new.place_name, new.place_address, new.city, new.category, new.event_title, new.with_people);
END;

CREATE TRIGGER IF NOT EXISTS segments_fts_ad AFTER DELETE ON segments BEGIN
    INSERT INTO segments_fts(segments_fts, rowid, place_name, place_address, city, category, event_title, with_people)
    VALUES ('delete', old.id, old.place_name, old.place_address, old.city, old.category, old.event_title, old.with_people);
END;

CREATE TRIGGER IF NOT EXISTS segments_fts_au AFTER UPDATE OF place_name, place_address, city, category, event_title, with_people ON segments BEGIN
    INSERT INTO segments_fts(segments_fts, rowid, place_name, place_address, city, category, event_title, with_people)
    VALUES ('delete', old.id, old.place_name, old.place_address, old.city, old.category, old.event_title, old.with_people);
    INSERT INTO segments_fts(rowid, place_name, place_address, city, category, event_title, with_people)
    VALUES (new.id, new.place_name, new.place_address, new.city, new.category, new.event_title, new.with_people);
END;
