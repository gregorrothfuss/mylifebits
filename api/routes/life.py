"""
Life Periods & Residency Chronology API.
"""

from __future__ import annotations

from typing import Any, Dict, List

from api.db import DEFAULT_DB_PATH, get_db
from api.response import Response, error_response, json_response
from api.router import Request, router


@router.get("/api/life-periods")
def get_life_periods(req: Request) -> Response:
    """Returns all historical residential and workplace periods."""
    try:
        from life_periods import get_all_life_periods

        periods = get_all_life_periods(DEFAULT_DB_PATH)
        return json_response({"status": "SUCCESS", "periods": periods})
    except Exception as e:
        return error_response(f"Error fetching life periods: {e}", status_code=500)


@router.post("/api/life-periods/save")
def save_life_period(req: Request) -> Response:
    """Creates a new residential or workplace life period."""
    data = req.json()
    name = data.get("name")
    p_type = data.get("type", "HOME")
    role = data.get("role_title", "")
    addr = data.get("address", "")
    s_date = data.get("start_date")
    e_date = data.get("end_date", "2026-12-31")
    lat = float(data.get("lat", 0.0))
    lng = float(data.get("lng", 0.0))
    is_curr = int(data.get("is_current", 0))
    desc = data.get("description", "")

    if not name or not s_date:
        return error_response("Missing name or start_date", status_code=400)

    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO life_periods (
                name, type, role_title, address, start_date, end_date, lat, lng, is_current, description
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (name, p_type, role, addr, s_date, e_date, lat, lng, is_curr, desc),
        )

    return json_response({"status": "SUCCESS"})
