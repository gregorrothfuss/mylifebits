"""
Places Catalog, Map Points, and Place Editing API.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from api.db import get_db, query_all, query_one
from api.response import Response, error_response, json_response
from api.router import Request, router


@router.get("/api/places")
def get_places(req: Request) -> Response:
    """Returns paginated places filtered by category, city, search, or bounds."""
    page = max(1, req.get_int("page", 1))
    limit = min(250, max(1, req.get_int("limit", 100)))
    offset = (page - 1) * limit

    q = req.get_str("q")
    category = req.get_str("category")
    city = req.get_str("city")
    reviewed_only = req.get_bool("reviewed_only", False)
    sort_by = req.get_str("sort_by", "visits")
    min_visits = req.get_int("min_visits", 1)

    where: List[str] = ["1=1"]
    params: List[Any] = []

    if min_visits > 0:
        where.append("visit_count >= ?")
        params.append(min_visits)

    if q:
        where.append("(name LIKE ? OR address LIKE ? OR semantic_type LIKE ? OR city LIKE ? OR review_text LIKE ?)")
        wildcard = f"%{q}%"
        params.extend([wildcard, wildcard, wildcard, wildcard, wildcard])

    if category and category.upper() != "ALL":
        where.append("category = ?")
        params.append(category)

    if city and city.upper() != "ALL":
        where.append("city = ?")
        params.append(city)

    if reviewed_only:
        where.append("has_review = 1")

    where_sql = "WHERE " + " AND ".join(where)

    # Sort order
    if sort_by == "rating":
        order_sql = "ORDER BY review_rating DESC, visit_count DESC"
    elif sort_by == "name":
        order_sql = "ORDER BY name ASC"
    elif sort_by == "first_visit":
        order_sql = "ORDER BY first_visit_time ASC"
    elif sort_by == "last_visit":
        order_sql = "ORDER BY last_visit_time DESC"
    else:
        order_sql = "ORDER BY visit_count DESC"

    # Fetch
    fetch_sql = f"""
        SELECT * FROM places
        {where_sql}
        {order_sql}
        LIMIT ? OFFSET ?;
    """
    places = query_all(fetch_sql, params + [limit, offset])

    import json
    for p in places:
        raw_photos = p.get("review_photos")
        if isinstance(raw_photos, str) and raw_photos.strip():
            try:
                p["review_photos"] = json.loads(raw_photos)
            except Exception:
                p["review_photos"] = []
        elif isinstance(raw_photos, list):
            p["review_photos"] = raw_photos
        else:
            p["review_photos"] = []

    # Category and City Facets (filtered by min_visits)
    facet_min = max(0, min_visits)
    categories = query_all("""
        SELECT category, COUNT(*) as cnt, SUM(visit_count) as visits 
        FROM places 
        WHERE category IS NOT NULL AND category != '' AND visit_count >= ?
        GROUP BY category 
        ORDER BY visits DESC;
    """, [facet_min])

    cities = query_all("""
        SELECT city, country, COUNT(*) as cnt, SUM(visit_count) as visits
        FROM places
        WHERE city IS NOT NULL AND city NOT IN ('Unknown', 'Other', '') AND visit_count >= ?
        GROUP BY city, country
        ORDER BY visits DESC
        LIMIT 30;
    """, [facet_min])

    # Total count for pagination
    total_row = query_one(f"SELECT COUNT(*) as cnt FROM places {where_sql};", params)
    total = total_row["cnt"] if total_row else len(places)

    return json_response({
        "status": "SUCCESS",
        "total": total,
        "page": page,
        "limit": limit,
        "places": places,
        "categories": categories,
        "cities": cities,
    })


@router.get("/api/places/visits")
def get_place_visits(req: Request) -> Response:
    """Returns complete list of visits for a given place_id."""
    place_id = req.get_str("place_id")
    if not place_id:
        return error_response("Missing place_id parameter", status_code=400)

    visits = query_all("""
        SELECT id, date, start_time, end_time, duration_minutes, place_name, 
               place_address, latitude, longitude, category, semantic_type
        FROM segments
        WHERE place_id = ?
        ORDER BY start_time DESC;
    """, (place_id,))

    place_meta = query_one("""
        SELECT place_id, name, address, category, city, country, latitude, longitude, 
               visit_count, review_rating, first_visit_time, last_visit_time, review_photos, review_photo_count
        FROM places
        WHERE place_id = ?;
    """, (place_id,))

    if place_meta:
        rp = place_meta.get("review_photos")
        if isinstance(rp, str) and rp.strip():
            try:
                place_meta["review_photos"] = json.loads(rp)
            except Exception:
                place_meta["review_photos"] = []
        elif not isinstance(rp, list):
            place_meta["review_photos"] = []

    photos = query_all("""
        SELECT sha256, filename, preview_path, timestamp_utc, timezone_offset,
               local_date, latitude, longitude, people, face_count
        FROM photos
        WHERE place_id = ?
        ORDER BY timestamp_utc DESC
        LIMIT 100;
    """, (place_id,))
    for p in photos:
        p["preview_url"] = f"/api/photo?sha256={p['sha256']}"

    return json_response({
        "status": "SUCCESS",
        "place_id": place_id,
        "place": place_meta,
        "count": len(visits),
        "visits": visits,
        "photos": photos,
        "photo_count": len(photos),
    })


@router.get("/api/places/map-points")
def get_places_map_points(req: Request) -> Response:
    """Returns lightweight coordinates and metadata objects for interactive map clustering."""
    category = req.get_str("category")
    city = req.get_str("city")
    q = req.get_str("q")
    min_visits = req.get_int("min_visits", 1)

    where: List[str] = ["latitude IS NOT NULL", "longitude IS NOT NULL", "latitude != 0.0"]
    params: List[Any] = []

    if min_visits > 0:
        where.append("visit_count >= ?")
        params.append(min_visits)

    if category and category.upper() != "ALL":
        where.append("category = ?")
        params.append(category)

    if city and city.upper() != "ALL":
        where.append("city = ?")
        params.append(city)

    if q:
        where.append("(name LIKE ? OR address LIKE ? OR city LIKE ?)")
        wild = f"%{q}%"
        params.extend([wild, wild, wild])

    sql = f"""
        SELECT place_id, name, address, latitude, longitude, category, city, 
               visit_count, review_rating, first_visit_time, last_visit_time
        FROM places
        WHERE {" AND ".join(where)}
        ORDER BY visit_count DESC
        LIMIT 12000;
    """
    rows = query_all(sql, params)
    return json_response({"status": "SUCCESS", "count": len(rows), "points": rows})


@router.post("/api/places/edit-place")
def edit_place(req: Request) -> Response:
    """Creates or updates place metadata and optionally relinks segments."""
    data = req.json()
    old_pid = data.get("place_id")
    new_pid = (data.get("new_place_id") or "").strip() or old_pid
    if not new_pid:
        return error_response("Missing place_id", status_code=400)

    name = (data.get("name") or "").strip()
    addr = (data.get("address") or "").strip()
    category = data.get("category", "Other / POI")
    city = data.get("city", "New York")
    country = data.get("country", "United States")
    lat = float(data["latitude"]) if data.get("latitude") is not None and data.get("latitude") != "" else None
    lng = float(data["longitude"]) if data.get("longitude") is not None and data.get("longitude") != "" else None
    relink = data.get("relink_segments", True)

    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO places (place_id, name, address, category, city, country, latitude, longitude, visit_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT(place_id) DO UPDATE SET
                name = CASE WHEN excluded.name != '' THEN excluded.name ELSE places.name END,
                address = CASE WHEN excluded.address != '' THEN excluded.address ELSE places.address END,
                category = CASE WHEN excluded.category != '' THEN excluded.category ELSE places.category END,
                city = CASE WHEN excluded.city != '' THEN excluded.city ELSE places.city END,
                country = CASE WHEN excluded.country != '' THEN excluded.country ELSE places.country END,
                latitude = COALESCE(excluded.latitude, places.latitude),
                longitude = COALESCE(excluded.longitude, places.longitude);
        """, (new_pid, name, addr, category, city, country, lat, lng))

        if relink and old_pid and old_pid != new_pid:
            c.execute("UPDATE segments SET place_id = ? WHERE place_id = ?;", (new_pid, old_pid))
            c.execute("UPDATE poi_reviews SET matched_place_id = ? WHERE matched_place_id = ?;", (new_pid, old_pid))
            c.execute("DELETE FROM places WHERE place_id = ?;", (old_pid,))

        # Update visit counts
        c.execute("""
            UPDATE places 
            SET visit_count = (SELECT COUNT(*) FROM segments WHERE place_id = ?),
                first_visit_time = (SELECT MIN(start_time) FROM segments WHERE place_id = ?),
                last_visit_time = (SELECT MAX(end_time) FROM segments WHERE place_id = ?)
            WHERE place_id = ?;
        """, (new_pid, new_pid, new_pid, new_pid))

    return json_response({"status": "SUCCESS", "place_id": new_pid})


@router.post("/api/places/merge")
def merge_places(req: Request) -> Response:
    """Merges duplicate places into a single canonical place ID."""
    data = req.json()
    can_id = data.get("canonical_place_id")
    dup_ids = data.get("duplicate_place_ids", [])
    if not can_id or not dup_ids:
        return error_response("Missing canonical_place_id or duplicate_place_ids", status_code=400)

    with get_db() as conn:
        c = conn.cursor()
        for dup_id in dup_ids:
            c.execute("UPDATE segments SET place_id = ? WHERE place_id = ?;", (can_id, dup_id))
            c.execute("UPDATE poi_reviews SET matched_place_id = ? WHERE matched_place_id = ?;", (can_id, dup_id))
            c.execute("DELETE FROM places WHERE place_id = ?;", (dup_id,))

        c.execute("""
            UPDATE places 
            SET visit_count = (SELECT COUNT(*) FROM segments WHERE place_id = ?),
                first_visit_time = (SELECT MIN(start_time) FROM segments WHERE place_id = ?),
                last_visit_time = (SELECT MAX(end_time) FROM segments WHERE place_id = ?)
            WHERE place_id = ?;
        """, (can_id, can_id, can_id, can_id))

    return json_response({"status": "SUCCESS", "canonical_place_id": can_id})


@router.get("/api/places/compare")
def compare_places(req: Request) -> Response:
    """Returns side-by-side comparison metadata and recent visits for place IDs."""
    raw_ids = req.get_str("ids")
    pids = [p.strip() for p in raw_ids.split(",") if p.strip()]
    if not pids:
        return error_response("Missing ids parameter", status_code=400)

    placeholders = ",".join(["?"] * len(pids))
    places = query_all(f"SELECT * FROM places WHERE place_id IN ({placeholders});", pids)
    for p in places:
        p["recent_segments"] = query_all(
            "SELECT id, date, start_time, end_time, duration_minutes FROM segments WHERE place_id = ? ORDER BY date DESC LIMIT 15;",
            (p["place_id"],),
        )
    return json_response({"status": "SUCCESS", "count": len(places), "places": places})


@router.post("/api/places/resolve-link")
def resolve_link(req: Request) -> Response:
    """Resolves Google Maps deep link and optionally upserts place and relinks visits."""
    data = req.json()
    raw_url = (data.get("url") or "").strip()
    old_pid = (data.get("place_id") or "").strip()
    prop_id = data.get("proposal_id")
    apply_directly = bool(data.get("apply_directly", False))

    if not raw_url:
        return error_response("Missing url parameter", status_code=400)

    from api.url_resolver import resolve_google_maps_url

    resolved = resolve_google_maps_url(raw_url)
    if not resolved.get("place_id") and not resolved.get("latitude"):
        return error_response("Could not extract place attributes from URL", status_code=422)

    if apply_directly and resolved.get("place_id"):
        can_pid = resolved["place_id"]
        name = resolved.get("name")
        addr = resolved.get("address")
        lat = resolved.get("latitude")
        lng = resolved.get("longitude")
        cat = resolved.get("category", "Other / POI")
        city = resolved.get("city", "New York")
        country = resolved.get("country", "United States")

        with get_db() as conn:
            c = conn.cursor()
            c.execute(
                """
                INSERT INTO places (place_id, name, address, category, city, country, latitude, longitude, visit_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(place_id) DO UPDATE SET
                    name = COALESCE(excluded.name, places.name),
                    address = COALESCE(excluded.address, places.address),
                    category = COALESCE(excluded.category, places.category),
                    city = COALESCE(excluded.city, places.city),
                    country = COALESCE(excluded.country, places.country),
                    latitude = COALESCE(excluded.latitude, places.latitude),
                    longitude = COALESCE(excluded.longitude, places.longitude);
                """,
                (can_pid, name, addr, cat, city, country, lat, lng),
            )

            if old_pid and old_pid != can_pid:
                c.execute("UPDATE segments SET place_id = ? WHERE place_id = ?;", (can_pid, old_pid))
                c.execute("UPDATE poi_reviews SET matched_place_id = ? WHERE matched_place_id = ?;", (can_pid, old_pid))
                c.execute("DELETE FROM places WHERE place_id = ?;", (old_pid,))

            if name:
                c.execute(
                    "UPDATE segments SET place_id = ?, place_name = ? WHERE place_name = ? AND (place_id IS NULL OR place_id = '' OR place_id LIKE 'citi_bike_%' OR place_id LIKE 'ChIJ%AAAA%');",
                    (can_pid, name, name),
                )
            if lat and lng:
                c.execute(
                    "UPDATE segments SET latitude = ?, longitude = ? WHERE place_id = ? AND (latitude IS NULL OR latitude = 0.0);",
                    (lat, lng, can_pid),
                )

            c.execute(
                """
                UPDATE places
                SET visit_count = (SELECT COUNT(*) FROM segments WHERE place_id = ?),
                    first_visit_time = (SELECT MIN(start_time) FROM segments WHERE place_id = ?),
                    last_visit_time = (SELECT MAX(end_time) FROM segments WHERE place_id = ?)
                WHERE place_id = ?;
                """,
                (can_pid, can_pid, can_pid, can_pid),
            )

            if prop_id:
                c.execute(
                    "UPDATE fix_proposals SET status = 'ACCEPTED', applied_at = datetime('now') WHERE id = ?;",
                    (prop_id,),
                )

    return json_response({"status": "SUCCESS", "place": resolved})


@router.get("/api/reviews")
def get_reviews(req: Request) -> Response:
    """Returns POI reviews matching places catalog."""
    reviews = query_all("""
        SELECT r.*, p.name as current_poi_name, p.address as current_poi_address, p.visit_count
        FROM poi_reviews r
        LEFT JOIN places p ON r.matched_place_id = p.place_id
        ORDER BY r.date DESC
        LIMIT 200;
    """)
    import json

    for r in reviews:
        raw_photos = r.get("photo_urls")
        if raw_photos and isinstance(raw_photos, str):
            try:
                r["photo_urls"] = json.loads(raw_photos)
            except Exception:
                r["photo_urls"] = []
        elif isinstance(raw_photos, list):
            r["photo_urls"] = raw_photos
        else:
            r["photo_urls"] = []
    return json_response({"status": "SUCCESS", "reviews": reviews})

