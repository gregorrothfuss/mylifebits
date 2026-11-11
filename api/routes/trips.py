"""
Trips, Expeditions, Passport Stats, and Nuggets API.
"""

from __future__ import annotations

from typing import Any, Dict, List

from api.db import get_db_path
from api.response import Response, error_response, json_response
from api.router import Request, router
from enrichment.nuggets_engine import extract_archive_nuggets, get_activity_summaries
from enrichment.trip_inferencer import get_country_passport_stats
from trips_engine import get_all_trips


@router.get("/api/trips")
def get_trips(req: Request) -> Response:
    """Returns detected multi-day trips and expeditions."""
    limit = min(250, max(1, req.get_int("limit", 150)))
    country = req.get_str("country")
    trips = get_all_trips(get_db_path(), limit=limit, country=country if country else None)
    return json_response({"status": "SUCCESS", "count": len(trips), "trips": trips})


@router.get("/api/trips/stats")
def get_trip_stats(req: Request) -> Response:
    """Returns all-time country passport stats, flights, and expedition totals."""
    stats = get_country_passport_stats(get_db_path())
    return json_response(stats)


@router.get("/api/insights/activity-summaries")
def get_activity_summaries_route(req: Request) -> Response:
    """Returns activity breakdowns, mode distributions, and nuggets by period."""
    period = req.get_str("period", "all")
    data = get_activity_summaries(get_db_path(), period=period)
    return json_response(data)


@router.get("/api/insights/nuggets")
def get_nuggets(req: Request) -> Response:
    """Returns interesting algorithmic facts and nuggets extracted from the timeline."""
    raw = extract_archive_nuggets(get_db_path())
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

        data = generate_trip_flythrough_data(trip_id, get_db_path())
        return json_response(data)
    except Exception as e:
        return error_response(f"Error generating trip flythrough: {e}", status_code=500)


@router.get("/api/trips/export.kml")
def export_trip_kml(req: Request) -> Response:
    """Exports Google Earth KML 2.2 tour for a specific trip_id or all expeditions."""
    import re
    from xml.sax.saxutils import escape as xml_escape

    from enrichment.kml_tour_generator import generate_earth_tour_kml
    from trips_engine import generate_trip_flythrough_data

    trip_id = req.get_str("trip_id")
    db_path = get_db_path()

    if trip_id:
        data = generate_trip_flythrough_data(trip_id, db_path)
        if data.get("status") != "SUCCESS":
            return error_response(data.get("error", "Trip not found"), status_code=404)

        pts: List[List[float]] = [
            [float(p["lat"]), float(p["lng"])]
            for p in data.get("trajectory", [])
            if p.get("lat") is not None and p.get("lng") is not None
        ]
        if len(pts) < 2:
            for arc in data.get("flight_arcs", []):
                if arc.get("from") and arc.get("to"):
                    pts.append([float(arc["from"][0]), float(arc["from"][1])])
                    pts.append([float(arc["to"][0]), float(arc["to"][1])])

        hotspots = data.get("hotspots", [])
        orig_name = hotspots[0]["title"] if hotspots else "Origin"
        dest_name = hotspots[-1]["title"] if hotspots else "Destination"
        kml_str = generate_earth_tour_kml(
            title=str(data.get("title") or trip_id),
            description=f"Expedition starting {data.get('start_date', '')}",
            points=pts,
            mode="EXPEDITION",
            origin_name=orig_name,
            dest_name=dest_name,
        )
        safe_slug = re.sub(r"[^a-zA-Z0-9_\-]+", "_", trip_id).strip("_") or "trip"
        return Response(
            body=kml_str.encode("utf-8"),
            status_code=200,
            content_type="application/vnd.google-earth.kml+xml; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="google_earth_trip_{safe_slug}.kml"'
            },
        )

    from api.db import query_one

    trips = get_all_trips(db_path, limit=250)
    placemarks: List[str] = []
    for t in trips:
        lat = t.get("center_lat")
        lng = t.get("center_lng")
        if (lat is None or lng is None) and t.get("start_ts") is not None and t.get("end_ts") is not None:
            rep = query_one(
                """
                SELECT latitude, longitude FROM segments
                WHERE start_ts >= ? AND end_ts <= ? AND latitude IS NOT NULL AND longitude IS NOT NULL
                ORDER BY start_ts ASC LIMIT 1;
                """,
                (t["start_ts"], t["end_ts"]),
            )
            if rep:
                lat = rep["latitude"]
                lng = rep["longitude"]
        if lat is None or lng is None:
            continue
        t_title = xml_escape(str(t.get("title") or t.get("country") or "Trip"))
        t_desc = xml_escape(
            f"{t.get('start_date', '')} to {t.get('end_date', '')} ({t.get('duration_days', 0)}d)"
        )
        placemarks.append(
            f"    <Placemark>\n"
            f"      <name>{t_title}</name>\n"
            f"      <description>{t_desc}</description>\n"
            f"      <Point><coordinates>{lng},{lat},0</coordinates></Point>\n"
            f"    </Placemark>"
        )
    kml_all = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<kml xmlns="http://www.opengis.net/kml/2.2">\n'
        "  <Document>\n"
        "    <name>MyLifeBits Expeditions</name>\n"
        + "\n".join(placemarks)
        + "\n  </Document>\n</kml>"
    )
    return Response(
        body=kml_all.encode("utf-8"),
        status_code=200,
        content_type="application/vnd.google-earth.kml+xml; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="mylifebits_trips.kml"'},
    )

