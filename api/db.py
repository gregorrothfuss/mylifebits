"""
Database Access Layer for Timeline Studio API.
Provides robust context-managed SQLite sessions with WAL mode and automatic rollback.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

def _resolve_default_db_path() -> str:
    env_path = os.environ.get("TIMELINE_DB_PATH")
    if env_path:
        return os.path.abspath(env_path)
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    legacy_path = os.path.join(base_dir, "timeline_viewer.db")
    if os.path.exists(legacy_path):
        return legacy_path
    return os.path.join(base_dir, "timeline.db")


DEFAULT_DB_PATH = _resolve_default_db_path()


def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Creates a configured SQLite connection."""
    target = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(target, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


@contextlib.contextmanager
def get_db(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    """Context manager for SQLite connections.
    Guarantees commit on success, rollback on exception, and connection closing.
    """
    conn = get_db_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def query_all(
    sql: str, params: tuple[Any, ...] | list[Any] = (), db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Executes a SELECT query and returns all matching rows as dictionaries."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]


def query_one(
    sql: str, params: tuple[Any, ...] | list[Any] = (), db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Executes a SELECT query and returns a single matching row as a dictionary or None."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        row = cursor.fetchone()
        return dict(row) if row else None


def execute_write(
    sql: str, params: tuple[Any, ...] | list[Any] = (), db_path: Optional[str] = None
) -> int:
    """Executes an INSERT/UPDATE/DELETE query and returns lastrowid or rowcount."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        return cursor.lastrowid or cursor.rowcount
