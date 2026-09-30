#!/usr/bin/env python3
"""
Re-indexes photos into timeline_viewer.db directly from gregor_cos photos_vault.db
with strict timestamp verification and exact camera local-to-UTC conversion.
"""

import datetime
import os
import re
import sqlite3
import time
from pathlib import Path

COS_DB_PATH = "/Users/rothfuss/projects/gregor_cos/photos_vault.db"
TV_DB_PATH = str(Path(__file__).resolve().parent.parent / "timeline_viewer.db")


def parse_tz(tz: str | None) -> int:
    if not tz:
        return 0
    m = re.match(r"([+-])(\d{2}):(\d{2})", tz)
    if not m:
        return 0
    sign = -1 if m.group(1) == "-" else 1
    return sign * (int(m.group(2)) * 3600 + int(m.group(3)) * 60)


def main():
    if not os.path.exists(COS_DB_PATH):
        raise FileNotFoundError(f"photos_vault.db not found at {COS_DB_PATH}")

    con_cos = sqlite3.connect(COS_DB_PATH)
    cur_cos = con_cos.cursor()

    camera_pat = re.compile(
        r"^(?:PXL_|IMG_|MVIMG_|VID_|Screenshot_|WP[-_])(19[7-9]\d|20[0-2]\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])[-_]([01]\d|2[0-3])([0-5]\d)([0-5]\d)"
    )

    print("Reading photos from photos_vault.db...")
    rows = cur_cos.execute("""
        SELECT sha256, filename, preview_path, timestamp_utc, timezone_offset, formatted_date,
               latitude, longitude, place_id, place_name, address, city, country, people, face_count
        FROM media_items
        WHERE preview_path IS NOT NULL
    """).fetchall()
    print(f"Total media items with previews: {len(rows)}")

    batch = []
    camera_ts_count = 0
    vault_ts_count = 0

    for r in rows:
        sha, fn, prev, ts, tz, fd, lat, lon, pid, pname, addr, city, country, people, fcnt = r
        offset = parse_tz(tz)
        true_ts = None
        ld = None

        # 1. Exact camera filename match (deterministic local time)
        if fn:
            m = camera_pat.match(fn)
            if m:
                y, mo, d, h, mi, s = map(int, m.groups())
                try:
                    local_dt = datetime.datetime(y, mo, d, h, mi, s, tzinfo=datetime.timezone.utc)
                    true_ts = int(local_dt.timestamp() - offset)
                    ld = f"{y:04d}-{mo:02d}-{d:02d}"
                    camera_ts_count += 1
                except Exception:
                    pass

        # 2. Authentic vault timestamp_utc fallback
        if true_ts is None and ts is not None and 0 <= ts <= 2500000000:
            true_ts = int(ts)
            try:
                local_dt = datetime.datetime.fromtimestamp(true_ts + offset, datetime.timezone.utc)
                ld = local_dt.strftime("%Y-%m-%d")
                vault_ts_count += 1
            except Exception:
                pass

        # Sanity check: discard impossible dates
        if ld and not ("1970-01-01" <= ld <= "2030-12-31"):
            ld = None
            true_ts = None

        batch.append((
            sha, fn, prev, true_ts, tz, ld, lat, lon, pid, pname, addr, city, country, people, fcnt or 0
        ))

    con_tv = sqlite3.connect(TV_DB_PATH)
    cur_tv = con_tv.cursor()

    print("Rebuilding photos table in timeline_viewer.db...")
    cur_tv.execute("DROP TABLE IF EXISTS photos;")
    cur_tv.execute("""
        CREATE TABLE photos (
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
            face_count INTEGER DEFAULT 0
        );
    """)

    t0 = time.time()
    cur_tv.executemany("""
        INSERT INTO photos (
            sha256, filename, preview_path, timestamp_utc, timezone_offset, local_date,
            latitude, longitude, place_id, place_name, address, city, country, people, face_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, batch)

    print("Building indexes on photos table...")
    cur_tv.execute("CREATE INDEX IF NOT EXISTS idx_photos_local_date ON photos(local_date);")
    cur_tv.execute("CREATE INDEX IF NOT EXISTS idx_photos_timestamp_utc ON photos(timestamp_utc);")
    cur_tv.execute("CREATE INDEX IF NOT EXISTS idx_photos_place_id ON photos(place_id);")
    cur_tv.execute("CREATE INDEX IF NOT EXISTS idx_photos_coords ON photos(latitude, longitude);")
    con_tv.commit()
    t1 = time.time()

    print(f"Done in {t1-t0:.2f}s!")
    print(f"  Inserted: {len(batch)} photos")
    print(f"  Exact camera timestamps: {camera_ts_count}")
    print(f"  Vault timestamps: {vault_ts_count}")

    # Check stats
    res = cur_tv.execute("""
        SELECT COUNT(*), COUNT(timestamp_utc), COUNT(local_date),
               MIN(local_date), MAX(local_date),
               MIN(timestamp_utc), MAX(timestamp_utc)
        FROM photos;
    """).fetchone()
    print("Verification stats in timeline_viewer.db:")
    print(f"  Total: {res[0]}, with ts: {res[1]}, with date: {res[2]}")
    print(f"  Date range: {res[3]} to {res[4]}")
    print(f"  TS range: {res[5]} to {res[6]}")


if __name__ == "__main__":
    main()
