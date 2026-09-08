#!/usr/bin/env python3
"""
Purge stale synthetic fix proposals, remap remaining synthetic Citi Bike segments
to canonical Google ChIJ Place IDs, and delete unreferenced synthetic place rows.
"""

import json
import sqlite3
from pathlib import Path

DB_PATH = Path("timeline_viewer.db")
SCRAPED_STATIONS_PATH = Path("scratch/scraped_all_citibike_stations.json")

# Mapping of the 6 remaining stations to canonical Google Place IDs and coordinates
STATION_MAP = {
    "citi_bike_66db9845-0aca-11e7-82f6-3863bb44ef7c": {
        "place_id": "ChIJwZVT9ZpZwokRBfO1cTF0MNo",
        "name": "Citi Bike: Sullivan St & Washington Sq",
        "address": "Sullivan St & Washington Sq, New York, NY 10012, USA",
        "lat": 40.73047747,
        "lng": -73.99906065,
    },
    "citi_bike_66ddd369-0aca-11e7-82f6-3863bb44ef7c": {
        "place_id": "ChIJwZVT9ZpZwokRBfO1cTF0MNo",
        "name": "Citi Bike: Mercer St & Bleecker St",
        "address": "Mercer St & Bleecker St, New York, NY 10012, USA",
        "lat": 40.72706363,
        "lng": -73.99662137,
    },
    "citi_bike_westbrdwaywattsst": {
        "place_id": "ChIJ0Rgkh4tZwokRz0P0RbSZOOc",
        "name": "Citi Bike: West Broadway & Watts St",
        "address": "West Broadway & Watts St, New York, NY 10013, USA",
        "lat": 40.7225,
        "lng": -74.0042,
    },
    "citi_bike_66dd4841-0aca-11e7-82f6-3863bb44ef7c": {
        "place_id": "ChIJkxmhxb9YwokR7GX1DnOb0MI",
        "name": "Citi Bike: E 77 St & 3 Ave",
        "address": "E 77 St & 3 Ave, New York, NY 10075, USA",
        "lat": 40.77314236,
        "lng": -73.95856158,
    },
    "citi_bike_66dde208-0aca-11e7-82f6-3863bb44ef7c": {
        "place_id": "ChIJl3D5taRYwokRa7LAMRDDTA0",
        "name": "Citi Bike: E 89 St & 3 Ave",
        "address": "E 89 St & 3 Ave, New York, NY 10128, USA",
        "lat": 40.7806284,
        "lng": -73.9521667,
    },
    "citi_bike_66de2707-0aca-11e7-82f6-3863bb44ef7c": {
        "place_id": "ChIJN2i2q-lYwokRBEzsU1F7pOo",
        "name": "Citi Bike: E 65 St & 2 Ave",
        "address": "E 65 St & 2 Ave, New York, NY 10065, USA",
        "lat": 40.76471852,
        "lng": -73.9622207,
    },
}


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    print("=== Step 1: Purging Stale Fake Proposals ===")
    c.execute("""
        DELETE FROM fix_proposals
        WHERE patch_data_json LIKE '%citi_bike_startedat%'
           OR reasoning LIKE '%citi_bike_startedat%'
           OR (target_type = 'place' AND target_id = 0 AND reasoning LIKE '%citi_bike_%');
    """)
    print(f"Purged {c.rowcount} stale synthetic Citi Bike proposals from fix_proposals.")

    print("\n=== Step 2: Remapping 26 Synthetic Segments to Canonical ChIJ IDs ===")
    remapped_count = 0
    for synth_id, meta in STATION_MAP.items():
        # Ensure canonical place exists in places table
        c.execute("""
            INSERT INTO places (place_id, name, address, category, city, country, latitude, longitude, visit_count)
            VALUES (?, ?, ?, 'Travel & Transit', 'New York', 'United States', ?, ?, 0)
            ON CONFLICT(place_id) DO UPDATE SET
                name = COALESCE(excluded.name, places.name),
                address = COALESCE(excluded.address, places.address),
                category = 'Travel & Transit',
                latitude = COALESCE(excluded.latitude, places.latitude),
                longitude = COALESCE(excluded.longitude, places.longitude);
        """, (meta["place_id"], meta["name"], meta["address"], meta["lat"], meta["lng"]))

        # Update segments
        c.execute("""
            UPDATE segments
            SET place_id = ?,
                place_name = ?,
                place_address = ?,
                latitude = COALESCE(latitude, ?),
                longitude = COALESCE(longitude, ?)
            WHERE place_id = ?;
        """, (meta["place_id"], meta["name"], meta["address"], meta["lat"], meta["lng"], synth_id))
        remapped_count += c.rowcount

    print(f"Remapped {remapped_count} segments to canonical Google ChIJ Place IDs.")

    # Check remaining citi_bike_% in segments
    c.execute("SELECT count(*) FROM segments WHERE place_id LIKE 'citi_bike%';")
    remaining_segments = c.fetchone()[0]
    print(f"Remaining segments with citi_bike_% place_id: {remaining_segments}")
    assert remaining_segments == 0, f"Expected 0 remaining synthetic segments, got {remaining_segments}!"

    print("\n=== Step 3: Purging Unreferenced Synthetic Places ===")
    c.execute("""
        DELETE FROM places
        WHERE place_id LIKE 'citi_bike%'
          AND place_id NOT IN (SELECT DISTINCT place_id FROM segments WHERE place_id IS NOT NULL);
    """)
    print(f"Purged {c.rowcount} unreferenced synthetic citi_bike_% records from places table.")

    conn.commit()
    conn.close()
    print("\n[SUCCESS] Fake proposals purged, Citi Bike dock segments canonicalized to ChIJ IDs.")


if __name__ == "__main__":
    main()
