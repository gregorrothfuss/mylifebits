"""
Typed Schemas and Contract Validators for Timeline Web API.
Defines explicit contracts matching static/app.js frontend requirements.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CategoryCount:
    category: str
    count: int = 0
    places_cnt: int = 0
    total_visits: int = 0


@dataclass
class CityCount:
    city: str
    country: str = ""
    count: int = 0
    places_cnt: int = 0
    total_visits: int = 0


@dataclass
class ScorecardData:
    total_segments: int = 0
    total_visits: int = 0
    total_activities: int = 0
    total_days: int = 0
    total_distance_km: float = 0.0
    place_hydration_rate_pct: float = 0.0
    path_snapping_rate_pct: float = 0.0
    gaps_count: int = 0
    anomalies_count: int = 0
    unconfirmed_visits_count: int = 0
    category_breakdown: List[Dict[str, Any]] = field(default_factory=list)
    top_cities: List[Dict[str, Any]] = field(default_factory=list)
    total_reviews: int = 0
    reviewed_pois: int = 0
    min_date: Optional[str] = None
    max_date: Optional[str] = None


@dataclass
class CalendarDayData:
    date: str
    year: int
    month: int
    day: int
    total_segments: int = 0
    visits: int = 0
    activities: int = 0
    child_visits: int = 0
    unconfirmed: int = 0
    snapped_paths: int = 0
    gaps: int = 0


@dataclass
class CalendarRangeDayData:
    date: str
    segments: List[Dict[str, Any]] = field(default_factory=list)
    gaps: List[Dict[str, Any]] = field(default_factory=list)
    total_visits: int = 0
    total_activities: int = 0
    total_duration_minutes: float = 0.0
    health_score: int = 100


@dataclass
class PlaceMapPoint:
    latitude: float
    longitude: float
    name: str
    category: str = "Other / POI"
    city: str = ""
    visit_count: int = 0
    place_id: str = ""


@dataclass
class SearchResultItem:
    type: str  # "place" | "date"
    id: str
    title: str
    subtitle: str
    date: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


def validate_contract(data: Dict[str, Any], required_keys: List[str], schema_name: str) -> None:
    """
    Strict contract assertion ensuring all required keys exist and are non-null.
    Throws ValueError with actionable diagnostic if a contract breach occurs.
    """
    missing = [k for k in required_keys if k not in data]
    if missing:
        raise ValueError(
            f"API Contract Violation in {schema_name}: missing required key(s) {missing}. "
            f"Present keys: {list(data.keys())}"
        )


def validate_points_contract(points: List[Any], schema_name: str) -> None:
    """
    Validates that a list of points contains dictionary objects with latitude and longitude,
    preventing array-of-arrays TypeError regressions in client rendering.
    """
    if not isinstance(points, list):
        raise ValueError(f"{schema_name}: points must be a list, got {type(points).__name__}")
    for idx, pt in enumerate(points[:50]):  # Check first 50 points
        if not isinstance(pt, dict):
            raise ValueError(
                f"{schema_name}: point[{idx}] must be a dict with latitude/longitude keys, got {type(pt).__name__}: {pt}"
            )
        if "latitude" not in pt and "lat" not in pt:
            raise ValueError(f"{schema_name}: point[{idx}] missing 'latitude' or 'lat': {pt}")
        if "longitude" not in pt and "lng" not in pt:
            raise ValueError(f"{schema_name}: point[{idx}] missing 'longitude' or 'lng': {pt}")


def validate_calendar_range_contract(days: Any) -> None:
    """
    Validates that /api/calendar-range returns a dict keyed by date string,
    where each value contains segments and gaps.
    """
    if not isinstance(days, dict):
        raise ValueError(f"/api/calendar-range: 'days' must be a dictionary keyed by date string, got {type(days).__name__}")
    for date_str, day_obj in list(days.items())[:10]:
        if not isinstance(day_obj, dict):
            raise ValueError(f"/api/calendar-range: day[{date_str}] must be an object, got {type(day_obj).__name__}")
        if "segments" not in day_obj or not isinstance(day_obj["segments"], list):
            raise ValueError(f"/api/calendar-range: day[{date_str}] missing 'segments' list")
        if "gaps" not in day_obj or not isinstance(day_obj["gaps"], list):
            raise ValueError(f"/api/calendar-range: day[{date_str}] missing 'gaps' list")
