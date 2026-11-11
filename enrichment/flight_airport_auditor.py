"""
Flight Airport Continuity Auditor & Great-Circle Trajectory Correction Engine.

1. Audits all flight segments across recorded years for airport visit continuity.
2. Identifies flights missing origin or destination airport visits (e.g. takeoff from diner, landing into empty space).
3. Computes exact Great-Circle Haversine flight distances to fix Takeout GPS blackout truncation.
4. Integrates seamlessly into Timeline Studio's Fix Proposals system.
"""

import sqlite3
import datetime
import json
import os
import sys
import re
from typing import Dict, Any, List, Optional, Tuple

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from breadcrumbs import haversine_distance

KNOWN_AIRPORTS: List[Tuple[str, str, float, float, str, str, str]] = [
    ("JFK", "John F. Kennedy International Airport", 40.6413, -73.7781, "New York", "US", "ChIJG45Wb19mwokRNXsvcPYOEzo"),
    ("LGA", "LaGuardia Airport", 40.7769, -73.8740, "New York", "US", "ChIJ51cu8IlewokRarMEXr0G4F4"),
    ("EWR", "Newark Liberty International Airport", 40.6895, -74.1745, "Newark", "US", "ChIJX7q5eU5RwokRFwLgH2qFzwo"),
    ("ZRH", "Zurich Airport", 47.4582, 8.5555, "Zürich", "CH", "ChIJfXVSQEJ1kEcRWHaIRtZ3a8Y"),
    ("BSL", "EuroAirport Basel-Mulhouse-Freiburg", 47.5900, 7.5292, "Basel", "CH", "ChIJf0qwdk2Q-6sRxzFEZ3lBJpA"),
    ("GVA", "Geneva Airport", 46.2370, 6.1092, "Geneva", "CH", "ChIJN5MjroBkjEcRMKa4TvKpEeU"),
    ("SFO", "San Francisco International Airport", 37.6213, -122.3790, "San Francisco", "US", "ChIJVVVVVYx3j4ARP-BpUinnRhE"),
    ("OAK", "Oakland International Airport", 37.7213, -122.2207, "Oakland", "US", "ChIJQabAAlSEj4ARYHQBAw8MY7A"),
    ("SJC", "San Jose Mineta International Airport", 37.3639, -121.9289, "San Jose", "US", "ChIJm8Wz-sPLj4ARPn72bT9E-rw"),
    ("LAX", "Los Angeles International Airport", 33.9416, -118.4085, "Los Angeles", "US", "ChIJtU-yE9KwwoAR8a2LaVd7qHc"),
    ("DEN", "Denver International Airport", 39.8561, -104.6737, "Denver", "US", "ChIJ_0T_mCp_bIcRapy1NbQ7WEk"),
    ("ORD", "O'Hare International Airport", 41.9742, -87.9073, "Chicago", "US", "ChIJ82J3aie0D4gRS61ZAgdHF1E"),
    ("DFW", "Dallas Fort Worth International Airport", 32.8998, -97.0403, "Dallas", "US", "ChIJpyoiDWYqTIYRHCB9Bl4_MnM"),
    ("IAH", "George Bush Intercontinental Airport", 29.9902, -95.3368, "Houston", "US", "ChIJx1VD2SO0QIYRMcLAyPy0xpw"),
    ("AUS", "Austin-Bergstrom International Airport", 30.1975, -97.6664, "Austin", "US", "ChIJRf9KizuxRIYRaCfcyaj8pxw"),
    ("MIA", "Miami International Airport", 25.7959, -80.2870, "Miami", "US", "ChIJwUq5Tk232YgR4fiiy-Dan5g"),
    ("FLL", "Fort Lauderdale-Hollywood International Airport", 26.0742, -80.1506, "Fort Lauderdale", "US", "ChIJY_Zi7Zxgq4oRc0843AQFXJc"),
    ("BNA", "Nashville International Airport", 36.1263, -86.6774, "Nashville", "US", "ChIJWT0fVKtuZIgRe6I-lF2K96o"),
    ("ATL", "Hartsfield-Jackson Atlanta International Airport", 33.6407, -84.4277, "Atlanta", "US", "ChIJAVkD4S_99IgRSLCSGO-jF0E"),
    ("CLT", "Charlotte Douglas International Airport", 35.2144, -80.9473, "Charlotte", "US", "ChIJidRKt32YVogRN6fEPG9Kuho"),
    ("HSV", "Huntsville International Airport", 34.6404, -86.7731, "Huntsville", "US", "ChIJPalorC5lYogRVoaVQbbHTPo"),
    ("DTW", "Detroit Metropolitan Wayne County Airport", 42.2162, -83.3554, "Detroit", "US", "ChIJBbPw2l1PO4gR-5i_Jc_AQSM"),
    ("MSP", "Minneapolis-Saint Paul International Airport", 44.8848, -93.2223, "Minneapolis", "US", "ChIJRz8Ukctso7QRg4_s54g2lJ4"),
    ("BOS", "Boston Logan International Airport", 42.3656, -71.0096, "Boston", "US", "ChIJN0na1RRw44kRRFEtH8OUkww"),
    ("RNO", "Reno-Tahoe International Airport", 39.4986, -119.7681, "Reno", "US", "ChIJF0m8rXA_mYARQFmvIP8eQBA"),
    ("HNL", "Daniel K. Inouye International Airport", 21.3245, -157.9251, "Honolulu", "US", "ChIJX_VoMZRvAHwR3zHzy7ER0X4"),
    ("LIH", "Lihue Airport", 21.9760, -159.3390, "Kauai", "US", "ChIJ--9uPvceB3wR-4BkkxaaWEI"),
    ("LHR", "Heathrow Airport", 51.4700, -0.4543, "London", "GB", "ChIJ6W3FzTRydkgRZ0H2Q1VT548"),
    ("CDG", "Charles de Gaulle Airport", 49.0097, 2.5479, "Paris", "FR", "ChIJaYXElsMVvEIRL6rR14eBtGQ"),
    ("FRA", "Frankfurt Airport", 50.0379, 8.5622, "Frankfurt", "DE", "ChIJt3rsWFRsvS8Rj93RgbpWmqc"),
    ("MUC", "Munich Airport", 48.3537, 11.7750, "Munich", "DE", "ChIJNxJYAiCjOv8Rq2qVLTR9QUY"),
    ("AMS", "Amsterdam Airport Schiphol", 52.3105, 4.7683, "Amsterdam", "NL", "ChIJLRb94DThxUcRiPHO8YMV1cc"),
    ("BCN", "Barcelona-El Prat Airport", 41.2974, 2.0833, "Barcelona", "ES", "ChIJpY58hGSepBIR15tv-0LpK_M"),
    ("SVQ", "Seville Airport", 37.4180, -5.8931, "Seville", "ES", "ChIJuZuEjRxmEg0ROif7oHd-UgE"),
    ("LIS", "Humberto Delgado Airport", 38.7742, -9.1342, "Lisbon", "PT", "ChIJgwHZFkYyGQ0RRm0DWD6lZgo"),
    ("FEZ", "Fes Sais International Airport", 33.9273, -4.9778, "Fès", "MA", "ChIJT38KqW2Lnw0RsJYdFUj4qQQ"),
    ("RAK", "Marrakesh Menara Airport", 31.6069, -8.0363, "Marrakech", "MA", "ChIJ60hRjdPUGlkRW5c6t7glod0"),
    ("NRT", "Narita International Airport", 35.7720, 140.3929, "Tokyo", "JP", "ChIJVze90XnzImARoRp3YqEpbtU"),
    ("HND", "Haneda Airport", 35.5494, 139.7798, "Tokyo", "JP", "ChIJ45IxpAtkGGAR3_hG0anDMg0"),
    ("SIN", "Singapore Changi Airport", 1.3644, 103.9915, "Singapore", "SG", "ChIJ483Qk9YX2jERA0VOQV7d1tY"),
    ("DPS", "Ngurah Rai International Airport", -8.7482, 115.1672, "Denpasar", "ID", "ChIJM2khUBZE0i0RH8x73W3acd8"),
    ("HKG", "Hong Kong International Airport", 22.3080, 113.9185, "Hong Kong", "HK", "ChIJncZGzPPiAzQRnjaSGIKQ9fk"),
    ("TPE", "Taiwan Taoyuan International Airport", 25.0797, 121.2342, "Taipei", "TW", "ChIJ1RXSYsCfQjQRCbG1qZC2o3A"),
]


def find_nearest_airport(
    lat: Optional[float], lng: Optional[float], max_km: float = 45.0
) -> Optional[Tuple[str, str, float, float, str, str, float, str]]:
    if lat is None or lng is None:
        return None
    best = None
    min_d = 99999999.0
    for code, name, a_lat, a_lng, city, country, pid in KNOWN_AIRPORTS:
        d = haversine_distance(lat, lng, a_lat, a_lng)
        if d < min_d:
            min_d = d
            best = (code, name, a_lat, a_lng, city, country, d / 1000.0, pid)
    if best and best[6] <= max_km:
        return best
    return None


def is_airport_name(s: Optional[str]) -> bool:
    if not s:
        return False
    lower = s.lower()
    return any(k in lower for k in ["airport", "terminal", "flughafen", "aeroport", "aeropuerto", "airfield", "lufthavn"])


def audit_flight_airports(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Audits all flights for missing endpoint airports and distance truncations."""
    from db import get_db_connection, get_db_path

    conn = get_db_connection(get_db_path(db_path))
    try:
        c = conn.cursor()

        c.execute("""
        SELECT id, date, start_time, end_time, start_ts, end_ts, distance_meters,
               latitude, longitude, end_lat, end_lng
        FROM segments
        WHERE activity_type = 'FLYING'
        ORDER BY start_ts ASC;
        """)
        flights = [dict(r) for r in c.fetchall()]

        proposals: List[Dict[str, Any]] = []

        for f in flights:
            cur_d = f["distance_meters"] or 0
            true_d = (
                haversine_distance(f["latitude"], f["longitude"], f["end_lat"], f["end_lng"])
                if (f["latitude"] is not None and f["end_lat"] is not None)
                else 0.0
            )

            # Check origin window (up to 4h before flight departure)
            orig_airport = find_nearest_airport(f["latitude"], f["longitude"])
            p_is_airport = False
            p_name = ""

            if orig_airport:
                c.execute("""
                SELECT id, segment_type, activity_type, place_name, place_address, latitude, longitude, end_lat, end_lng, start_ts, end_ts
                FROM segments
                WHERE end_ts >= ? - 14400 AND start_ts <= ? + 300 AND id != ?
                ORDER BY start_ts ASC;
                """, (f["start_ts"], f["start_ts"], f["id"]))
                pre_rows = [dict(r) for r in c.fetchall()]

                for r in pre_rows:
                    if r["segment_type"] == "visit":
                        p_name = r["place_name"] or p_name
                        if is_airport_name(r["place_name"]):
                            p_is_airport = True
                            break
                        if r["latitude"] is not None and haversine_distance(r["latitude"], r["longitude"], orig_airport[2], orig_airport[3]) < 7000.0:
                            p_is_airport = True
                            break

                if not p_is_airport:
                    desc_prev = "ground transit"
                    for r in reversed(pre_rows):
                        if r.get("place_name"):
                            desc_prev = r["place_name"]
                            break
                        elif r.get("activity_type"):
                            desc_prev = r["activity_type"]

                    proposals.append({
                        "proposal_id": f"fix_flight_orig_{f['id']}",
                        "flight_id": f["id"],
                        "date": f["date"],
                        "flight_time": (f["start_time"] or "")[:16],
                        "type": "INSERT_ORIGIN_AIRPORT",
                        "airport_code": orig_airport[0],
                        "airport_iata": orig_airport[0],
                        "airport_name": orig_airport[1],
                        "city": orig_airport[4],
                        "country": orig_airport[5],
                        "lat": orig_airport[2],
                        "lng": orig_airport[3],
                        "place_id": orig_airport[7],
                        "prev_place": desc_prev,
                        "description": f"Flight on {f['date']} departs near {orig_airport[1]} ({orig_airport[0]}), but preceding segment was '{desc_prev}'. Propose inserting departure airport visit.",
                    })

            # Check destination window (up to 4h after flight landing)
            dest_airport = find_nearest_airport(f["end_lat"], f["end_lng"])
            n_is_airport = False
            n_name = ""

            if dest_airport:
                c.execute("""
                SELECT id, segment_type, activity_type, place_name, place_address, latitude, longitude, end_lat, end_lng, start_ts, end_ts
                FROM segments
                WHERE start_ts <= ? + 14400 AND end_ts >= ? - 300 AND id != ?
                ORDER BY start_ts ASC;
                """, (f["end_ts"], f["end_ts"], f["id"]))
                post_rows = [dict(r) for r in c.fetchall()]

                for r in post_rows:
                    if r["segment_type"] == "visit":
                        n_name = r["place_name"] or n_name
                        if is_airport_name(r["place_name"]):
                            n_is_airport = True
                            break
                        if r["latitude"] is not None and haversine_distance(r["latitude"], r["longitude"], dest_airport[2], dest_airport[3]) < 7000.0:
                            n_is_airport = True
                            break

                if not n_is_airport:
                    desc_next = "ground transit"
                    for r in post_rows:
                        if r.get("place_name"):
                            desc_next = r["place_name"]
                            break
                        elif r.get("activity_type"):
                            desc_next = r["activity_type"]

                    proposals.append({
                        "proposal_id": f"fix_flight_dest_{f['id']}",
                        "flight_id": f["id"],
                        "date": f["date"],
                        "flight_time": (f["end_time"] or "")[:16],
                        "type": "INSERT_DESTINATION_AIRPORT",
                        "airport_code": dest_airport[0],
                        "airport_iata": dest_airport[0],
                        "airport_name": dest_airport[1],
                        "city": dest_airport[4],
                        "country": dest_airport[5],
                        "lat": dest_airport[2],
                        "lng": dest_airport[3],
                        "place_id": dest_airport[7],
                        "next_place": desc_next,
                        "description": f"Flight on {f['date']} lands near {dest_airport[1]} ({dest_airport[0]}), but succeeding segment was '{desc_next}'. Propose inserting arrival airport visit.",
                    })

            # Distance truncation check (e.g. flight offline GPS drop)
            if true_d > 100000 and cur_d < (true_d * 0.5):
                proposals.append({
                    "proposal_id": f"fix_flight_dist_{f['id']}",
                    "flight_id": f["id"],
                    "date": f["date"],
                    "flight_time": (f["start_time"] or "")[:16],
                    "type": "FIX_FLIGHT_DISTANCE",
                    "current_distance_km": round(cur_d / 1000.0, 1),
                    "true_distance_km": round(true_d / 1000.0, 1),
                    "description": f"Flight on {f['date']} recorded distance as {cur_d/1000.0:.1f} km due to in-flight GPS loss. True Great-Circle trajectory between airports is {true_d/1000.0:.1f} km.",
                })

        return proposals
    finally:
        conn.close()


def fix_all_flight_distances(db_path: Optional[str] = None) -> int:
    """Corrects all flight distances in SQLite to true Great-Circle Haversine distances."""
    from db import get_db_connection, get_db_path

    conn = get_db_connection(get_db_path(db_path))
    try:
        c = conn.cursor()

        c.execute("""
        SELECT id, latitude, longitude, end_lat, end_lng, distance_meters
        FROM segments
        WHERE activity_type = 'FLYING' AND latitude IS NOT NULL AND end_lat IS NOT NULL;
        """)
        rows = c.fetchall()

        fixed = 0
        for sid, s_lat, s_lng, e_lat, e_lng, cur_d in rows:
            true_d = haversine_distance(s_lat, s_lng, e_lat, e_lng)
            if true_d > 100000 and (cur_d or 0) < (true_d * 0.75):
                c.execute("UPDATE segments SET distance_meters = ? WHERE id = ?;", (round(true_d, 1), sid))
                fixed += 1

        conn.commit()
        print(f"[✓] Corrected true flight trajectory distance on {fixed} flight segments.")
        return fixed
    finally:
        conn.close()


if __name__ == "__main__":
    db = "timeline_viewer.db"
    fixed_cnt = fix_all_flight_distances(db)
    props = audit_flight_airports(db)
    print(f"\n[✓] Audit Complete: Found {len(props)} actionable airport continuity proposals.")
    for p in props[:10]:
        print(f"  • [{p['date']}] {p['type']}: {p['description']}")
