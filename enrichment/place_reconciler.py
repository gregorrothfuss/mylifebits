"""
POI Loss Prevention & Spatial Place Reconciliation Engine.

Reconciles unconfirmed, nameless, or raw-coordinate visits against:
1. Date-aware residences & workplaces (life_periods)
2. Custom labeled places (custom_labeled_places)
3. Canonical places catalog (places) with multi-factor scoring
4. Reverse geocoding (OpenStreetMap Nominatim / Google) as fallback
"""

import html
import json
import math
import os
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from breadcrumbs import haversine_distance
from enrichment.place_types_taxonomy import map_google_types_to_category
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


def resolve_synthetic_feature_id(conn: sqlite3.Connection, place_id: str) -> Optional[Dict[str, Any]]:
    """
    Resolves synthetic Google cell IDs (ChIJAAAAAAAAAAAR<fingerprint>)
    by matching the 64-bit feature ID fingerprint against canonical places.
    """
    if not place_id or not place_id.startswith("ChIJAAAAAAAAAA"):
        return None
    if "R" not in place_id:
        return None
    suffix = place_id.split("R", 1)[1]
    if not suffix:
        return None
    c = conn.cursor()
    c.execute(
        """
        SELECT place_id, name, address, category, city, country,
               latitude, longitude, visit_count, review_rating, has_review
        FROM places
        WHERE place_id LIKE ? AND name IS NOT NULL AND name != ''
        LIMIT 1;
        """,
        ("%" + suffix,),
    )
    row = c.fetchone()
    if row:
        canonical_pid = row[0]
        record_place_alias(conn, place_id, canonical_pid)
        return {
            "place_id": canonical_pid,
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
            "matched_by": "synthetic_feature_id",
        }
    return None


def init_google_place_cache_table(conn: sqlite3.Connection) -> None:
    """Ensures the google_place_cache table exists to guarantee each Place ID is queried exactly ONCE."""
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS google_place_cache (
            place_id TEXT PRIMARY KEY,
            name TEXT,
            address TEXT,
            category TEXT,
            city TEXT,
            country TEXT,
            latitude REAL,
            longitude REAL,
            primary_type TEXT,
            types_json TEXT,
            status TEXT NOT NULL,
            raw_payload TEXT,
            queried_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_google_place_cache_status ON google_place_cache(status);")


def get_cached_google_place(conn: sqlite3.Connection, place_id: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Checks if place_id has already been queried in google_place_cache.
    Returns (True, place_dict) if resolved,
    returns (True, None) if previously queried and marked NOT_FOUND or INVALID (preventing re-queries),
    returns (False, None) if never queried before.
    """
    if not place_id:
        return (True, None)
    init_google_place_cache_table(conn)
    c = conn.cursor()
    c.execute(
        """
        SELECT place_id, name, address, category, city, country,
               latitude, longitude, primary_type, types_json, status
        FROM google_place_cache
        WHERE place_id = ?;
        """,
        (place_id,),
    )
    row = c.fetchone()
    if row:
        pid, name, addr, cat, city, country, lat, lng, p_type, types_json, status = row
        if status == "RESOLVED" and name and not is_nameless_place(name):
            types_list = []
            if types_json:
                try:
                    types_list = json.loads(types_json)
                except Exception:
                    pass
            return (
                True,
                {
                    "place_id": pid,
                    "name": name,
                    "address": addr,
                    "category": cat or "Other / POI",
                    "city": city,
                    "country": country,
                    "latitude": lat,
                    "longitude": lng,
                    "primary_type": p_type,
                    "types": types_list,
                    "matched_by": "google_place_cache",
                },
            )
        else:
            # Previously queried but not found or invalid; avoid re-querying!
            return (True, None)
    return (False, None)


def record_cached_google_place(
    conn: sqlite3.Connection,
    place_id: str,
    place_data: Optional[Dict[str, Any]],
    status: str = "RESOLVED",
    raw_payload: Optional[str] = None,
) -> None:
    """
    Permanently records the result of a single Google lookup in the persistent cache.
    Guarantees this place_id will never be queried across the network again.
    """
    if not place_id:
        return
    init_google_place_cache_table(conn)
    c = conn.cursor()
    if place_data and status == "RESOLVED":
        name = place_data.get("name")
        addr = place_data.get("address")
        cat = place_data.get("category", "Other / POI")
        city = place_data.get("city")
        country = place_data.get("country")
        lat = place_data.get("latitude")
        lng = place_data.get("longitude")
        p_type = place_data.get("primary_type")
        types = place_data.get("types")
        types_json = json.dumps(types) if types else None
        c.execute(
            """
            INSERT OR REPLACE INTO google_place_cache (
                place_id, name, address, category, city, country,
                latitude, longitude, primary_type, types_json, status, raw_payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (place_id, name, addr, cat, city, country, lat, lng, p_type, types_json, status, raw_payload),
        )
    else:
        c.execute(
            """
            INSERT OR REPLACE INTO google_place_cache (
                place_id, name, address, category, city, country,
                latitude, longitude, primary_type, types_json, status, raw_payload
            ) VALUES (?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?, ?);
            """,
            (place_id, status, raw_payload),
        )
    conn.commit()


def fetch_google_maps_place_details(
    place_id: str,
    api_key: Optional[str] = None,
    timeout_sec: float = 12.0,
    max_retries: int = 3,
    conn: Optional[sqlite3.Connection] = None,
    db_path: str = DEFAULT_DB_PATH,
) -> Optional[Dict[str, Any]]:
    """
    Authoritatively queries Google Maps to resolve Place ID into genuine venue name,
    address, category, types, and coordinates directly from Google.

    CRITICAL INVARIANT: Queries each Place ID exactly ONCE, permanently caching the
    result in SQLite google_place_cache to avoid any repeated lookups or billing loops.
    """
    if not place_id or not place_id.startswith("ChIJ"):
        return None

    close_conn = False
    if conn is None:
        conn = sqlite3.connect(db_path, timeout=30.0)
        close_conn = True

    try:
        # 1. Check persistent single-lookup cache first
        is_cached, cached_res = get_cached_google_place(conn, place_id)
        if is_cached:
            return cached_res

        # 2. Check canonical places catalog table
        c = conn.cursor()
        c.execute(
            """
            SELECT place_id, name, address, category, city, country,
                   latitude, longitude, primary_type, types, visit_count
            FROM places
            WHERE place_id = ?;
            """,
            (place_id,),
        )
        p_row = c.fetchone()
        if p_row and p_row[1] and not is_nameless_place(p_row[1]):
            types_list = []
            if p_row[9]:
                try:
                    types_list = json.loads(p_row[9])
                except Exception:
                    pass
            place_dict = {
                "place_id": p_row[0],
                "name": p_row[1],
                "address": p_row[2],
                "category": p_row[3] or "Other / POI",
                "city": p_row[4],
                "country": p_row[5],
                "latitude": p_row[6],
                "longitude": p_row[7],
                "primary_type": p_row[8],
                "types": types_list,
                "visit_count": p_row[10] or 0,
                "matched_by": "places_catalog",
            }
            record_cached_google_place(conn, place_id, place_dict, status="RESOLVED")
            return place_dict

        # 3. Only if never queried before, perform ONE lookup
        result = None

        # Try Google Places API (New) v1 if key configured
        key = api_key or os.environ.get("GOOGLE_MAPS_API_KEY")
        if key:
            url = f"https://places.googleapis.com/v1/places/{place_id}?key={key}"
            headers = {
                "User-Agent": "GoogleTimelineStudio/2.0",
                "X-Goog-FieldMask": "id,displayName,formattedAddress,primaryType,types,rating,location",
            }
            for attempt in range(max_retries):
                try:
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                        name = data.get("displayName", {}).get("text")
                        if name:
                            address = data.get("formattedAddress")
                            primary_type = data.get("primaryType")
                            types = data.get("types", [])
                            loc = data.get("location", {})
                            category = map_google_types_to_category(primary_type, types) or "Other / POI"
                            result = {
                                "place_id": place_id,
                                "name": name,
                                "address": address,
                                "category": category,
                                "latitude": loc.get("latitude"),
                                "longitude": loc.get("longitude"),
                                "primary_type": primary_type,
                                "types": types,
                                "matched_by": "google_places_api_v1",
                            }
                            break
                except Exception:
                    time.sleep(1.0 * (attempt + 1))

        # Otherwise, Google Maps Knowledge Graph Desktop Endpoint
        if not result:
            url = f"https://www.google.com/maps/place/?q=place_id:{place_id}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            }
            for attempt in range(max_retries):
                try:
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                        page = resp.read().decode("utf-8", errors="ignore")
                    m = re.search(r'(/maps/preview/place\?[^\"]+)', page)
                    if not m:
                        continue
                    preview_path = html.unescape(m.group(1).replace(r"\u0026", "&").replace(r"\x26", "&"))
                    full_url = "https://www.google.com" + preview_path
                    req2 = urllib.request.Request(full_url, headers=headers)
                    with urllib.request.urlopen(req2, timeout=timeout_sec) as resp2:
                        raw_preview = resp2.read().decode("utf-8", errors="ignore")
                    start_idx = raw_preview.find("[")
                    if start_idx == -1:
                        continue
                    data = json.loads(raw_preview[start_idx:])

                    name = None
                    try:
                        name = data[6][11]
                    except Exception:
                        pass
                    if not name or is_nameless_place(name):
                        continue

                    address = None
                    try:
                        address = data[6][18]
                    except Exception:
                        pass
                    if not address:
                        try:
                            parts = data[6][2]
                            if isinstance(parts, list):
                                address = ", ".join([p for p in parts if isinstance(p, str)])
                        except Exception:
                            pass

                    lat = None
                    lng = None
                    try:
                        coords = data[4][0]
                        lat = coords[2]
                        lng = coords[1]
                    except Exception:
                        pass

                    raw_types = []
                    try:
                        raw_types = data[6][13] or []
                    except Exception:
                        pass

                    norm_types = [t.lower().strip().replace(" ", "_").replace("-", "_") for t in raw_types if isinstance(t, str)]
                    category = None
                    if norm_types:
                        category = map_google_types_to_category(norm_types[0], norm_types)
                    if not category:
                        category = "Other / POI"

                    result = {
                        "place_id": place_id,
                        "name": name,
                        "address": address,
                        "category": category,
                        "latitude": lat,
                        "longitude": lng,
                        "primary_type": norm_types[0] if norm_types else None,
                        "types": raw_types,
                        "matched_by": "google_maps_knowledge_graph",
                    }
                    break
                except urllib.error.HTTPError as he:
                    if he.code in (404, 400):
                        break
                    time.sleep(1.0 * (attempt + 1))
                except Exception:
                    time.sleep(1.0 * (attempt + 1))

        # 4. Cache the result permanently (whether resolved or not found)
        if result and result.get("name") and not is_nameless_place(result["name"]):
            record_cached_google_place(conn, place_id, result, status="RESOLVED")
            save_place_to_catalog(conn, result)
            return result
        else:
            record_cached_google_place(conn, place_id, None, status="NOT_FOUND")
            return None

    finally:
        if close_conn:
            conn.close()


def save_place_to_catalog(conn: sqlite3.Connection, place_data: Dict[str, Any]) -> None:
    """Inserts or updates an enriched place into the places catalog table."""
    pid = place_data.get("place_id")
    name = place_data.get("name")
    if not pid or not name or is_nameless_place(name):
        return

    addr = place_data.get("address")
    cat = place_data.get("category", "Other / POI")
    lat = place_data.get("latitude")
    lng = place_data.get("longitude")
    p_type = place_data.get("primary_type")
    types = place_data.get("types")
    types_json = json.dumps(types) if types else None

    # Derive city/country from address
    city, country = None, None
    if addr:
        parts = [p.strip() for p in addr.split(",")]
        if len(parts) >= 2:
            country = parts[-1]
            city_state = parts[-2]
            city = city_state.split()[0] if city_state else None

    c = conn.cursor()
    c.execute(
        """
        INSERT INTO places (
            place_id, name, address, category, city, country,
            latitude, longitude, primary_type, types, user_confirmed,
            visit_count, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1, 'GOOGLE_MAPS_KNOWLEDGE_GRAPH')
        ON CONFLICT(place_id) DO UPDATE SET
            name = excluded.name,
            address = COALESCE(excluded.address, places.address),
            category = CASE WHEN places.category IS NULL OR places.category = 'Other / POI' THEN excluded.category ELSE places.category END,
            city = COALESCE(excluded.city, places.city),
            country = COALESCE(excluded.country, places.country),
            latitude = COALESCE(excluded.latitude, places.latitude),
            longitude = COALESCE(excluded.longitude, places.longitude),
            primary_type = COALESCE(excluded.primary_type, places.primary_type),
            types = COALESCE(excluded.types, places.types);
        """,
        (pid, name, addr, cat, city, country, lat, lng, p_type, types_json),
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
        # 2. Check canonical catalog places
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
    2. If incoming_place_id is a synthetic Google cell ID (ChIJAAAAAAAAAA...), resolves via 64-bit FID.
    3. If incoming_place_id is in places catalog with a valid name, returns it.
    4. If incoming_place_id is a Google Place ID (ChIJ...), resolves authoritatively via Google Maps
       with single-lookup persistent caching in google_place_cache (zero repeat queries).
    5. If current_name is a valid, non-placeholder name, returns None (already resolved).
    6. Spatially reconciles against places catalog, life periods, and custom labeled places.
       If matched and incoming_place_id is provided, automatically records place alias.
    7. If no catalog match and allow_reverse_geocode is True, falls back to reverse geocode.
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

            # 2. Check synthetic cell ID (ChIJAAAAAAAAAAAR...)
            synth = resolve_synthetic_feature_id(conn, incoming_place_id)
            if synth:
                return synth

            # 3. Check places catalog
            c = conn.cursor()
            c.execute(
                """
                SELECT place_id, name, address, category, city, country,
                       latitude, longitude, visit_count, review_rating, has_review
                FROM places WHERE place_id = ?;
                """,
                (incoming_place_id,),
            )
            p_row = c.fetchone()
            if p_row and p_row[1] and not is_nameless_place(p_row[1]):
                return {
                    "place_id": p_row[0],
                    "name": p_row[1],
                    "address": p_row[2],
                    "category": p_row[3] or "Other / POI",
                    "city": p_row[4],
                    "country": p_row[5],
                    "latitude": p_row[6],
                    "longitude": p_row[7],
                    "visit_count": p_row[8] or 0,
                    "review_rating": p_row[9],
                    "has_review": p_row[10] or 0,
                    "matched_by": "places_catalog",
                }

            # 4. Resolve authoritatively via Google Maps with single-lookup persistent caching
            if incoming_place_id.startswith("ChIJ"):
                google_match = fetch_google_maps_place_details(incoming_place_id, conn=conn, db_path=db_path)
                if google_match and google_match.get("name") and not is_nameless_place(google_match["name"]):
                    return google_match

        if not is_nameless_place(current_name):
            return None

        # 5. Spatial match against existing catalog & life periods (fallback only, never create aliases)
        match = reconcile_place_spatial(db_path, lat, lng, date_str=date_str, conn=conn)
        if match:
            return match

        return None
    finally:
        if close_conn:
            conn.close()

