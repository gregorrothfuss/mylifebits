"""
Canonical Place ID Validation, Reference Relinking, and Visit Aggregate Recomputation.

Maintains strict invariants across `places`, `segments`, `photos`, `poi_reviews`,
`raw_source_segments`, and `place_aliases`:
- 100% 20-byte `ChIJ` binary Feature ID integrity (`\\x0a\\x12\\x09<8B cell>\\x11<8B fprint>`)
- Exact `visit_count`, `first_visit_time`, `last_visit_time`, `latest_visit_date`,
  and `median_dwell_minutes` computed strictly from `segments WHERE segment_type = 'visit'`
"""

from __future__ import annotations

import base64
import hashlib
import sqlite3
import statistics
import struct
from typing import Iterable, List, Optional


def is_valid_20byte_chij(pid: Optional[str]) -> bool:
    """Verifies exact 20-byte protobuf FeatureId alignment inside a `ChIJ` Place ID."""
    if not pid or not str(pid).startswith("ChIJ"):
        return False
    try:
        pad = str(pid) + "=" * ((4 - len(str(pid)) % 4) % 4)
        raw = base64.urlsafe_b64decode(pad.encode("ascii"))
        if (
            len(raw) < 20
            or raw[0] != 0x0A
            or raw[1] != 0x12
            or raw[2] != 0x09
            or raw[11] != 0x11
        ):
            return False
        fp = struct.unpack("<Q", raw[12:20])[0]
        return fp != 0
    except Exception:
        return False


def mint_canonical_chij(
    lat: Optional[float], lng: Optional[float], seed_str: str
) -> str:
    """Mints a deterministic, structurally valid 20-byte `ChIJ` Place ID."""
    full_seed = f"{seed_str}|{lat if lat is not None else 0.0:.5f}|{lng if lng is not None else 0.0:.5f}"
    digest = hashlib.sha256(full_seed.encode("utf-8")).digest()
    cell_id = struct.unpack("<Q", digest[:8])[0] | 1
    fprint = struct.unpack("<Q", digest[8:16])[0] | 1
    blob = (
        b"\x0a\x12\x09"
        + struct.pack("<Q", cell_id)
        + b"\x11"
        + struct.pack("<Q", fprint)
    )
    return base64.urlsafe_b64encode(blob).decode("ascii").rstrip("=")


def relink_place_references(
    conn: sqlite3.Connection,
    old_place_id: str,
    new_place_id: str,
    *,
    delete_old: bool = True,
) -> None:
    """
    Atomically migrates all foreign/logical references from `old_place_id` to `new_place_id`
    across `segments`, `poi_reviews`, `photos`, `raw_source_segments`, and `place_aliases`.
    """
    if not old_place_id or not new_place_id or old_place_id == new_place_id:
        return

    c = conn.cursor()
    c.execute(
        "UPDATE segments SET place_id = ? WHERE place_id = ?;",
        (new_place_id, old_place_id),
    )
    c.execute(
        "UPDATE poi_reviews SET matched_place_id = ? WHERE matched_place_id = ?;",
        (new_place_id, old_place_id),
    )
    c.execute(
        "UPDATE photos SET place_id = ? WHERE place_id = ?;",
        (new_place_id, old_place_id),
    )
    c.execute(
        "UPDATE raw_source_segments SET place_id = ? WHERE place_id = ?;",
        (new_place_id, old_place_id),
    )
    c.execute(
        "UPDATE place_aliases SET canonical_place_id = ? WHERE canonical_place_id = ?;",
        (new_place_id, old_place_id),
    )
    c.execute(
        """
        INSERT INTO place_aliases (alias_place_id, canonical_place_id)
        VALUES (?, ?)
        ON CONFLICT(alias_place_id) DO UPDATE SET canonical_place_id = excluded.canonical_place_id;
        """,
        (old_place_id, new_place_id),
    )
    if delete_old:
        c.execute("DELETE FROM places WHERE place_id = ?;", (old_place_id,))


def recompute_place_aggregates(
    conn: sqlite3.Connection,
    place_ids: Optional[Iterable[Optional[str]]] = None,
) -> int:
    """
    Recomputes `visit_count`, `first_visit_time`, `last_visit_time`, `latest_visit_date`,
    and true `median_dwell_minutes` on `places` strictly from `segments WHERE segment_type = 'visit'`.

    If `place_ids` is None, recomputes across the entire `places` table in a single pass.
    """
    c = conn.cursor()

    if place_ids is not None:
        unique_pids: List[str] = sorted({str(p).strip() for p in place_ids if p and str(p).strip()})
        if not unique_pids:
            return 0

        updated = 0
        for pid in unique_pids:
            rows = c.execute(
                """
                SELECT start_time, end_time, date, duration_minutes
                FROM segments
                WHERE place_id = ? AND segment_type = 'visit'
                ORDER BY start_ts ASC;
                """,
                (pid,),
            ).fetchall()

            if not rows:
                c.execute(
                    """
                    UPDATE places
                    SET visit_count = 0,
                        first_visit_time = NULL,
                        last_visit_time = NULL,
                        latest_visit_date = NULL,
                        median_dwell_minutes = 0
                    WHERE place_id = ?;
                    """,
                    (pid,),
                )
            else:
                v_cnt = len(rows)
                first_vt = min((r[0] for r in rows if r[0]), default=None)
                last_vt = max((r[1] or r[0] for r in rows if (r[1] or r[0])), default=None)
                latest_dt = max((r[2] for r in rows if r[2]), default=None)
                dwells = [float(r[3]) for r in rows if r[3] is not None and float(r[3]) >= 0.0]
                med_dwell = int(round(statistics.median(dwells))) if dwells else 0
                c.execute(
                    """
                    UPDATE places
                    SET visit_count = ?,
                        first_visit_time = ?,
                        last_visit_time = ?,
                        latest_visit_date = ?,
                        median_dwell_minutes = ?,
                        business_status = COALESCE(NULLIF(business_status, ''), 'OPERATIONAL')
                    WHERE place_id = ?;
                    """,
                    (v_cnt, first_vt, last_vt, latest_dt, med_dwell, pid),
                )
            updated += int(c.rowcount or 0)
        return updated

    # Full-catalog single-pass aggregation
    c.execute(
        """
        UPDATE places
        SET visit_count = 0,
            first_visit_time = NULL,
            last_visit_time = NULL,
            latest_visit_date = NULL,
            median_dwell_minutes = 0,
            business_status = COALESCE(NULLIF(business_status, ''), 'OPERATIONAL');
        """
    )
    rows = c.execute(
        """
        SELECT place_id, start_time, end_time, date, duration_minutes
        FROM segments
        WHERE segment_type = 'visit' AND place_id IS NOT NULL AND place_id != ''
        ORDER BY place_id ASC;
        """
    ).fetchall()

    grouped: dict[str, list[tuple[Optional[str], Optional[str], Optional[str], Optional[float]]]] = {}
    for pid, st_iso, et_iso, dt_str, dur_m in rows:
        grouped.setdefault(str(pid), []).append((st_iso, et_iso, dt_str, dur_m))

    batch_updates = []
    for pid, items in grouped.items():
        v_cnt = len(items)
        first_vt = min((x[0] for x in items if x[0]), default=None)
        last_candidates = [x[1] or x[0] for x in items]
        last_vt = max((v for v in last_candidates if v is not None), default=None)
        latest_dt = max((x[2] for x in items if x[2]), default=None)
        dwells = [float(x[3]) for x in items if x[3] is not None and float(x[3]) >= 0.0]
        med_dwell = int(round(statistics.median(dwells))) if dwells else 0
        batch_updates.append((v_cnt, first_vt, last_vt, latest_dt, med_dwell, pid))

    if batch_updates:
        c.executemany(
            """
            UPDATE places
            SET visit_count = ?,
                first_visit_time = ?,
                last_visit_time = ?,
                latest_visit_date = ?,
                median_dwell_minutes = ?
            WHERE place_id = ?;
            """,
            batch_updates,
        )
    return len(batch_updates)
