#!/usr/bin/env python3
"""
Re-indexes photos into timeline_viewer.db directly from gregor_cos photos_vault.db
with strict timestamp verification and exact camera local-to-UTC conversion.
"""

import datetime
import math
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
    wa_pat = re.compile(
        r"^(?:IMG-)?(19[7-9]\d|20[0-2]\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])[-_]WA"
    )

    def haversine_km(lat1, lon1, lat2, lon2):
        if None in (lat1, lon1, lat2, lon2):
            return 999999.0
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
        return 6371.0 * 2 * math.asin(math.sqrt(math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2))

    # Preload Gregor's ground truth daily locations from segments in timeline_viewer.db
    gregor_locs_by_date = {}
    if os.path.exists(TV_DB_PATH):
        con_tv_read = sqlite3.connect(TV_DB_PATH)
        cur_tv_read = con_tv_read.cursor()
        for d, s_lat, s_lon in cur_tv_read.execute("SELECT date, latitude, longitude FROM segments WHERE latitude IS NOT NULL AND longitude IS NOT NULL"):
            if d not in gregor_locs_by_date:
                gregor_locs_by_date[d] = []
            gregor_locs_by_date[d].append((s_lat, s_lon))
        con_tv_read.close()

    print("Reading photos from photos_vault.db...")
    rows = cur_cos.execute("""
        SELECT sha256, filename, preview_path, timestamp_utc, timezone_offset, formatted_date,
               latitude, longitude, place_id, place_name, address, city, country, people, face_count,
               location_source, is_partner, camera_model
        FROM media_items
        WHERE preview_path IS NOT NULL
    """).fetchall()
    print(f"Total media items with previews: {len(rows)}")

    # Pre-pass: also gather Gregor's own camera photo locations (Gregor's photos trump)
    for r in rows:
        sha, fn, prev, ts, tz, fd, lat, lon, pid, pname, addr, city, country, people, fcnt, loc_source, is_p, cam = r
        if is_p == 0 and cam != "Pixel 6" and lat is not None and lon is not None:
            ld_candidate = None
            if fn:
                m_cam = camera_pat.match(fn)
                if m_cam:
                    y, mo, d = map(int, m_cam.groups()[:3])
                    ld_candidate = f"{y:04d}-{mo:02d}-{d:02d}"
            if ld_candidate:
                if ld_candidate not in gregor_locs_by_date:
                    gregor_locs_by_date[ld_candidate] = []
                gregor_locs_by_date[ld_candidate].append((lat, lon))

    batch = []
    camera_ts_count = 0
    vault_ts_count = 0
    partner_discarded_count = 0
    partner_kept_count = 0

    for r in rows:
        sha, fn, prev, ts, tz, fd, lat, lon, pid, pname, addr, city, country, people, fcnt, loc_source, is_p, cam = r
        offset = parse_tz(tz)
        true_ts = None
        ld = None

        # Purge synthetic circular locations derived from timeline visits/activities
        if loc_source in ("timeline_visit", "timeline_activity"):
            lat, lon, pid, pname, addr = None, None, None, None, None

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
            else:
                m_wa = wa_pat.match(fn)
                if m_wa:
                    y, mo, d = map(int, m_wa.groups())
                    ld = f"{y:04d}-{mo:02d}-{d:02d}"
                    # WhatsApp media has no second-level capture time; keep true_ts None so it is not falsely placed into a visit
                    true_ts = None

        # 2. Authentic vault timestamp_utc fallback (only if date not already extracted)
        if true_ts is None and ld is None and ts is not None and 0 <= ts <= 2500000000:
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

        # Identify partner photos (partner sharing flag or Jessica's Pixel 6 from 2023 onwards)
        is_partner_photo = bool((is_p == 1) or (cam == "Pixel 6" and (ld or "") >= "2023-01-01"))

        # Enforce partner colocation: discard partner photos when Jessica was far away from Gregor
        if is_partner_photo and ld and ld in gregor_locs_by_date:
            g_locs = gregor_locs_by_date[ld]
            if lat is not None and lon is not None:
                min_d = min(haversine_km(lat, lon, g_lat, g_lon) for g_lat, g_lon in g_locs)
                if min_d > 50.0:
                    # Non-colocated: partner was in a different city or continent; discard!
                    partner_discarded_count += 1
                    continue
                else:
                    partner_kept_count += 1
            else:
                # Non-GPS partner photo on a day Gregor has verified GPS elsewhere: discard to prevent false co-presence
                partner_discarded_count += 1
                continue

        batch.append((
            sha, fn, prev, true_ts, tz, ld, lat, lon, pid, pname, addr, city, country, people, fcnt or 0,
            1 if is_partner_photo else 0
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
            face_count INTEGER DEFAULT 0,
            is_partner INTEGER DEFAULT 0
        );
    """)

    t0 = time.time()
    cur_tv.executemany("""
        INSERT INTO photos (
            sha256, filename, preview_path, timestamp_utc, timezone_offset, local_date,
            latitude, longitude, place_id, place_name, address, city, country, people, face_count,
            is_partner
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, batch)

    print("Building indexes on photos table...")
    cur_tv.execute("CREATE INDEX IF NOT EXISTS idx_photos_local_date ON photos(local_date);")
    cur_tv.execute("CREATE INDEX IF NOT EXISTS idx_photos_timestamp_utc ON photos(timestamp_utc);")
    cur_tv.execute("CREATE INDEX IF NOT EXISTS idx_photos_place_id ON photos(place_id);")
    cur_tv.execute("CREATE INDEX IF NOT EXISTS idx_photos_coords ON photos(latitude, longitude);")
    cur_tv.execute("CREATE INDEX IF NOT EXISTS idx_photos_partner ON photos(is_partner);")
    con_tv.commit()
    t1 = time.time()

    print(f"Done in {t1-t0:.2f}s!")
    print(f"  Inserted: {len(batch)} photos")
    print(f"  Exact camera timestamps: {camera_ts_count}")
    print(f"  Vault timestamps: {vault_ts_count}")
    print(f"  Partner photos discarded (non-colocated > 50km): {partner_discarded_count}")
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
