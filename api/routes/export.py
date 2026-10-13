"""
GeoJSON & GPX Export API.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from api.db import query_all
from api.response import Response, error_response, json_response
from api.router import Request, router


@router.get("/api/export")
def export_day(req: Request) -> Response:
    """Exports daily segments as GeoJSON FeatureCollection."""
    date_str = req.get_str("date")
    fmt = req.get_str("format", "geojson").lower()

    if fmt != "geojson":
        return error_response(f"Unsupported format '{fmt}'. Only 'geojson' is supported.", status_code=400)

    segs = query_all("SELECT * FROM segments WHERE date = ? ORDER BY start_ts;", (date_str,))
    features: List[Dict[str, Any]] = []

    for s in segs:
        if s["segment_type"] == "visit" and s.get("latitude") is not None and s.get("longitude") is not None:
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [s["longitude"], s["latitude"]]
                },
                "properties": {
                    "id": s["id"],
                    "type": "visit",
                    "name": s["place_name"] or s["semantic_type"],
                    "category": s["category"],
                    "city": s["city"],
                    "rating": s["review_rating"],
                    "start": s["start_time"],
                    "end": s["end_time"]
                }
            })
        elif s["segment_type"] == "activity":
            coords: List[List[float]] = []
            if s.get("path_points_json"):
                try:
                    pts = json.loads(s["path_points_json"])
                    coords = [[p[1], p[0]] for p in pts if len(p) >= 2]
                except Exception:
                    coords = []

            if not coords and s.get("latitude") is not None and s.get("end_lat") is not None:
                coords = [[s["longitude"], s["latitude"]], [s["end_lng"], s["end_lat"]]]

            if coords:
                dist_km = round((s["distance_meters"] or 0.0) / 1000.0, 2)
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": coords
                    },
                    "properties": {
                        "id": s["id"],
                        "type": "activity",
                        "activity_type": s["activity_type"],
                        "distance_km": dist_km,
                        "start": s["start_time"],
                        "end": s["end_time"]
                    }
                })

    return json_response({"type": "FeatureCollection", "features": features})
