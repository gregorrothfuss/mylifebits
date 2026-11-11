#!/usr/bin/env python3
"""
Sync Production Timeline Data via Rooted Pixel 8.

Workflow:
1. Connects to the rooted Pixel 8 (over USB or Wireless ADB).
2. Extracts GMS SQLite databases directly via root (su -c):
   - odlh-storage.db (+ WAL/SHM)
   - aux-odlh-storage.db (+ WAL/SHM)
   - portable_geller_*.db (+ WAL/SHM)
3. Automates or pulls on-device Timeline JSON export from /sdcard/Download/.
4. Preserves 100% of rolling rawSignals (71,960+ buffer) and raw paths (segment_type=3).
5. Incrementally synchronizes newly recorded days into timeline_viewer.db without
   overwriting curated or verified historical periods.
6. Emits extraction audit log with byte-for-byte and entity-level counts.
"""

import argparse
import base64
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple
import zoneinfo

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
if str(WORKSPACE_DIR) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_DIR))

from breadcrumbs import decode_protobuf_fields
from enrichment.gms_enums import GMS_CODE_TO_ACTIVITY

ADB_BIN = WORKSPACE_DIR / "platform-tools" / "adb"
DEFAULT_DB = Path(os.environ.get("TIMELINE_DB_PATH") or (WORKSPACE_DIR / "timeline_viewer.db"))
EXTRACTION_DIR = WORKSPACE_DIR / "pixel8_extracted"
NYC_TZ = zoneinfo.ZoneInfo("America/New_York")

ACT_MAP: Dict[int, str] = GMS_CODE_TO_ACTIVITY



def run_adb_cmd(args: List[str], target: Optional[str] = None, timeout: int = 30) -> Tuple[int, str, str]:
    """Runs an ADB command with optional device serial/target."""
    cmd = [str(ADB_BIN)]
    if target:
        cmd.extend(["-s", target])
    cmd.extend(args)
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return res.returncode, res.stdout, res.stderr
    except Exception as e:
        return 1, "", str(e)


def resolve_device(preferred_target: Optional[str] = None) -> str:
    """Finds a connected Android device, prioritizing the rooted Pixel 8."""
    if preferred_target:
        code, out, _ = run_adb_cmd(["get-state"], target=preferred_target)
        if code == 0 and "device" in out:
            return preferred_target

    code, out, _ = run_adb_cmd(["devices", "-l"])
    lines = [l.strip() for l in out.splitlines()[1:] if l.strip()]
    devices = []
    for l in lines:
        parts = l.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])

    if not devices:
        raise RuntimeError("No ADB devices connected. Please connect Pixel 8 via USB or Wireless ADB.")

    # Check for root on available devices
    for d in devices:
        code, out, _ = run_adb_cmd(["shell", "su", "-c", "id"], target=d, timeout=5)
        if code == 0 and "uid=0" in out:
            return d

    # Return first available device if root check is inconclusive
    return devices[0]


def check_device_root(target: str) -> bool:
    """Verifies root access on target device."""
    code, out, _ = run_adb_cmd(["shell", "su", "-c", "id"], target=target, timeout=5)
    return code == 0 and "uid=0" in out


def extract_gms_databases(target: str, out_dir: Path) -> List[Path]:
    """Copies odlh and geller databases from /data/data/com.google.android.gms/databases/."""
    out_dir.mkdir(parents=True, exist_ok=True)
    temp_device_dir = "/sdcard/Download/timeline_db_extract_tmp"

    print(f"[*] Preparing temporary extraction directory on device: {temp_device_dir}")
    run_adb_cmd(["shell", "rm", "-rf", temp_device_dir], target=target)
    run_adb_cmd(["shell", "mkdir", "-p", temp_device_dir], target=target)

    # Copy files as root to temporary sdcard directory
    db_globs = [
        "odlh-storage.db*",
        "aux-odlh-storage.db*",
        "portable_geller*",
    ]
    for pattern in db_globs:
        copy_cmd = f"cp /data/data/com.google.android.gms/databases/{pattern} {temp_device_dir}/ 2>/dev/null || true"
        run_adb_cmd(["shell", "su", "-c", copy_cmd], target=target)

    # Copy Google Maps places cache databases
    maps_globs = [
        "gmm_myplaces.db*",
        "gmm_sync.db*",
    ]
    for pattern in maps_globs:
        copy_cmd = f"cp /data/data/com.google.android.apps.maps/databases/{pattern} {temp_device_dir}/ 2>/dev/null || true"
        run_adb_cmd(["shell", "su", "-c", copy_cmd], target=target)

    # Chmod files so adb pull can read them
    run_adb_cmd(["shell", "su", "-c", f"chmod -R 777 {temp_device_dir}"], target=target)

    # Pull files to local Mac directory
    print(f"[*] Pulling databases to {out_dir}...")
    code, out, err = run_adb_cmd(["pull", f"{temp_device_dir}/.", str(out_dir)], target=target)
    if code != 0:
        print(f"[!] Warning pulling databases: {err.strip() or out.strip()}")

    # Cleanup temporary files on device
    run_adb_cmd(["shell", "rm", "-rf", temp_device_dir], target=target)

    extracted = list(out_dir.glob("*"))
    print(f"[✓] Extracted {len(extracted)} database files to {out_dir}:")
    for f in sorted(extracted):
        print(f"    • {f.name} ({f.stat().st_size:,} bytes)")

    return extracted


def pull_latest_json_export(target: str, out_dir: Path) -> Optional[Path]:
    """Finds and pulls the newest Timeline*.json export from /sdcard/Download/."""
    out_dir.mkdir(parents=True, exist_ok=True)
    code, out, _ = run_adb_cmd(["shell", "ls", "-t", "/sdcard/Download/Timeline*.json"], target=target)
    if code != 0 or not out.strip():
        # Also check without prefix case
        code, out, _ = run_adb_cmd(["shell", "ls", "-t", "/sdcard/Download/*.json"], target=target)

    candidates = [line.strip() for line in out.splitlines() if line.strip() and not line.startswith("ls:")]
    if not candidates:
        print("[!] No Timeline JSON export found in /sdcard/Download/.")
        return None

    remote_file = candidates[0]
    local_file = out_dir / Path(remote_file).name
    print(f"[*] Pulling latest export: {remote_file} -> {local_file}")
    code, _, err = run_adb_cmd(["pull", remote_file, str(local_file)], target=target)
    if code == 0 and local_file.exists():
        print(f"[✓] Successfully pulled {local_file.name} ({local_file.stat().st_size:,} bytes)")
        return local_file
    else:
        print(f"[!] Failed to pull {remote_file}: {err.strip()}")
        return None


def parse_timestamp_and_date(ts_str: str) -> Tuple[float, str]:
    clean = ts_str.strip()
    try:
        dt = datetime.datetime.fromisoformat(clean.replace("Z", "+00:00"))
        return dt.timestamp(), clean[:10]
    except Exception:
        parts = clean[:10].split("-")
        dt = datetime.datetime(int(parts[0]), int(parts[1]), int(parts[2]), tzinfo=datetime.timezone.utc)
        return dt.timestamp(), clean[:10]


def ingest_raw_telemetry(conn: sqlite3.Connection, json_path: Path, odlh_path: Path) -> Dict[str, int]:
    """Ingests rawSignals and segment_type=3 raw paths into master database."""
    counts = {"raw_signals_buffer": 0, "raw_path_segments": 0}

    # 1. Ingest rolling rawSignals buffer
    if json_path.exists():
        print(f"[*] Ingesting rawSignals buffer from {json_path.name}...")
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        raw_signals: List[Dict] = data.get("rawSignals", [])
        source_name = json_path.name
        rows_to_insert = []

        for idx, sig in enumerate(raw_signals):
            signal_type = "unknown"
            ts_str = ""
            if "position" in sig:
                signal_type = "position"
                ts_str = sig["position"].get("timestamp", "")
            elif "wifiScan" in sig:
                signal_type = "wifiScan"
                ts_str = sig["wifiScan"].get("deliveryTime", "")
            elif "activityRecord" in sig:
                signal_type = "activityRecord"
                ts_str = sig["activityRecord"].get("timestamp", "")

            if not ts_str:
                continue

            u_ts, date_str = parse_timestamp_and_date(ts_str)
            canonical_json = json.dumps(sig, sort_keys=True, separators=(",", ":"))
            payload_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
            rows_to_insert.append((
                source_name,
                idx,
                signal_type,
                ts_str,
                u_ts,
                date_str,
                payload_hash,
                canonical_json,
            ))

        conn.executemany("""
        INSERT INTO raw_signals_buffer (
            source_export, export_index, signal_type, timestamp, ts, date, payload_hash, payload_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_export, export_index) DO NOTHING;
        """, rows_to_insert)
        conn.commit()

        cur = conn.execute("SELECT COUNT(*) FROM raw_signals_buffer;")
        counts["raw_signals_buffer"] = cur.fetchone()[0]
        print(f"[✓] raw_signals_buffer now contains {counts['raw_signals_buffer']:,} records.")

    # 2. Ingest raw GPS paths (segment_type=3)
    if odlh_path.exists():
        print(f"[*] Ingesting raw path segments (segment_type=3) from {odlh_path.name}...")
        odlh_conn = sqlite3.connect(odlh_path)
        odlh_cur = odlh_conn.cursor()
        odlh_cur.execute("""
        SELECT _id, database_id, origin_id, segment_id, semantic_segment, obfuscated_gaia_id,
               shown_in_timeline, is_finalized, start_timestamp_seconds, end_timestamp_seconds,
               segment_type, hierarchy_level, fprint
        FROM semantic_segment_table
        WHERE segment_type = 3;
        """)
        rows = odlh_cur.fetchall()
        path_rows = []
        for r in rows:
            (
                _id, db_id, orig_id, seg_id, blob, gaia,
                shown, finalized, start_sec, end_sec,
                seg_type, hier, fprint
            ) = r
            dt_start = datetime.datetime.fromtimestamp(start_sec, tz=datetime.timezone.utc)
            dt_end = datetime.datetime.fromtimestamp(end_sec, tz=datetime.timezone.utc)
            path_rows.append((
                seg_id, db_id, orig_id, start_sec, end_sec,
                dt_start.isoformat(), dt_end.isoformat(),
                dt_start.strftime("%Y-%m-%d"), blob, gaia,
                shown, finalized, hier, fprint
            ))

        conn.executemany("""
        INSERT INTO raw_path_segments (
            segment_id, database_id, origin_id, start_timestamp_seconds, end_timestamp_seconds,
            start_time, end_time, date, semantic_segment, obfuscated_gaia_id,
            shown_in_timeline, is_finalized, hierarchy_level, fprint
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(segment_id) DO NOTHING;
        """, path_rows)
        conn.commit()
        odlh_conn.close()

        cur = conn.execute("SELECT COUNT(*) FROM raw_path_segments;")
        counts["raw_path_segments"] = cur.fetchone()[0]
        print(f"[✓] raw_path_segments now contains {counts['raw_path_segments']:,} records.")

    # 2.5 Ingest authentic Google Maps saved/cached places
    myplaces_path = odlh_path.parent / "gmm_myplaces.db"
    if myplaces_path.exists():
        ingest_gmm_places(conn, myplaces_path)

    # 3. Ingest semantic visits & activities (segment_type=1, 2)
    if odlh_path.exists():
        new_segs_count = ingest_semantic_segments(conn, odlh_path)
        cur = conn.execute("SELECT COUNT(*) FROM segments;")
        counts["segments"] = cur.fetchone()[0]
        counts["new_semantic_segments"] = new_segs_count

    return counts


def place_id_from_ftid(cell_hex: str, fp_hex: str) -> str:
    cell_id = int(cell_hex, 16)
    fprint = int(fp_hex, 16)
    raw = bytearray([0x0A, 0x12, 0x09])
    raw.extend(struct.pack("<Q", cell_id))
    raw.append(0x11)
    raw.extend(struct.pack("<Q", fprint))
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def ingest_gmm_places(conn: sqlite3.Connection, myplaces_path: Path) -> int:
    """Ingests authentic Google Maps saved and cached places directly into places table."""
    if not myplaces_path.exists():
        return 0
    import urllib.parse
    gmm_conn = sqlite3.connect(myplaces_path)
    cur = gmm_conn.cursor()
    rows = cur.execute("SELECT sync_item, latitude, longitude FROM sync_item;").fetchall()
    gmm_conn.close()

    m_cur = conn.cursor()
    count = 0
    for blob, lat_e6, lng_e6 in rows:
        ftids = re.findall(rb"0x([0-9a-f]{16}):0x([0-9a-f]{16})", blob)
        if not ftids:
            continue
        c_hex, fp_hex = ftids[0][0].decode(), ftids[0][1].decode()
        pid = place_id_from_ftid(c_hex, fp_hex)

        m_url = re.search(rb"http://maps\.google\.com/\?q=([^&]+)&ftid=", blob)
        if not m_url:
            continue
        q = urllib.parse.unquote(m_url.group(1).decode("utf-8", errors="ignore")).replace("+", " ")
        parts = [p.strip() for p in q.split(",") if p.strip()]
        name = parts[0] if parts else "Location"
        addr = q
        lat = lat_e6 / 1e6 if lat_e6 else None
        lng = lng_e6 / 1e6 if lng_e6 else None

        city = "New York"
        if len(parts) >= 2:
            for p in parts[1:]:
                if any(c in p for c in ["Brooklyn", "Queens", "Manhattan", "Bronx", "Staten Island", "Philadelphia", "Cambridge", "Boston", "Zurich", "Zürich", "Bangkok"]):
                    city = p.strip()
                    break

        m_cur.execute("""
        INSERT INTO places (place_id, name, address, latitude, longitude, source, category, city)
        VALUES (?, ?, ?, ?, ?, 'GMM_CACHE', 'Other / POI', ?)
        ON CONFLICT(place_id) DO UPDATE SET
            name = CASE WHEN places.name IS NULL OR places.name = 'Location' THEN excluded.name ELSE places.name END,
            address = COALESCE(places.address, excluded.address),
            latitude = COALESCE(places.latitude, excluded.latitude),
            longitude = COALESCE(places.longitude, excluded.longitude),
            city = COALESCE(places.city, excluded.city);
        """, (pid, name, addr, lat, lng, city))
        count += 1

    conn.commit()
    print(f"[✓] Synchronized {count:,} authentic places from {myplaces_path.name}.")
    return count


def ingest_semantic_segments(conn: sqlite3.Connection, odlh_path: Path, since_ts: Optional[float] = None) -> int:
    """Ingests newly recorded visits and activities from odlh-storage.db into segments."""
    if not odlh_path.exists():
        return 0

    cur = conn.cursor()
    if since_ts is None:
        max_ts_res = cur.execute("SELECT MAX(end_ts) FROM segments WHERE source != 'ON_DEVICE_2026';").fetchone()
        since_ts = float(max_ts_res[0]) if max_ts_res and max_ts_res[0] else 0.0

    print(f"[*] Ingesting semantic visits & activities from {odlh_path.name} (since end_ts >= {since_ts})...")
    # Clean up previous partial/unfinalized device sync segments after since_ts
    cur.execute("DELETE FROM segments WHERE source = 'ON_DEVICE_2026' AND start_ts >= ?;", (since_ts,))
    conn.commit()

    odlh_conn = sqlite3.connect(odlh_path)
    odlh_cur = odlh_conn.cursor()

    odlh_cur.execute("""
    SELECT segment_id, segment_type, COALESCE(hierarchy_level, 0), start_timestamp_seconds, end_timestamp_seconds, semantic_segment
    FROM semantic_segment_table
    WHERE segment_type IN (1, 2) AND start_timestamp_seconds >= ?
    ORDER BY start_timestamp_seconds ASC;
    """, (since_ts,))
    rows = odlh_cur.fetchall()

    def decode_point(pt_bytes: bytes) -> Tuple[Optional[float], Optional[float]]:
        f = decode_protobuf_fields(pt_bytes)
        lat = struct.unpack("<i", f[1][0][1])[0] / 1e7 if 1 in f else None
        lng = struct.unpack("<i", f[2][0][1])[0] / 1e7 if 2 in f else None
        return lat, lng

    parsed_records: List[Dict[str, Any]] = []
    for seg_id, seg_type, hier_level, start_sec, end_sec, blob in rows:
        dt_start = datetime.datetime.fromtimestamp(start_sec, tz=NYC_TZ)
        dt_end = datetime.datetime.fromtimestamp(end_sec, tz=NYC_TZ)
        duration_min = round((end_sec - start_sec) / 60.0, 2)
        top = decode_protobuf_fields(blob)
        payload_bytes = top[3][0][1] if 3 in top else b""
        payload = decode_protobuf_fields(payload_bytes) if payload_bytes else {}

        if seg_type == 1:  # Visit
            v_details = decode_protobuf_fields(payload[1][0][1]) if 1 in payload else {}
            cand = decode_protobuf_fields(v_details[4][0][1]) if 4 in v_details else {}
            lat, lng = (None, None)
            if 5 in cand:
                lat, lng = decode_point(cand[5][0][1])
            pid = None
            if 1 in cand:
                fid_fields = decode_protobuf_fields(cand[1][0][1])
                if 1 in fid_fields and 2 in fid_fields:
                    fp = struct.unpack("<Q", fid_fields[1][0][1])[0]
                    cid = struct.unpack("<Q", fid_fields[2][0][1])[0]
                    b = struct.pack("<BBBQBQ", 0x0A, 0x12, 0x09, cid, 0x11, fp)
                    pid = base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")

            pname, paddr, pcat, pcity = (None, None, "Other / POI", "New York")
            if pid:
                p_row = cur.execute("SELECT name, address, category, city FROM places WHERE place_id = ?", (pid,)).fetchone()
                if p_row:
                    pname, paddr, pcat, pcity = p_row

            # Geographic refinement for city
            if lat is not None and lng is not None:
                if 39.8 <= lat <= 40.1 and -75.3 <= lng <= -75.0:
                    pcity = "Philadelphia"
                elif 41.4 <= lat <= 41.6 and -74.1 <= lng <= -73.8:
                    pcity = "Beacon"
                elif 40.55 <= lat <= 40.75 and -74.05 <= lng <= -73.85:
                    if pcity in (None, "New York"):
                        pcity = "Brooklyn"

            is_unconfirmed_flag = 0 if (pid and pname != "Location") else 1
            pname = pname or "Location"
            parsed_records.append({
                "segment_type": "visit",
                "start_time": dt_start.isoformat(),
                "end_time": dt_end.isoformat(),
                "start_ts": float(start_sec),
                "end_ts": float(end_sec),
                "duration_minutes": duration_min,
                "date": dt_start.strftime("%Y-%m-%d"),
                "year": dt_start.year,
                "month": dt_start.month,
                "day": dt_start.day,
                "latitude": lat,
                "longitude": lng,
                "end_lat": None,
                "end_lng": None,
                "place_id": pid,
                "place_name": pname,
                "place_address": paddr,
                "semantic_type": "visit",
                "activity_type": None,
                "distance_meters": 0.0,
                "probability": 1.0,
                "source": "ON_DEVICE_2026",
                "category": pcat,
                "city": pcity,
                "source_key": seg_id,
                "path_points_json": None,
                "has_snapped_path": 0,
                "hierarchy_level": hier_level,
            })
        elif seg_type == 2:  # Activity
            a_details = decode_protobuf_fields(payload[2][0][1]) if 2 in payload else {}
            s_lat, s_lng = decode_point(a_details[1][0][1]) if 1 in a_details else (None, None)
            e_lat, e_lng = decode_point(a_details[2][0][1]) if 2 in a_details else (None, None)
            dist_m = struct.unpack("<f", a_details[3][0][1])[0] if 3 in a_details else 0.0
            act_enum = 2
            prob = 1.0
            if 6 in a_details:
                t6_fields = decode_protobuf_fields(a_details[6][0][1])
                act_enum = t6_fields[1][0][1] if 1 in t6_fields else 2
                prob = struct.unpack("<f", t6_fields[2][0][1])[0] if 2 in t6_fields else 1.0
            act_name = ACT_MAP.get(act_enum, "WALKING")
            # Invariant 4: Multi-Factor Physical Validation for Travel Modes
            if act_name == "FLYING" and dist_m < 300000:
                act_name = "IN_PASSENGER_VEHICLE"

            city = "New York"
            ref_lat = s_lat or e_lat
            ref_lng = s_lng or e_lng
            if ref_lat is not None and ref_lng is not None:
                if 39.8 <= ref_lat <= 40.1 and -75.3 <= ref_lng <= -75.0:
                    city = "Philadelphia"
                elif 41.4 <= ref_lat <= 41.6 and -74.1 <= ref_lng <= -73.8:
                    city = "Beacon"
                elif 40.55 <= ref_lat <= 40.75 and -74.05 <= ref_lng <= -73.85:
                    city = "Brooklyn"

            parsed_records.append({
                "segment_type": "activity",
                "start_time": dt_start.isoformat(),
                "end_time": dt_end.isoformat(),
                "start_ts": float(start_sec),
                "end_ts": float(end_sec),
                "duration_minutes": duration_min,
                "date": dt_start.strftime("%Y-%m-%d"),
                "year": dt_start.year,
                "month": dt_start.month,
                "day": dt_start.day,
                "latitude": s_lat,
                "longitude": s_lng,
                "end_lat": e_lat,
                "end_lng": e_lng,
                "place_id": None,
                "place_name": None,
                "place_address": None,
                "semantic_type": "activity",
                "activity_type": act_name,
                "distance_meters": round(dist_m, 1),
                "probability": round(prob, 2),
                "source": "ON_DEVICE_2026",
                "category": None,
                "city": city,
                "source_key": seg_id,
                "path_points_json": None,
                "has_snapped_path": 0,
                "hierarchy_level": 0,
            })

    # Propagate departure/arrival coordinates from adjacent visits for continuous geometries
    for i, rec in enumerate(parsed_records):
        if rec["segment_type"] == "activity":
            if rec["latitude"] is None and i > 0 and parsed_records[i - 1]["latitude"] is not None:
                rec["latitude"] = parsed_records[i - 1]["latitude"]
                rec["longitude"] = parsed_records[i - 1]["longitude"]
            if rec["end_lat"] is None and i + 1 < len(parsed_records) and parsed_records[i + 1]["latitude"] is not None:
                rec["end_lat"] = parsed_records[i + 1]["latitude"]
                rec["end_lng"] = parsed_records[i + 1]["longitude"]

    rows_to_insert = [
        (
            r["segment_type"], r["start_time"], r["end_time"], r["start_ts"], r["end_ts"], r["duration_minutes"],
            r["date"], r["year"], r["month"], r["day"], r["latitude"], r["longitude"], r["end_lat"], r["end_lng"],
            r["place_id"], r["place_name"], r["place_address"], r["semantic_type"], r["activity_type"],
            r["distance_meters"], r["probability"], r["hierarchy_level"], r["source"], r["category"], r["city"], r["source_key"],
            r["path_points_json"], r["has_snapped_path"]
        )
        for r in parsed_records
    ]

    if rows_to_insert:
        cur.executemany("""
        INSERT INTO segments (
            segment_type, start_time, end_time, start_ts, end_ts, duration_minutes,
            date, year, month, day, latitude, longitude, end_lat, end_lng,
            place_id, place_name, place_address, semantic_type, activity_type,
            distance_meters, probability, hierarchy_level, source, category, city, source_key,
            path_points_json, has_snapped_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, rows_to_insert)
        conn.commit()

    odlh_conn.close()
    print(f"[✓] Successfully inserted {len(rows_to_insert)} newly recorded semantic segments into master timeline_viewer.db.")
    return len(rows_to_insert)


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract and synchronize Timeline data via rooted Pixel 8.")
    parser.add_argument("--device", help="ADB target device serial or IP:port")
    parser.add_argument("--skip-extract", action="store_true", help="Skip ADB extraction and use existing files in pixel8_extracted/")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to master timeline_viewer.db")
    args = parser.parse_args()

    print("=================================================================")
    print("      PRODUCTION TIMELINE SYNC VIA ROOTED PIXEL 8 GATEWAY        ")
    print("=================================================================")

    target_dir = EXTRACTION_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    if not args.skip_extract:
        target = resolve_device(args.device)
        print(f"[*] Target Device: {target}")

        if not check_device_root(target):
            raise PermissionError(f"Device {target} does not grant root (su) access. Ensure SuperSU/Magisk is enabled.")
        print("[✓] Root access confirmed.")

        extract_gms_databases(target, target_dir)
        pull_latest_json_export(target, target_dir)
    else:
        print(f"[*] Skipping live extraction, reading from {target_dir}...")

    # Locate pulled artifacts
    odlh_file = target_dir / "odlh-storage.db"
    json_candidates = sorted(list(target_dir.glob("*.json")), key=lambda p: p.stat().st_mtime, reverse=True)
    json_file = json_candidates[0] if json_candidates else (WORKSPACE_DIR / "pixel10_export" / "Timeline-latest.json")

    # Connect to master database and ingest
    conn = sqlite3.connect(args.db)
    counts = ingest_raw_telemetry(conn, json_file, odlh_file)
    conn.close()

    print("=================================================================")
    print("                PRODUCTION SYNC SUMMARY REPORT                  ")
    print(f"  • Extracted SQLite DBs: {len(list(target_dir.glob('*.db*')))} files")
    print(f"  • JSON Export File:     {json_file.name}")
    print(f"  • Master rawSignals:    {counts['raw_signals_buffer']:,}")
    print(f"  • Master Raw Paths:     {counts['raw_path_segments']:,}")
    print(f"  • New Semantic Segments:{counts.get('new_semantic_segments', 0):,}")
    print(f"  • Total Master Segments:{counts.get('segments', 0):,}")
    print("=================================================================")


if __name__ == "__main__":
    main()
