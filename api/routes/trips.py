"""
Trips, Expeditions, Passport Stats, and Nuggets API.
"""

from __future__ import annotations

from typing import Any, Dict, List

from api.db import DEFAULT_DB_PATH
from api.response import Response, json_response
from api.router import Request, router
from enrichment.nuggets_engine import extract_archive_nuggets, get_activity_summaries
from enrichment.trip_inferencer import get_country_passport_stats
from trips_engine import get_all_trips


@router.get("/api/trips")
def get_trips(req: Request) -> Response:
    """Returns detected multi-day trips and expeditions."""
    limit = min(250, max(1, req.get_int("limit", 150)))
    country = req.get_str("country")
    trips = get_all_trips(DEFAULT_DB_PATH, limit=limit, country=country if country else None)
    return json_response({"status": "SUCCESS", "count": len(trips), "trips": trips})


@router.get("/api/trips/stats")
def get_trip_stats(req: Request) -> Response:
    """Returns all-time country passport stats, flights, and expedition totals."""
    stats = get_country_passport_stats(DEFAULT_DB_PATH)
    return json_response(stats)


@router.get("/api/insights/activity-summaries")
def get_activity_summaries_route(req: Request) -> Response:
    """Returns activity breakdowns, mode distributions, and nuggets by period."""
    period = req.get_str("period", "all")
    data = get_activity_summaries(DEFAULT_DB_PATH, period=period)
    return json_response(data)


@router.get("/api/insights/nuggets")
def get_nuggets(req: Request) -> Response:
    """Returns interesting algorithmic facts and nuggets extracted from the timeline."""
    raw = extract_archive_nuggets(DEFAULT_DB_PATH)
    return json_response({
        "status": "SUCCESS",
        "nuggets": raw.get("nuggets", []),
        "extremes": raw.get("extremes", {}),
        "rare_modes": raw.get("rare_modes", []),
        "mode_summary": raw.get("mode_summary", {}),
        "night_treks": raw.get("night_treks", []),
        "top_sanctuaries": raw.get("top_sanctuaries", []),
    })


@router.get("/api/trips/flythrough")
def get_trip_flythrough(req: Request) -> Response:
    """Generates 3D flythrough animation data for a multi-day trip."""
    trip_id = req.get_str("trip_id")
    if not trip_id:
        return error_response("Missing trip_id parameter", status_code=400)

    try:
        from trips_engine import generate_trip_flythrough_data

        data = generate_trip_flythrough_data(trip_id, DEFAULT_DB_PATH)
        return json_response(data)
    except Exception as e:
        return error_response(f"Error generating trip flythrough: {e}", status_code=500)

