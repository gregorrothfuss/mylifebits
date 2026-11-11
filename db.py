"""
Canonical SQLite schema loader, connection configurator, migration runner, and FTS5 helpers.

Loads tracked `schema.sql` as the single source of truth for all tables, indexes, and
external-content FTS5 virtual tables (`places_fts`, `photos_fts`, `segments_fts`).
"""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Literal, Optional

REPO_ROOT = Path(__file__).resolve().parent
SCHEMA_SQL_PATH = REPO_ROOT / "schema.sql"

_FTS_TOKEN_RE = re.compile(r"[^\W_]+", flags=re.UNICODE)

# Legacy columns added across historical iterations before schema.sql unification
_LEGACY_COLUMN_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("places", "category TEXT DEFAULT 'Other / POI'"),
    ("places", "city TEXT"),
    ("places", "country TEXT"),
    ("places", "review_rating INTEGER"),
    ("places", "review_text TEXT"),
    ("places", "review_count INTEGER DEFAULT 0"),
    ("places", "has_review INTEGER DEFAULT 0"),
    ("places", "review_photos TEXT"),
    ("places", "review_photo_count INTEGER DEFAULT 0"),
    ("places", "primary_type TEXT"),
    ("places", "types TEXT"),
    ("places", "google_types_json TEXT"),
    ("places", "business_status TEXT DEFAULT 'UNKNOWN'"),
    ("places", "verification_status TEXT DEFAULT 'UNVERIFIED'"),
    ("places", "last_verified_at TEXT"),
    ("places", "latest_visit_date TEXT"),
    ("places", "median_dwell_minutes REAL"),
    ("segments", "category TEXT"),
    ("segments", "city TEXT"),
    ("segments", "clean_distance_meters REAL"),
    ("segments", "jitter_ratio REAL"),
    ("segments", "review_rating INTEGER"),
    ("segments", "review_photos TEXT"),
    ("segments", "fprint INTEGER"),
    ("segments", "feature_id TEXT"),
    ("segments", "road_segment_ids TEXT"),
    ("segments", "entity_metadata_json TEXT"),
    ("segments", "primary_type TEXT"),
    ("segments", "event_title TEXT"),
    ("segments", "with_people TEXT"),
    ("segments", "event_location TEXT"),
    ("segments", "fit_steps INTEGER"),
    ("segments", "fit_activity_type TEXT"),
    ("segments", "engine_version TEXT"),
    ("segments", "inference_run_id INTEGER"),
    ("segments", "evidence_json TEXT"),
    ("segments", "source_key TEXT"),
    ("fix_proposals", "engine_version TEXT"),
    ("fix_proposals", "inference_run_id INTEGER"),
    ("fix_proposals", "evidence_json TEXT"),
    ("fix_proposals", "decision_key TEXT"),
    ("poi_reviews", "photo_urls TEXT"),
    ("poi_reviews", "photo_count INTEGER DEFAULT 0"),
    ("trips", "summary_markdown TEXT"),
    ("photos", "blur_score REAL"),
    ("photos", "ocr_text TEXT"),
)

# Redundant duplicate or strict-prefix indexes superseded by composite indexes
_REDUNDANT_INDEXES: tuple[str, ...] = (
    "idx_segments_place_id",
    "idx_segments_seg_type",
    "idx_segments_date",
    "idx_segments_start_ts",
)


def _resolve_default_db_path() -> str:
    env_path = os.environ.get("TIMELINE_DB_PATH")
    if env_path:
        return os.path.abspath(env_path)
    legacy_path = REPO_ROOT / "timeline_viewer.db"
    if legacy_path.exists():
        return str(legacy_path)
    return str(REPO_ROOT / "timeline.db")


DEFAULT_DB_PATH = _resolve_default_db_path()


def get_db_path(db_path: Optional[str] = None) -> str:
    """Resolves the active SQLite database path dynamically, honoring TIMELINE_DB_PATH."""
    return os.path.abspath(db_path) if db_path else _resolve_default_db_path()


def configure_connection(
    conn: sqlite3.Connection,
    *,
    readonly: bool = False,
    busy_timeout_ms: int = 30000,
) -> sqlite3.Connection:
    """Applies high-concurrency WAL, memory-mapped I/O, and FTS5 trigger PRAGMAs."""
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)};")
    conn.execute("PRAGMA cache_size = -32000;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA mmap_size = 268435456;")
    if not readonly:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        # Required so INSERT OR REPLACE fires AFTER DELETE triggers on external-content FTS5 tables
        conn.execute("PRAGMA recursive_triggers = ON;")
    return conn


def get_db_connection(
    db_path: Optional[str] = None,
    *,
    readonly: bool = False,
    isolation_level: Optional[Literal["DEFERRED", "EXCLUSIVE", "IMMEDIATE"]] = "DEFERRED",
    busy_timeout_ms: int = 30000,
) -> sqlite3.Connection:
    """Returns a configured SQLite connection."""
    target = Path(get_db_path(db_path))
    timeout_sec = max(1.0, busy_timeout_ms / 1000.0)
    if readonly and target.exists():
        uri = f"{target.as_uri()}?mode=ro"
        conn = sqlite3.connect(
            uri,
            uri=True,
            timeout=timeout_sec,
            isolation_level=isolation_level,
            check_same_thread=False,
        )
        return configure_connection(conn, readonly=True, busy_timeout_ms=busy_timeout_ms)

    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(target),
        timeout=timeout_sec,
        isolation_level=isolation_level,
        check_same_thread=False,
    )
    return configure_connection(conn, readonly=False, busy_timeout_ms=busy_timeout_ms)


def build_fts_match_query(raw_query: str) -> Optional[str]:
    """Builds an injection-safe FTS5 prefix MATCH expression from arbitrary user input.

    Returns None when the input contains no indexable word tokens (e.g. pure punctuation),
    allowing callers to fall back cleanly or return empty results without OperationalError.
    """
    tokens = _FTS_TOKEN_RE.findall(raw_query.strip())
    if not tokens:
        return None
    return " AND ".join(f'"{tok}"*' for tok in tokens[:8])


def _add_col_if_missing(c: sqlite3.Cursor, table: str, col_def: str) -> None:
    """Safely adds a column to an existing SQLite table if absent."""
    try:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {col_def};")
    except sqlite3.OperationalError:
        pass


def _ensure_legacy_columns(conn: sqlite3.Connection) -> None:
    """Backfills columns on pre-existing tables prior to executing indexes/triggers in schema.sql."""
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type = 'table';")
    existing_tables = {row[0] for row in c.fetchall()}
    for table, col_def in _LEGACY_COLUMN_MIGRATIONS:
        if table in existing_tables:
            _add_col_if_missing(c, table, col_def)


def apply_migrations(conn: sqlite3.Connection) -> None:
    """Prunes redundant indexes and ensures external-content FTS5 indexes are populated."""
    c = conn.cursor()
    for idx_name in _REDUNDANT_INDEXES:
        c.execute(f"DROP INDEX IF EXISTS {idx_name};")

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    c.execute("SELECT version FROM schema_migrations;")
    applied_versions = {int(row[0]) for row in c.fetchall()}

    if 1 not in applied_versions:
        c.execute("INSERT INTO places_fts(places_fts) VALUES('rebuild');")
        c.execute("INSERT INTO photos_fts(photos_fts) VALUES('rebuild');")
        c.execute("INSERT INTO segments_fts(segments_fts) VALUES('rebuild');")
        c.execute(
            "INSERT INTO schema_migrations (version, name) VALUES (1, 'fts5_external_content_v1');"
        )


def init_db(db_path: Optional[str] = None) -> None:
    """Initializes the database from canonical schema.sql and runs idempotent migrations."""
    target = get_db_path(db_path)
    conn = get_db_connection(target, readonly=False)
    try:
        _ensure_legacy_columns(conn)
        conn.commit()

        schema_sql = SCHEMA_SQL_PATH.read_text(encoding="utf-8")
        conn.executescript(schema_sql)

        # Re-assert connection-scoped PRAGMAs after executescript
        configure_connection(conn, readonly=False)
        apply_migrations(conn)
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print("Database schema, FTS5 indexes, and migrations initialized.")
