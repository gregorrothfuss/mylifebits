"""
POI Loss Prevention & Spatial Place Reconciliation Engine.

Reconciles unconfirmed, nameless, or raw-coordinate visits against:
1. Date-aware residences & workplaces (life_periods)
2. Custom labeled places (custom_labeled_places)
3. Canonical places catalog (places) with multi-factor scoring
4. Reverse geocoding (OpenStreetMap Nominatim / Google) as fallback
"""

import json
import math
import os
import re
import sqlite3
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from breadcrumbs import haversine_distance
from life_periods import get_date_aware_label

DEFAULT_DB_PATH = "timeline_viewer.db"

NAMELESS_PLACE_PATTERNS = {
    "",
    "none",
    "null",
    "place",
    "home/place",
    "unconfirmed location",
    "saved location",
    "point of interest",
    "stationary dwell",
    "stationary location",
    "unknown",
    "unknown_location",
}

COORDINATE_LOCATION_REGEX = re.compile(r"^location\s*\([0-9\.\-,\s]+\)$", re.IGNORECASE)


def is_nameless_place(name: Optional[str]) -> bool:
    """Returns True if the place name is empty, a generic placeholder, or a raw coordinate string."""
    if not name:
        return True
    clean = name.strip().lower()
    if clean in NAMELESS_PLACE_PATTERNS:
        return True
    if COORDINATE_LOCATION_REGEX.match(clean):
        return True
    return False


def init_place_aliases_table(conn: sqlite3.Connection) -> None:
    """Ensures the place_aliases table exists to permanently track mutated/new Google Place IDs."""
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS place_aliases (
            alias_place_id TEXT PRIMARY KEY,
            canonical_place_id TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_place_aliases_canonical ON place_aliases(canonical_place_id);")


def get_aliased_place(conn: sqlite3.Connection, place_id: str) -> Optional[Dict[str, Any]]:
    """Resolves an incoming place_id to its canonical place record if aliased."""
    if not place_id:
        return None
    init_place_aliases_table(conn)
    c = conn.cursor()
    c.execute(
        """
        SELECT p.place_id, p.name, p.address, p.category, p.city, p.country,
               p.latitude, p.longitude, p.visit_count, p.review_rating, p.has_review
        FROM place_aliases pa
        JOIN places p ON pa.canonical_place_id = p.place_id
        WHERE pa.alias_place_id = ?;
        """,
        (place_id,),
    )
    row = c.fetchone()
    if row:
        return {
            "place_id": row[0],
            "name": row[1],
            "address": row[2],
            "category": row[3] or "Other / POI",
            "city": row[4],
            "country": row[5],
            "latitude": row[6],
            "longitude": row[7],
            "visit_count": row[8] or 0,
            "review_rating": row[9],
            "has_review": row[10] or 0,
            "matched_by": "place_aliases",
        }
    return None


def record_place_alias(conn: sqlite3.Connection, alias_place_id: str, canonical_place_id: str) -> None:
    """Permanently records that alias_place_id maps to canonical_place_id."""
    if not alias_place_id or not canonical_place_id or alias_place_id == canonical_place_id:
        return
    init_place_aliases_table(conn)
    c = conn.cursor()
    c.execute(
        """
        INSERT OR IGNORE INTO place_aliases (alias_place_id, canonical_place_id)
        VALUES (?, ?);
        """,
        (alias_place_id, canonical_place_id),
    )



def get_nearby_catalog_candidates(
    conn: sqlite3.Connection,
    lat: float,
    lng: float,
    max_radius_meters: float = 65.0,
) -> List[Dict[str, Any]]:
    """Fetches valid places from the catalog within a bounding box and scores them."""
    # 0.001 deg lat is ~111m, 0.0012 deg lng is ~100m at NYC latitudes
    lat_delta = max_radius_meters / 111000.0 * 1.5
    lng_delta = max_radius_meters / (111000.0 * math.cos(math.radians(lat))) * 1.5

    c = conn.cursor()
    c.execute(
        """
        SELECT place_id, name, address, latitude, longitude, category,
               visit_count, review_rating, has_review, primary_type
        FROM places
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
          AND name IS NOT NULL
          AND latitude BETWEEN ? AND ?
          AND longitude BETWEEN ? AND ?;
        """,
        (lat - lat_delta, lat + lat_delta, lng - lng_delta, lng + lng_delta),
    )

    rows = c.fetchall()
    candidates = []

    for r in rows:
        pid, name, addr, c_lat, c_lng, cat, vc, rating, has_rev, p_type = r
        if is_nameless_place(name):
            continue

        dist = haversine_distance(lat, lng, c_lat, c_lng)
        if dist > max_radius_meters:
            continue

        # Multi-factor scoring
        # Direct coordinate match (<1.5m) is highest possible priority
        if dist <= 1.5:
            score = 10000.0 - dist
        else:
            score = max(0.0, 100.0 - dist)
            # Bias toward previously visited places
            if vc and vc > 0:
                score += min(50.0, vc * 4.0)
            # Bias toward reviewed / confirmed places
            if has_rev or rating:
                score += 15.0
            if addr and len(addr) > 5:
                score += 10.0

        candidates.append(
            {
                "place_id": pid,
                "name": name,
                "address": addr,
                "category": cat or "Other / POI",
                "latitude": c_lat,
                "longitude": c_lng,
                "distance_meters": dist,
                "score": score,
                "visit_count": vc or 0,
            }
        )

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates


def reconcile_place_spatial(
    db_path: str,
    lat: float,
    lng: float,
    date_str: Optional[str] = None,
    max_radius_meters: float = 65.0,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """
    Reconciles an unconfirmed or raw-coordinate visit against:
    1. Chronological life periods (Home residences, Work offices)
    2. Custom labeled places
    3. Existing canonical places catalog with multi-factor scoring
    """
    if lat is None or lng is None:
        return None

    # 1. Date-aware residence or office
    if date_str:
        lbl, cat = get_date_aware_label(db_path, None, lat, lng, date_str)
        if lbl and not is_nameless_place(lbl):
            return {
                "place_id": f"life_period_{lat:.4f}_{lng:.4f}",
                "name": lbl,
                "address": None,
                "category": cat or "Home & Residence",
                "distance_meters": 0.0,
                "matched_by": "life_period",
            }

    close_conn = False
    if conn is None:
        conn = sqlite3.connect(db_path, timeout=30.0)
        close_conn = True

    try:
        # 2. Check custom_labeled_places within 35m
        c = conn.cursor()
        c.execute(
            """
            SELECT name, address, latitude, longitude
            FROM custom_labeled_places
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL
              AND abs(latitude - ?) < 0.0005 AND abs(longitude - ?) < 0.0005;
            """,
            (lat, lng),
        )
        for cl_name, cl_addr, cl_lat, cl_lng in c.fetchall():
            if not is_nameless_place(cl_name):
                d = haversine_distance(lat, lng, cl_lat, cl_lng)
                if d <= 35.0:
                    return {
                        "place_id": f"custom_label_{cl_lat:.4f}_{cl_lng:.4f}",
                        "name": cl_name,
                        "address": cl_addr,
                        "category": "Home & Residence" if "Home" in cl_name else "Other / POI",
                        "distance_meters": d,
                        "matched_by": "custom_labeled_places",
                    }

        # 3. Check canonical catalog places
        candidates = get_nearby_catalog_candidates(conn, lat, lng, max_radius_meters=max_radius_meters)
        if candidates:
            best = candidates[0]
            best["matched_by"] = "places_catalog"
            return best

    finally:
        if close_conn:
            conn.close()

    return None


def reverse_geocode_osm(lat: float, lng: float, timeout_sec: float = 5.0) -> Optional[Dict[str, Any]]:
    """
    Reverse geocodes coordinates via Photon (Komoot OSM) with Nominatim fallback.
    Extracts venue names, street addresses, and cities to eliminate raw coordinate fallbacks.
    """
    # 1. Try Photon first (high availability, fast, no harsh rate limits)
    try:
        photon_url = f"https://photon.komoot.io/reverse?lat={lat:.6f}&lon={lng:.6f}"
        req = urllib.request.Request(photon_url, headers={"User-Agent": "GregorMyLifeBits/2.0"})
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            features = data.get("features", [])
            if features:
                props = features[0].get("properties", {})
                name = (
                    props.get("name")
                    or f"{props.get('housenumber', '')} {props.get('street', '')}".strip()
                    or props.get("street")
                )
                city = props.get("city") or props.get("locality") or props.get("district")
                state = props.get("state")
                country = props.get("country")
                postcode = props.get("postcode")
                addr_parts = [p for p in [name, props.get("street"), city, state, postcode, country] if p]
                dedup_addr = []
                for part in addr_parts:
                    if part not in dedup_addr:
                        dedup_addr.append(part)
                formatted_addr = ", ".join(dedup_addr)

                osm_value = props.get("osm_value", "").lower()
                category = "Other / POI"
                if any(k in osm_value for k in ["cafe", "restaurant", "bar", "bakery", "fast_food", "food"]):
                    category = "Food & Drink"
                elif any(k in osm_value for k in ["museum", "artwork", "attraction", "gallery"]):
                    category = "Arts & Entertainment"
                elif any(k in osm_value for k in ["park", "pitch", "station", "stop", "platform", "dyke", "greenway"]):
                    category = "Travel & Transit"

                if name:
                    return {
                        "name": name,
                        "address": formatted_addr or name,
                        "city": city,
                        "country": country,
                        "category": category,
                    }
    except Exception:
        pass

    # 2. Fallback to Nominatim
    url = f"https://nominatim.openstreetmap.org/reverse?lat={lat:.6f}&lon={lng:.6f}&format=jsonv2&addressdetails=1"
    headers = {
        "User-Agent": "GregorMyLifeBits/2.0 (personal archival timeline system)",
        "Accept": "application/json",
    }
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                display_name = data.get("display_name", "")
                address = data.get("address", {})

                # Determine best name: amenity, shop, tourism, leisure, building, or road
                name = (
                    data.get("name")
                    or address.get("amenity")
                    or address.get("shop")
                    or address.get("tourism")
                    or address.get("leisure")
                    or address.get("building")
                )

                if not name:
                    house_num = address.get("house_number", "")
                    road = address.get("road", "")
                    if road:
                        name = f"{house_num} {road}".strip() if house_num else road

                city = (
                    address.get("city")
                    or address.get("town")
                    or address.get("village")
                    or address.get("hamlet")
                    or address.get("municipality")
                )
                country = address.get("country")

                category = "Other / POI"
                if any(k in address for k in ["amenity", "shop", "cafe", "restaurant", "bakery", "bar"]):
                    category = "Food & Drink"
                elif any(k in address for k in ["tourism", "attraction", "museum"]):
                    category = "Arts & Entertainment"
                elif any(k in address for k in ["leisure", "park"]):
                    category = "Travel & Transit"

                return {
                    "name": name or display_name.split(",")[0].strip(),
                    "address": display_name,
                    "city": city,
                    "country": country,
                    "category": category,
                }
        except urllib.error.HTTPError as he:
            if he.code == 429:
                import time
                time.sleep(1.5 * (attempt + 1))
                continue
            return None
        except Exception:
            import time
            time.sleep(1.0)
            continue
    return None


def resolve_visit_place(
    db_path: str,
    lat: float,
    lng: float,
    current_name: Optional[str] = None,
    current_address: Optional[str] = None,
    date_str: Optional[str] = None,
    incoming_place_id: Optional[str] = None,
    allow_reverse_geocode: bool = True,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """
    Complete end-to-end place resolver:
    1. If incoming_place_id is already in place_aliases, returns canonical place immediately.
    2. If current_name is a valid, non-placeholder name, returns None (already resolved).
    3. Spatially reconciles against places catalog, life periods, and custom labeled places.
       If matched and incoming_place_id is provided, automatically records place alias.
    4. If no catalog match and allow_reverse_geocode is True, falls back to reverse geocode.
    """
    close_conn = False
    if conn is None:
        conn = sqlite3.connect(db_path, timeout=30.0)
        close_conn = True

    try:
        # 1. Check known place aliases
        if incoming_place_id:
            aliased = get_aliased_place(conn, incoming_place_id)
            if aliased:
                return aliased

        if not is_nameless_place(current_name):
            return None

        # 2. Spatial match against existing catalog & life periods
        match = reconcile_place_spatial(db_path, lat, lng, date_str=date_str, conn=conn)
        if match:
            # If Google minted a new Place ID for an existing venue, permanently alias it
            if incoming_place_id and match.get("place_id") and incoming_place_id != match["place_id"]:
                record_place_alias(conn, incoming_place_id, match["place_id"])
                if close_conn:
                    conn.commit()
            return match

        # 3. If allowed, reverse geocode to eliminate raw coordinate fallbacks
        if allow_reverse_geocode and lat is not None and lng is not None:
            geo = reverse_geocode_osm(lat, lng)
            if geo and geo.get("name"):
                geo["place_id"] = incoming_place_id or f"osm_{lat:.5f}_{lng:.5f}"
                geo["distance_meters"] = 0.0
                geo["matched_by"] = "reverse_geocode_osm"
                return geo

        return None
    finally:
        if close_conn:
            conn.close()

