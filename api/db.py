"""
Database Access Layer for Timeline Studio API.

Provides thread-local read/write connection pooling with inode change detection,
re-entrant write transactions (`BEGIN IMMEDIATE`), zero WAL snapshot pinning on
idle worker threads, and FTS5 helper re-exports.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import threading
from typing import Any, Dict, Iterator, List, Optional, Tuple

from db import (
    DEFAULT_DB_PATH,
    build_fts_match_query,
    configure_connection,
    get_db_connection as _open_db_connection,
    get_db_path,
)

__all__ = [
    "DEFAULT_DB_PATH",
    "build_fts_match_query",
    "close_all_connections",
    "close_thread_connections",
    "execute_write",
    "get_db",
    "get_db_connection",
    "get_db_path",
    "get_read_db",
    "query_all",
    "query_one",
]

_THREAD_LOCAL = threading.local()
_REGISTRY_LOCK = threading.Lock()
_REGISTERED_POOLS: list[Dict[str, Tuple[int, sqlite3.Connection]]] = []


def _file_inode(path: str) -> int:
    try:
        return os.stat(path).st_ino
    except OSError:
        return -1


def _thread_pool(attr_name: str) -> Dict[str, Tuple[int, sqlite3.Connection]]:
    pool: Optional[Dict[str, Tuple[int, sqlite3.Connection]]] = getattr(_THREAD_LOCAL, attr_name, None)
    if pool is None:
        pool = {}
        setattr(_THREAD_LOCAL, attr_name, pool)
        with _REGISTRY_LOCK:
            _REGISTERED_POOLS.append(pool)
    return pool


def _active_writes() -> Dict[str, sqlite3.Connection]:
    active: Optional[Dict[str, sqlite3.Connection]] = getattr(_THREAD_LOCAL, "active_writes", None)
    if active is None:
        active = {}
        _THREAD_LOCAL.active_writes = active
    return active


def get_db_connection(db_path: Optional[str] = None, *, readonly: bool = False) -> sqlite3.Connection:
    """Creates a standalone configured SQLite connection (caller must close)."""
    return _open_db_connection(db_path, readonly=readonly, busy_timeout_ms=15000)


def _acquire_pooled_connection(target: str, *, readonly: bool) -> sqlite3.Connection:
    pool = _thread_pool("read_pool" if readonly else "write_pool")
    cur_ino = _file_inode(target)
    cached = pool.get(target)
    if cached is not None:
        cached_ino, cached_conn = cached
        if cached_ino == cur_ino and cur_ino != -1:
            return cached_conn
        with contextlib.suppress(Exception):
            cached_conn.close()
        pool.pop(target, None)

    can_ro = readonly and cur_ino != -1
    conn = _open_db_connection(
        target,
        readonly=can_ro,
        isolation_level=None,
        busy_timeout_ms=15000,
    )
    new_ino = _file_inode(target)
    if new_ino != -1:
        pool[target] = (new_ino, conn)
    return conn


def close_thread_connections() -> None:
    """Closes all pooled read/write SQLite connections for the calling thread."""
    for attr_name in ("read_pool", "write_pool"):
        pool: Optional[Dict[str, Tuple[int, sqlite3.Connection]]] = getattr(_THREAD_LOCAL, attr_name, None)
        if not pool:
            continue
        for _, conn in list(pool.values()):
            with contextlib.suppress(Exception):
                conn.close()
        pool.clear()


def close_all_connections() -> None:
    """Closes all pooled SQLite connections across all registered worker threads."""
    with _REGISTRY_LOCK:
        pools = list(_REGISTERED_POOLS)
    for pool in pools:
        for key, (_, conn) in list(pool.items()):
            with contextlib.suppress(Exception):
                conn.close()
            pool.pop(key, None)


@contextlib.contextmanager
def get_read_db(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    """Context manager yielding a pooled read-only SQLite connection for the current thread.

    Automatically reuses an active write transaction on the same thread if one is open,
    and releases any implicit read snapshot on exit so idle threads never pin WAL frames.
    """
    target = get_db_path(db_path)
    active = _active_writes().get(target)
    if active is not None:
        yield active
        return

    conn = _acquire_pooled_connection(target, readonly=True)
    try:
        yield conn
    finally:
        if conn.in_transaction:
            with contextlib.suppress(sqlite3.Error):
                conn.execute("ROLLBACK;")


@contextlib.contextmanager
def get_db(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    """Context manager for atomic write transactions using `BEGIN IMMEDIATE`.

    Re-entrant on the same `(thread, target)` pair and guarantees `COMMIT` on success
    or `ROLLBACK` on exception while keeping the underlying connection warm in the pool.
    """
    target = get_db_path(db_path)
    active_map = _active_writes()
    existing = active_map.get(target)
    if existing is not None:
        yield existing
        return

    conn = _acquire_pooled_connection(target, readonly=False)
    configure_connection(conn, readonly=False, busy_timeout_ms=15000)
    conn.execute("BEGIN IMMEDIATE;")
    active_map[target] = conn
    try:
        yield conn
        if conn.in_transaction:
            conn.execute("COMMIT;")
    except Exception:
        if conn.in_transaction:
            with contextlib.suppress(sqlite3.Error):
                conn.execute("ROLLBACK;")
        raise
    finally:
        active_map.pop(target, None)


def query_all(
    sql: str, params: tuple[Any, ...] | list[Any] = (), db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Executes a SELECT query on the pooled read connection and returns row dicts."""
    with get_read_db(db_path) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            cursor.close()


def query_one(
    sql: str, params: tuple[Any, ...] | list[Any] = (), db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Executes a SELECT query on the pooled read connection and returns one row dict or None."""
    with get_read_db(db_path) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(sql, params)
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            cursor.close()


def execute_write(
    sql: str, params: tuple[Any, ...] | list[Any] = (), db_path: Optional[str] = None
) -> int:
    """Executes an INSERT/UPDATE/DELETE query inside a `BEGIN IMMEDIATE` transaction."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(sql, params)
            return cursor.lastrowid or cursor.rowcount
        finally:
            cursor.close()
