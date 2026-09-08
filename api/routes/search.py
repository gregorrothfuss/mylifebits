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

    # 2. Places / POI Search
    place_rows = query_all("""
        SELECT max(s.place_id) as place_id, s.place_name, s.place_address, s.category, s.latitude, s.longitude,
               max(s.date) as last_date, count(s.id) as visit_count, min(s.date) as first_date,
               p.review_text, p.review_rating
        FROM segments s
        LEFT JOIN places p ON s.place_id = p.place_id
        WHERE s.segment_type = 'visit' AND (s.place_name LIKE ? OR s.place_address LIKE ? OR p.review_text LIKE ?)
        GROUP BY s.place_name, s.place_address
        ORDER BY visit_count DESC
        LIMIT ?;
    """, (f"%{q}%", f"%{q}%", f"%{q}%", limit))

    for r in place_rows:
        results.append({
            "type": "PLACE",
            "place_id": r.get("place_id"),
            "title": r["place_name"] or "Home/Place",
            "subtitle": r["place_address"] or (f"{r['latitude']:.4f}, {r['longitude']:.4f}" if r.get("latitude") else "Unknown location"),
            "category": r["category"] or "Other / POI",
            "latitude": r["latitude"],
            "longitude": r["longitude"],
            "date": r["last_date"],
            "visit_count": r["visit_count"],
            "first_date": r["first_date"],
            "icon": "fa-location-dot"
        })

    # 3. Categories Search
    cat_rows = query_all("""
        SELECT category, count(DISTINCT date) as days_count, count(id) as visit_count, max(date) as last_date
        FROM segments
        WHERE category LIKE ? AND segment_type = 'visit'
        GROUP BY category
        LIMIT 3;
    """, (f"%{q}%",))

    for r in cat_rows:
        results.append({
            "type": "CATEGORY",
            "title": f"Category: {r['category']}",
            "subtitle": f"{r['visit_count']} visits across {r['days_count']} days · Last: {r['last_date']}",
            "date": r["last_date"],
            "icon": "fa-tag"
        })

    return json_response({"status": "SUCCESS", "count": len(results), "results": results[:limit]})
