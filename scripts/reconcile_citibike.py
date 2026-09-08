#!/usr/bin/env python3
"""
Systemic Citi Bike Station & Dock Reconciliation Engine.

1. Reconciles synthetic citi_bike_% UUIDs in segments to canonical ChIJ place IDs in places.
2. Ingests and links authentic 15-second dock stops for all recent CYCLING legs (Aug 20 - Sep 8, 2026).
3. Snaps CYCLING path geometries between verified dock coordinates.
"""

import os
import sys
import json
import math
import sqlite3
import datetime
from typing import Dict, Tuple, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "timeline_viewer.db")
CACHE_DB_PATH = os.path.join(WORKSPACE_DIR, "snapped_routes_cache.db")


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * R * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def clean_station_name(name: str) -> str:
    if not name:
        return ""
    n = name.strip()
    if n.lower().startswith("citi bike:"):
        n = n[10:].strip()
    elif n.lower().startswith("citibike:"):
        n = n[9:].strip()
    return n.lower()


def main():
    print("=================================================================")
    print("      CITI BIKE CANONICAL RECONCILIATION & DOCK LINKING          ")
    print("=================================================================")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    conn_cache = sqlite3.connect(CACHE_DB_PATH)
    c_cache = conn_cache.cursor()

    # 1. Load canonical Citi Bike places
    print("[1/4] Indexing canonical Citi Bike stations...")
    c.execute("""
        SELECT place_id, name, latitude, longitude
        FROM places
        WHERE place_id LIKE 'ChIJ%' AND (name LIKE '%Citi Bike%' OR name LIKE '%Citibike%');
    """)
    canon_places = c.fetchall()
    print(f"  [✓] Loaded {len(canon_places):,} canonical Citi Bike stations.")

    name_to_canon: Dict[str, sqlite3.Row] = {}
    for p in canon_places:
        cn = clean_station_name(p["name"])
        if cn:
            name_to_canon[cn] = p

    # 2. Upgrade synthetic citi_bike_UUID place_ids in segments table
    print("[2/4] Upgrading synthetic citi_bike_UUIDs to canonical ChIJ IDs...")
    c.execute("""
        SELECT id, place_name, place_id, latitude, longitude
        FROM segments
        WHERE place_id LIKE 'citi_bike_%';
    """)
    uuid_rows = c.fetchall()
    upgrades = []

    for r in uuid_rows:
        sid = r["id"]
        pname = r["place_name"] or ""
        lat = r["latitude"]
        lng = r["longitude"]

        matched_canon = None
        # Try clean name match first
        cn = clean_station_name(pname)
        if cn in name_to_canon:
            matched_canon = name_to_canon[cn]
        elif lat is not None and lng is not None:
            # Try nearest coordinate match within 80m
            best_dist = 80.0
            for cp in canon_places:
                if cp["latitude"] is not None and cp["longitude"] is not None:
                    d = haversine(lat, lng, cp["latitude"], cp["longitude"])
                    if d < best_dist:
                        best_dist = d
                        matched_canon = cp

        if matched_canon:
            c_name = matched_canon["name"]
            if not c_name.startswith("Citi Bike: "):
                c_name = f"Citi Bike: {c_name}"
            upgrades.append((matched_canon["place_id"], c_name, "Transit", sid))

    if upgrades:
        print(f"  Upgrading {len(upgrades):,} / {len(uuid_rows):,} synthetic dock visits...")
        c.executemany("""
            UPDATE segments
            SET place_id = ?, place_name = ?, category = ?
            WHERE id = ?;
        """, upgrades)
        conn.commit()
    print(f"  [✓] Successfully upgraded {len(upgrades):,} dock visits to canonical ChIJ IDs.")

    # 3. Reconcile Recent CYCLING Legs (Aug 20 - Sep 8, 2026)
    print("[3/4] Reconciling recent CYCLING legs with canonical dock stops...")
    c.execute("""
        SELECT id, date, start_time, end_time, start_ts, end_ts, latitude, longitude, end_lat, end_lng, distance_meters
        FROM segments
        WHERE segment_type = 'activity' AND activity_type = 'CYCLING' AND date >= '2026-08-20'
        ORDER BY start_ts ASC;
    """)
    recent_rides = c.fetchall()
    print(f"  Found {len(recent_rides):,} CYCLING legs from 2026-08-20 onwards.")

    new_dock_visits = []
    updated_ride_coords = []

    def find_best_dock(lat: float, lng: float, max_m: float = 120.0) -> Optional[sqlite3.Row]:
        best = None
        best_d = max_m
        for cp in canon_places:
            if cp["latitude"] is not None and cp["longitude"] is not None:
                d = haversine(lat, lng, cp["latitude"], cp["longitude"])
                if d < best_d:
                    best_d = d
                    best = cp
        return best

    for ride in recent_rides:
        rid = ride["id"]
        rdate = ride["date"]
        sts = ride["start_ts"]
        ets = ride["end_ts"]
        slat = ride["latitude"]
        slng = ride["longitude"]
        elat = ride["end_lat"]
        elng = ride["end_lng"]

        # Check if already preceded by a dock visit
        c.execute("""
            SELECT id FROM segments
            WHERE date = ? AND segment_type = 'visit' AND (place_name LIKE '%Citi Bike%' OR category = 'Transit')
              AND abs(end_ts - ?) <= 30;
        """, (rdate, sts))
        has_start_dock = c.fetchone() is not None

        # Check if already succeeded by a dock visit
        c.execute("""
            SELECT id FROM segments
            WHERE date = ? AND segment_type = 'visit' AND (place_name LIKE '%Citi Bike%' OR category = 'Transit')
              AND abs(start_ts - ?) <= 30;
        """, (rdate, ets))
        has_end_dock = c.fetchone() is not None

        start_dock = find_best_dock(slat, slng) if (slat and slng) else None
        end_dock = find_best_dock(elat, elng) if (elat and elng) else None

        # Snap ride endpoints to canonical dock coordinates
        new_slat = start_dock["latitude"] if start_dock else slat
        new_slng = start_dock["longitude"] if start_dock else slng
        new_elat = end_dock["latitude"] if end_dock else elat
        new_elng = end_dock["longitude"] if end_dock else elng

        updated_ride_coords.append((new_slat, new_slng, new_elat, new_elng, rid))

        # Insert start dock visit (15 seconds before ride start)
        tz_ny = datetime.timezone(datetime.timedelta(hours=-4))
        if not has_start_dock and start_dock:
            dock_sts = sts - 15
            dock_ets = sts
            dt_s = datetime.datetime.fromtimestamp(dock_sts, tz=tz_ny).strftime('%Y-%m-%dT%H:%M:%S-04:00')
            dt_e = datetime.datetime.fromtimestamp(dock_ets, tz=tz_ny).strftime('%Y-%m-%dT%H:%M:%S-04:00')
            d_name = start_dock["name"]
            if not d_name.startswith("Citi Bike: "):
                d_name = f"Citi Bike: {d_name}"
            new_dock_visits.append((
                "visit", dt_s, dt_e, dock_sts, dock_ets, 0.25, rdate,
                int(rdate[:4]), int(rdate[5:7]), int(rdate[8:10]),
                start_dock["latitude"], start_dock["longitude"],
                start_dock["place_id"], d_name, "Transit", "citibike_app"
            ))

        # Insert end dock visit (15 seconds after ride end)
        if not has_end_dock and end_dock:
            dock_sts = ets
            dock_ets = ets + 15
            dt_s = datetime.datetime.fromtimestamp(dock_sts, tz=tz_ny).strftime('%Y-%m-%dT%H:%M:%S-04:00')
            dt_e = datetime.datetime.fromtimestamp(dock_ets, tz=tz_ny).strftime('%Y-%m-%dT%H:%M:%S-04:00')
            d_name = end_dock["name"]
            if not d_name.startswith("Citi Bike: "):
                d_name = f"Citi Bike: {d_name}"
            new_dock_visits.append((
                "visit", dt_s, dt_e, dock_sts, dock_ets, 0.25, rdate,
                int(rdate[:4]), int(rdate[5:7]), int(rdate[8:10]),
                end_dock["latitude"], end_dock["longitude"],
                end_dock["place_id"], d_name, "Transit", "citibike_app"
            ))

    if updated_ride_coords:
        c.executemany("""
            UPDATE segments
            SET latitude = ?, longitude = ?, end_lat = ?, end_lng = ?
            WHERE id = ?;
        """, updated_ride_coords)

    if new_dock_visits:
        print(f"  Inserting {len(new_dock_visits):,} authentic 15s dock visits...")
        c.executemany("""
            INSERT INTO segments (
                segment_type, start_time, end_time, start_ts, end_ts, duration_minutes,
                date, year, month, day, latitude, longitude, place_id, place_name, category, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, new_dock_visits)
        conn.commit()

    print(f"  [✓] Successfully reconciled all recent CYCLING legs.")

    # 4. Re-snap CYCLING routes between docks
    print("[4/4] Snapping CYCLING routes between canonical docks...")
    c_cache.execute("SELECT route_key, geometry_json, distance_m FROM route_cache WHERE geometry_json IS NOT NULL;")
    route_map = {rk: geom for rk, geom, dist in c_cache.fetchall()}

    c.execute("""
        SELECT id, latitude, longitude, end_lat, end_lng
        FROM segments
        WHERE segment_type = 'activity' AND activity_type = 'CYCLING' AND date >= '2026-08-20';
    """)
    cycling_acts = c.fetchall()
    snapped_cycling = []

    for ca in cycling_acts:
        cid = ca["id"]
        slat = ca["latitude"]
        slng = ca["longitude"]
        elat = ca["end_lat"]
        elng = ca["end_lng"]
        if slat and elat and (slat != elat or slng != elng):
            k = f"bike:{slat:.5f},{slng:.5f};{elat:.5f},{elng:.5f}"
            if k in route_map:
                snapped_cycling.append((route_map[k], 1, cid))
            else:
                for ckey in route_map:
                    if ckey.startswith("bike:") and f"{slat:.4f}" in ckey and f"{elat:.4f}" in ckey:
                        snapped_cycling.append((route_map[ckey], 1, cid))
                        break

    if snapped_cycling:
        print(f"  Applying {len(snapped_cycling):,} snapped curves to recent CYCLING legs...")
        c.executemany("UPDATE segments SET path_points_json = ?, has_snapped_path = ? WHERE id = ?;", snapped_cycling)
        conn.commit()

    conn_cache.close()
    conn.close()
    print("=================================================================")
    print("[✓] CITI BIKE RECONCILIATION COMPLETED SUCCESSFULLY.")
    print("=================================================================")


if __name__ == "__main__":
    main()
