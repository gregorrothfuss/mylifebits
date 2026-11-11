"""
Overview & Global Health Scorecard API.
"""

from __future__ import annotations

from typing import Any, Dict

from api.db import get_read_db, query_all, query_one
from api.response import Response, json_response
from api.router import Request, router


@router.get("/api/overview")
def get_overview(req: Request) -> Response:
    """Returns the system health scorecard, date range, categories, and top cities."""
    from diagnostics import TimelineDiagnosticsEngine

    with get_read_db() as conn:
        scorecard = TimelineDiagnosticsEngine(conn=conn).get_health_scorecard()

    scorecard["min_date"] = scorecard["date_range"][0]
    scorecard["max_date"] = scorecard["date_range"][1]

    # Categories
    categories = query_all("""
        SELECT category, COUNT(*) as places_cnt, COALESCE(SUM(visit_count), 0) as total_visits
        FROM places
        WHERE category IS NOT NULL AND category != ''
        GROUP BY category
        ORDER BY total_visits DESC;
    """)
    scorecard["category_breakdown"] = categories

    # Top Cities
    top_cities = query_all("""
        SELECT city, country, COUNT(*) as places_cnt, COALESCE(SUM(visit_count), 0) as total_visits
        FROM places
        WHERE city IS NOT NULL AND city NOT IN ('Unknown', 'Other', '')
        GROUP BY city, country
        ORDER BY total_visits DESC
        LIMIT 15;
    """)
    scorecard["top_cities"] = top_cities

    # Reviews & Navigation Badge Counts
    rev_row = (
        query_one("""
        SELECT COUNT(*) as total_rev, COUNT(DISTINCT matched_place_id) as matched_pois
        FROM poi_reviews;
    """)
        or {}
    )
    scorecard["total_reviews"] = rev_row.get("total_rev", 0)
    scorecard["reviewed_pois"] = rev_row.get("matched_pois", 0)

    badge_row = (
        query_one("""
        SELECT
            (SELECT COUNT(*) FROM places WHERE COALESCE(visit_count, 0) >= 1) as visited_places_count,
            (SELECT COUNT(*) FROM trips) as total_trips,
            (SELECT COUNT(*) FROM fix_proposals WHERE status = 'PENDING') as pending_fixes;
    """)
        or {}
    )
    scorecard["visited_places_count"] = int(badge_row.get("visited_places_count") or 0)
    scorecard["total_trips"] = int(badge_row.get("total_trips") or 0)
    scorecard["pending_fixes"] = int(badge_row.get("pending_fixes") or 0)

    return json_response({"status": "SUCCESS", "scorecard": scorecard})
