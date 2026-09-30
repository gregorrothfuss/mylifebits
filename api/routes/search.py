"""
Universal Search Engine (Dates, Months, Places, Categories, Locations, and Events).
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from api.db import query_all, query_one
from api.response import Response, json_response
from api.router import Request, router


@router.get("/api/search")
def search(req: Request) -> Response:
    """Multi-modal timeline search."""
    q = req.get_str("q").strip()
    limit = min(50, max(1, req.get_int("limit", 25)))
    if not q:
        return json_response({"status": "SUCCESS", "count": 0, "results": []})

    results: List[Dict[str, Any]] = []
    date_candidates: List[str] = []

    # 1. Date Detection (YYYY-MM-DD, MM/DD/YYYY, etc.)
    m_iso = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", q)
    if m_iso:
        y, m, d = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
        date_candidates.append(f"{y:04d}-{m:02d}-{d:02d}")

    m_us = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", q)
    if m_us and not m_iso:
        m, d, y = int(m_us.group(1)), int(m_us.group(2)), int(m_us.group(3))
        if y < 100:
            y += 2000 if y < 70 else 1900
        date_candidates.append(f"{y:04d}-{m:02d}-{d:02d}")

    for dt in set(date_candidates):
        r = query_one("SELECT count(*) as cnt, sum(distance_meters) as dist FROM segments WHERE date = ?;", (dt,))
        if r and r.get("cnt", 0) > 0:
            p_rows = query_all("SELECT DISTINCT place_name FROM segments WHERE date = ? AND place_name IS NOT NULL LIMIT 4;", (dt,))
            pnames = [row["place_name"] for row in p_rows if row.get("place_name")]
            results.append({
                "type": "DATE",
                "title": f"Day Timeline: {dt}",
                "subtitle": f"{r['cnt']} segments · {round((r.get('dist') or 0)/1000.0, 1)} km · {pnames[0] if pnames else 'Trip activity'}",
                "date": dt,
                "places": pnames,
                "icon": "fa-calendar-day"
            })

    # 2. Photo Semantic Search (Visits matching visual concepts)
    photo_visits_results: List[Dict[str, Any]] = []
    if not m_iso and not m_us:
        try:
            from api.photo_search import search_visits_by_photo_semantics
            photo_visits = search_visits_by_photo_semantics(q, limit=12, min_score=0.48)
            for v in photo_visits:
                top_p = v.get("top_photo") or {}
                cnt = v.get("photo_count", 1)
                photo_visits_results.append({
                    "type": "PHOTO_VISIT",
                    "segment_id": v["id"],
                    "place_id": v.get("place_id"),
                    "title": v["place_name"] or "Visit",
                    "subtitle": f"{cnt} photo match{'es' if cnt > 1 else ''} · {v.get('city') or v.get('place_address') or v['date']}",
                    "date": v["date"],
                    "time": f"{v['start_time']} - {v['end_time']}",
                    "category": v.get("category") or "Other / POI",
                    "latitude": v.get("latitude"),
                    "longitude": v.get("longitude"),
                    "preview_url": top_p.get("preview_url") or (f"/api/photo?sha256={top_p['sha256']}" if top_p.get("sha256") else None),
                    "sha256": top_p.get("sha256"),
                    "score": v["max_score"],
                    "photo_count": cnt,
                    "photos": v.get("photos", [])[:4],
                    "icon": "fa-camera-retro",
                })
        except Exception as e:
            # Non-blocking if photos service is unreachable
            pass

    # 3. Places / POI Search with Match Priority (Name > Address > Review)
    wildcard = f"%{q}%"
    place_limit = min(12, limit)
    place_rows = query_all("""
        SELECT max(s.place_id) as place_id, s.place_name, s.place_address, s.category, s.latitude, s.longitude,
               max(s.date) as last_date, count(s.id) as visit_count, min(s.date) as first_date,
               p.review_text, p.review_rating,
               (CASE WHEN s.place_name LIKE ? THEN 1 WHEN s.place_address LIKE ? THEN 2 ELSE 3 END) as match_priority
        FROM segments s
        LEFT JOIN places p ON s.place_id = p.place_id
        WHERE s.segment_type = 'visit' AND (s.place_name LIKE ? OR s.place_address LIKE ? OR p.review_text LIKE ?)
        GROUP BY s.place_name, s.place_address
        ORDER BY match_priority ASC, visit_count DESC
        LIMIT ?;
    """, (wildcard, wildcard, wildcard, wildcard, wildcard, place_limit))

    place_results: List[Dict[str, Any]] = []
    review_match_count = 0
    for r in place_rows:
        is_review_only = (r["match_priority"] == 3)
        if is_review_only:
            review_match_count += 1
            if review_match_count > 3:
                continue
            rev = r.get("review_text") or ""
            idx = rev.lower().find(q.lower())
            start = max(0, idx - 18)
            end = min(len(rev), idx + len(q) + 26)
            snippet = ("..." if start > 0 else "") + rev[start:end].strip() + ("..." if end < len(rev) else "")
            sub = f"Review match: \"{snippet}\""
        else:
            sub = r["place_address"] or (f"{r['latitude']:.4f}, {r['longitude']:.4f}" if r.get("latitude") else "Unknown location")

        place_results.append({
            "type": "PLACE",
            "place_id": r.get("place_id"),
            "title": r["place_name"] or "Home/Place",
            "subtitle": sub,
            "category": r["category"] or "Other / POI",
            "latitude": r["latitude"],
            "longitude": r["longitude"],
            "date": r["last_date"],
            "visit_count": r["visit_count"],
            "first_date": r["first_date"],
            "icon": "fa-location-dot",
            "is_review_match": is_review_only,
        })

    # 4. Categories Search
    category_results: List[Dict[str, Any]] = []
    cat_rows = query_all("""
        SELECT category, count(DISTINCT date) as days_count, count(id) as visit_count, max(date) as last_date
        FROM segments
        WHERE category LIKE ? AND segment_type = 'visit'
        GROUP BY category
        LIMIT 3;
    """, (f"%{q}%",))

    for r in cat_rows:
        category_results.append({
            "type": "CATEGORY",
            "title": f"Category: {r['category']}",
            "subtitle": f"{r['visit_count']} visits across {r['days_count']} days · Last: {r['last_date']}",
            "date": r["last_date"],
            "icon": "fa-tag"
        })

    all_results = results + photo_visits_results + place_results + category_results
    return json_response({"status": "SUCCESS", "count": len(all_results), "results": all_results[:limit]})


@router.get("/api/visits/search")
def search_visits(req: Request) -> Response:
    """
    Dedicated visit search by semantic visual concepts and text.
    Query params:
      q: search string (e.g. 'coffee', 'skiing', 'Central Park')
      semantic: 1 to enable CLIP photo semantic search (default: 1)
      limit: max results (default: 30)
      min_score: minimum semantic similarity score (default: 0.50)
    """
    q = req.get_str("q").strip()
    limit = min(100, max(1, req.get_int("limit", 30)))
    min_score = req.get_float("min_score", 0.50)
    use_semantic = req.get_int("semantic", 1) == 1

    if not q:
        return json_response({"status": "SUCCESS", "count": 0, "visits": []})

    visits: List[Dict[str, Any]] = []
    if use_semantic:
        try:
            from api.photo_search import search_visits_by_photo_semantics
            visits = search_visits_by_photo_semantics(q, limit=limit, min_score=min_score)
        except Exception:
            visits = []

    # If semantic search returned fewer than requested, backfill with direct text matches
    if len(visits) < limit:
        needed = limit - len(visits)
        seen_ids = {v["id"] for v in visits}
        text_matches = query_all("""
            SELECT id, date, start_ts, end_ts, start_time, end_time, duration_minutes,
                   place_name, place_address, place_id, category, latitude, longitude, city
            FROM segments
            WHERE segment_type = 'visit' AND (place_name LIKE ? OR place_address LIKE ?)
            ORDER BY start_ts DESC
            LIMIT ?;
        """, (f"%{q}%", f"%{q}%", needed * 2))

        for tm in text_matches:
            if tm["id"] in seen_ids:
                continue
            visits.append({
                "id": tm["id"],
                "date": tm["date"],
                "start_time": tm["start_time"],
                "end_time": tm["end_time"],
                "duration_minutes": tm["duration_minutes"],
                "place_name": tm["place_name"] or "Visit",
                "place_address": tm["place_address"],
                "place_id": tm["place_id"],
                "category": tm["category"] or "Other / POI",
                "city": tm["city"],
                "latitude": tm["latitude"],
                "longitude": tm["longitude"],
                "max_score": 1.0,
                "photo_count": 0,
                "photos": [],
                "top_photo": None,
            })
            seen_ids.add(tm["id"])
            if len(visits) >= limit:
                break

    return json_response({
        "status": "SUCCESS",
        "count": len(visits),
        "query": q,
        "visits": visits,
    })

