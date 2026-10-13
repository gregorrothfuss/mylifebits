"""
Overview & Global Health Scorecard API.
"""

from __future__ import annotations

from typing import Any, Dict

from api.db import query_all, query_one
from api.response import Response, json_response
from api.router import Request, router


@router.get("/api/overview")
def get_overview(req: Request) -> Response:
    """Returns the system health scorecard, date range, categories, and top cities."""
    from diagnostics import TimelineDiagnosticsEngine
    diag = TimelineDiagnosticsEngine()
    scorecard = diag.get_health_scorecard()

    min_max = query_one("SELECT MIN(date) as min_date, MAX(date) as max_date FROM segments;")
    scorecard["min_date"] = min_max["min_date"] if min_max else None
    scorecard["max_date"] = min_max["max_date"] if min_max else None

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

    # Reviews
    rev_row = query_one("""
        SELECT COUNT(*) as total_rev, COUNT(DISTINCT matched_place_id) as matched_pois 
        FROM poi_reviews;
    """) or {}
    scorecard["total_reviews"] = rev_row.get("total_rev", 0)
    scorecard["reviewed_pois"] = rev_row.get("matched_pois", 0)

    return json_response({"status": "SUCCESS", "scorecard": scorecard})
