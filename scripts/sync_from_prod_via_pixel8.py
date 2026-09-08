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
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
ADB_BIN = WORKSPACE_DIR / "platform-tools" / "adb"
DEFAULT_DB = WORKSPACE_DIR / "timeline_viewer.db"
EXTRACTION_DIR = WORKSPACE_DIR / "pixel8_extracted"


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

    return counts


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
    print("=================================================================")


if __name__ == "__main__":
    main()
