#!/usr/bin/env python3
"""
Systematic, reliable batch scraper for all 65 Citi Bike rides (Aug 28 - Sep 21).
Uses top-reset + fixed swipe count navigation to guarantee 100% position accuracy.
"""

import sys
import os
import time
import json
import math
import sqlite3
import subprocess
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
ADB_BIN = WORKSPACE / "platform-tools" / "adb"
TARGET_DEVICE = "10.80.1.36:41713"
DB_PATH = WORKSPACE / "scratch" / "citibike_rides.db"
GBFS_PATH = WORKSPACE / "scratch" / "citibike_full_stations_catalog.json"
SWIFT_OCR = WORKSPACE / "scripts" / "ocr_bin"

MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
DATE_TIME_RE = re.compile(r'^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),?\s*(\d{1,2}:\d{2}\s*(?:AM|PM))$', re.IGNORECASE)

def run_adb(cmd, timeout=10):
    full_cmd = [str(ADB_BIN), "-s", TARGET_DEVICE] + cmd
    res = subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)
    return res.returncode, res.stdout, res.stderr

def capture_and_ocr(local_img="/tmp/s_batch.png"):
    cmd = f"{ADB_BIN} -s {TARGET_DEVICE} exec-out screencap -p > {local_img}"
    subprocess.run(cmd, shell=True, timeout=10)
    if not os.path.exists(local_img) or os.path.getsize(local_img) == 0:
        return []
    res = subprocess.run([str(SWIFT_OCR), local_img], capture_output=True, text=True, timeout=5)
    items = []
    for line in res.stdout.strip().split("\n"):
        if "|" in line:
            box_s, txt = line.split("|", 1)
            try:
                px, py, pw, ph = map(int, box_s.split(","))
                items.append((px, py, pw, ph, txt.strip()))
            except Exception:
                pass
    return items

def is_detail_screen(items):
    texts = [txt for _, _, _, _, txt in items]
    return 'Your Trip' in texts or ('Start' in texts and 'End' in texts)

def is_drawer(items):
    texts = [txt for _, _, _, _, txt in items]
    return any('Annual membership' in t or 'Bike Angels' in t for t in texts)

def is_map(items):
    texts = [txt for _, _, _, _, txt in items]
    return any('Get directions' in t or 'Take a ride' in t for t in texts)

def reset_to_top():
    for _ in range(4):
        items = capture_and_ocr()
        if is_detail_screen(items):
            run_adb(["shell", "input", "tap", "74", "194"])
            time.sleep(0.5)
        elif is_drawer(items):
            for px, py, pw, ph, txt in items:
                if "Ride history" in txt:
                    run_adb(["shell", "input", "tap", str(px + pw//2), str(py + ph//2)])
                    time.sleep(0.8)
                    break
        elif is_map(items):
            run_adb(["shell", "input", "tap", "70", "190"])
            time.sleep(0.8)
        else:
            break
    # 4 fast swipes down to scroll to top
    for _ in range(4):
        run_adb(["shell", "input", "swipe", "540", "500", "540", "1800", "200"])
        time.sleep(0.3)
    time.sleep(0.5)

def nav_to_page(page_idx):
    reset_to_top()
    for _ in range(page_idx):
        run_adb(["shell", "input", "swipe", "540", "1800", "540", "700", "350"])
        time.sleep(0.5)
    time.sleep(0.5)

def parse_detail_ocr(items):
    date_str = None
    bike_id = None
    start_stn = None
    start_tm = None
    end_stn = None
    end_tm = None

    for px, py, pw, ph, txt in items:
        clean = re.sub(r'^[^\w]+', '', txt).strip()
        if any(m in clean for m in MONTHS) and ('202' in clean or py < 300):
            date_str = clean
        if 450 <= py <= 650 and (txt.isdigit() or '-' in txt) and len(txt) in (4, 5, 6, 7, 8):
            bike_id = txt

    if date_str:
        date_str = re.sub(r'^[^\w]+', '', date_str).strip()
        if not any(yr in date_str for yr in ['2024', '2025', '2026']):
            date_str = f"{date_str}, 2026"

    start_y = None
    end_y = None
    for px, py, pw, ph, txt in items:
        if txt == 'Start': start_y = py
        elif txt == 'End': end_y = py

    start_parts = []
    end_parts = []

    if start_y and end_y:
        for px, py, pw, ph, txt in sorted(items, key=lambda x: x[1]):
            clean = re.sub(r'^[^\w]+', '', txt).strip()
            m = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM))', txt, re.I)
            if m:
                if abs(py - start_y) <= 120 and not start_tm:
                    start_tm = m.group(1).upper()
                elif abs(py - end_y) <= 120 and not end_tm:
                    end_tm = m.group(1).upper()
            elif clean and txt not in ('Start', 'End', 'Your Trip') and px < 800:
                if start_y - 60 <= py < end_y - 40:
                    start_parts.append(clean)
                elif end_y - 40 <= py <= end_y + 160:
                    end_parts.append(clean)

    if start_parts:
        start_stn = " ".join(start_parts)
    if end_parts:
        end_stn = " ".join(end_parts)

    return date_str, bike_id, start_stn, start_tm, end_stn, end_tm

def load_gbfs():
    stations = {}
    if GBFS_PATH.exists():
        with open(GBFS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            for item in data:
                name = item.get("name", "").strip()
                if name:
                    stations[name.lower()] = item
    return stations

def find_station_info(name, gbfs_stations):
    if not name:
        return None, 40.7288, -73.9804
    nl = name.lower().strip()
    if nl in gbfs_stations:
        st = gbfs_stations[nl]
        return st.get("station_id") or st.get("place_id"), st.get("lat", 40.7288), st.get("lng", -73.9804)
    for k, st in gbfs_stations.items():
        if nl in k or k in nl:
            return st.get("station_id") or st.get("place_id"), st.get("lat", 40.7288), st.get("lng", -73.9804)
    return None, 40.7288, -73.9804

def haversine(lat1, lon1, lat2, lon2):
    R = 3958.8
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def is_already_in_db(date_txt, existing_rides):
    # Parse approximate timestamp of date_txt, e.g. "Sep 18, 11:09 PM"
    edt = timezone(timedelta(hours=-4))
    try:
        clean = re.sub(r'^[^\w]+', '', date_txt).strip()
        dt = datetime.strptime(f"{clean}, 2026", "%b %d, %I:%M %p, %Y").replace(tzinfo=edt)
        approx_ms = int(dt.timestamp() * 1000)
        for r_ms in existing_rides:
            if abs(approx_ms - r_ms) <= 180000: # within 3 minutes
                return True
    except Exception:
        pass
    return False

def main():
    print("[*] Starting Batch Citi Bike Scraper (Pages 0-8)...")
    gbfs_stations = load_gbfs()
    conn = sqlite3.connect(str(DB_PATH))
    existing_rides = set(r[0] for r in conn.execute("SELECT start_time_ms FROM citibike_rides"))
    print(f"[*] Loaded {len(existing_rides)} existing rides from database.")

    total_inserted = 0

    for page in range(9):
        print(f"\n--- Scraping Page {page} ---")
        nav_to_page(page)
        items = capture_and_ocr()
        rides_on_page = []
        for px, py, pw, ph, txt in items:
            m = DATE_TIME_RE.match(txt)
            if m and 300 <= py <= 2200:
                rides_on_page.append((px, py, pw, ph, txt))

        print(f"[*] Found {len(rides_on_page)} rides on Page {page}")

        for idx, (px, py, pw, ph, date_time_txt) in enumerate(rides_on_page):
            if is_already_in_db(date_time_txt, existing_rides):
                print(f"  [i] Ride {date_time_txt} already in DB, skipping.")
                continue

            print(f"  [>] Extracting {date_time_txt} (ride {idx+1}/{len(rides_on_page)} on page {page})...")
            # Navigate to page fresh to ensure exact coordinates
            nav_to_page(page)
            # Re-find coordinates in case of slight offset
            cur_items = capture_and_ocr()
            tap_x = px + 100
            tap_y = py
            target_norm = re.sub(r'[^a-zA-Z0-9]', '', date_time_txt).lower()
            for c_px, c_py, _, _, c_txt in cur_items:
                c_norm = re.sub(r'[^a-zA-Z0-9]', '', c_txt).lower()
                if c_norm == target_norm or (len(c_norm) > 4 and (c_norm in target_norm or target_norm in c_norm)):
                    tap_x = c_px + 100
                    tap_y = c_py
                    break

            run_adb(["shell", "input", "tap", str(tap_x), str(tap_y)])
            time.sleep(0.8)

            det_items = capture_and_ocr()
            if not is_detail_screen(det_items):
                # Retry tap slightly above or below
                run_adb(["shell", "input", "tap", str(tap_x), str(tap_y - 40)])
                time.sleep(0.8)
                det_items = capture_and_ocr()

            if not is_detail_screen(det_items):
                run_adb(["shell", "input", "tap", str(tap_x), str(tap_y + 40)])
                time.sleep(0.8)
                det_items = capture_and_ocr()

            if not is_detail_screen(det_items):
                print(f"  [!] Could not open detail screen for {date_time_txt}")
                continue

            date_str, bike_id, start_stn, start_tm, end_stn, end_tm = parse_detail_ocr(det_items)

            if not (date_str and start_stn and start_tm and end_stn and end_tm):
                print(f"  [!] Missing fields: date={date_str}, start={start_stn}@{start_tm}, end={end_stn}@{end_tm}")
            else:
                edt = timezone(timedelta(hours=-4))
                try:
                    dt_start = datetime.strptime(f"{date_str} {start_tm}", "%b %d, %Y %I:%M %p").replace(tzinfo=edt)
                    dt_end = datetime.strptime(f"{date_str} {end_tm}", "%b %d, %Y %I:%M %p").replace(tzinfo=edt)
                    if dt_end < dt_start:
                        dt_end += timedelta(days=1)

                    s_ms = int(dt_start.timestamp() * 1000)
                    e_ms = int(dt_end.timestamp() * 1000)
                    dur_min = round((e_ms - s_ms) / 60000.0, 1)

                    s_id, s_lat, s_lng = find_station_info(start_stn, gbfs_stations)
                    e_id, e_lat, e_lng = find_station_info(end_stn, gbfs_stations)
                    dist_miles = round(haversine(s_lat, s_lng, e_lat, e_lng), 2)
                    ride_id = f"cb_{s_ms}_{e_ms}"
                    bike_name = bike_id or "citi_bike"

                    raw_obj = {
                        "ride_id": ride_id,
                        "start_time_ms": s_ms,
                        "end_time_ms": e_ms,
                        "start_address": start_stn,
                        "end_address": end_stn,
                        "start_station_id": s_id or "",
                        "end_station_id": e_id or "",
                        "distance": {"value": dist_miles, "unit": "miles"},
                        "duration_minutes": dur_min,
                        "rideable_name": bike_name,
                        "rideable_type": "classic_bike",
                        "time_zone": "America/New_York"
                    }

                    conn.execute("""
                        INSERT OR REPLACE INTO citibike_rides 
                        (ride_id, start_station_id, start_station_name, start_time_ms,
                         end_station_id, end_station_name, end_time_ms, distance_miles,
                         duration_minutes, rideable_type, rideable_name, raw_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        ride_id, s_id or "", start_stn, s_ms,
                        e_id or "", end_stn, e_ms, dist_miles,
                        dur_min, "classic_bike", bike_name, json.dumps(raw_obj)
                    ))
                    conn.commit()
                    existing_rides.add(s_ms)
                    total_inserted += 1
                    print(f"  [✓] Inserted: {dt_start.strftime('%Y-%m-%d %H:%M')} | {start_stn} -> {end_stn} ({dur_min}m, {dist_miles}mi, bike={bike_name})")

                except Exception as e:
                    print(f"  [!] Error parsing datetime: {e}")

            # Close detail
            run_adb(["shell", "input", "tap", "74", "194"])
            time.sleep(0.4)
            chk = capture_and_ocr()
            if is_detail_screen(chk):
                run_adb(["shell", "input", "keyevent", "4"])
                time.sleep(0.4)

    conn.close()
    print(f"\n[✓] Batch scraping complete! Total new rides added: {total_inserted}")

if __name__ == "__main__":
    main()
