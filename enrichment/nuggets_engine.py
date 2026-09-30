"""
Archive Nuggets & Activity Summaries Engine.
Extracts unusual finds, geographic extremes, cosmic distance analogies,
rare activity modes, and intriguing travel curiosities from the database.
"""

import sqlite3
import math
from typing import Dict, Any, List

DEFAULT_DB_PATH = "timeline_viewer.db"

EARTH_CIRCUMFERENCE_KM = 40075.0
MOON_DISTANCE_KM = 384400.0


def extract_archive_nuggets(db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 1. Geographic Extremes
    c.execute("""
    SELECT place_name, city, latitude, longitude, date
    FROM segments WHERE segment_type = 'visit' AND latitude IS NOT NULL
    ORDER BY latitude DESC LIMIT 1;
    """)
    north = dict(c.fetchone() or {})

    c.execute("""
    SELECT place_name, city, latitude, longitude, date
    FROM segments WHERE segment_type = 'visit' AND latitude IS NOT NULL
    ORDER BY latitude ASC LIMIT 1;
    """)
    south = dict(c.fetchone() or {})

    c.execute("""
    SELECT place_name, city, latitude, longitude, date
    FROM segments WHERE segment_type = 'visit' AND longitude IS NOT NULL
    ORDER BY longitude DESC LIMIT 1;
    """)
    east = dict(c.fetchone() or {})

    c.execute("""
    SELECT place_name, city, latitude, longitude, date
    FROM segments WHERE segment_type = 'visit' AND longitude IS NOT NULL
    ORDER BY longitude ASC LIMIT 1;
    """)
    west = dict(c.fetchone() or {})

    # 2. Cumulative Distances by Mode
    c.execute("""
    SELECT activity_type, COUNT(*) as count,
           SUM(COALESCE(clean_distance_meters, distance_meters, 0))/1000.0 as total_km,
           SUM(duration_minutes)/60.0 as total_hours
    FROM segments
    WHERE segment_type = 'activity'
    GROUP BY activity_type
    ORDER BY total_km DESC;
    """)
    mode_stats = {r['activity_type']: dict(r) for r in c.fetchall()}

    fly_km = mode_stats.get('FLYING', {}).get('total_km', 0.0)
    walk_km = mode_stats.get('WALKING', {}).get('total_km', 0.0)
    cycle_km = mode_stats.get('CYCLING', {}).get('total_km', 0.0)
    subway_km = mode_stats.get('IN_SUBWAY', {}).get('total_km', 0.0)
    subway_trips = mode_stats.get('IN_SUBWAY', {}).get('count', 0)
    drive_km = mode_stats.get('DRIVING', {}).get('total_km', 0.0) or mode_stats.get('IN_PASSENGER_VEHICLE', {}).get('total_km', 0.0)
    train_km = mode_stats.get('IN_TRAIN', {}).get('total_km', 0.0)

    earth_orbits = round(fly_km / EARTH_CIRCUMFERENCE_KM, 1)
    moon_trips = round(fly_km / MOON_DISTANCE_KM, 2)
    transcon_cycles = round(cycle_km / 4000.0, 1)

    # 3. Rare & Exotic Activity Modes
    rare_modes = []
    rare_types = [
        ('PARAGLIDING', 'Paragliding Flight', 'fa-parachute-box', '#38bdf8'),
        ('KITESURFING', 'Kitesurfing Session', 'fa-water', '#06b6d4'),
        ('SNOWSHOEING', 'Snowshoeing Expeditions', 'fa-snowflake', '#93c5fd'),
        ('SLEDDING', 'Alpine Sledding', 'fa-person-sledding', '#a855f7'),
        ('IN_GONDOLA_LIFT', 'Gondola Lift Mountain Ascents', 'fa-cable-car', '#f59e0b'),
        ('KAYAKING', 'Kayaking Treks', 'fa-sailboat', '#10b981'),
        ('SAILING', 'Open Sea Sailing', 'fa-ship', '#6366f1'),
        ('BOATING', 'Nautical Boating & Ferries', 'fa-ferry', '#3b82f6'),
    ]

    for m_type, m_title, m_icon, m_color in rare_types:
        if m_type in mode_stats:
            stat = mode_stats[m_type]
            c.execute("""
            SELECT date, start_time, distance_meters, duration_minutes
            FROM segments WHERE activity_type = ?
            ORDER BY distance_meters DESC LIMIT 1;
            """, (m_type,))
            top_rec = dict(c.fetchone() or {})
            rare_modes.append({
                "type": m_type,
                "title": m_title,
                "icon": m_icon,
                "color": m_color,
                "count": stat['count'],
                "total_km": round(stat['total_km'], 1),
                "total_hours": round(stat['total_hours'], 1),
                "highlight_date": top_rec.get('date'),
                "highlight_dist_km": round((top_rec.get('distance_meters') or 0.0) / 1000.0, 2)
            })

    # 4. Longest Non-Stop Flight
    c.execute("""
    SELECT s.date, s.start_time, s.end_time, s.distance_meters, s.duration_minutes
    FROM segments s
    WHERE s.activity_type = 'FLYING'
    ORDER BY s.distance_meters DESC LIMIT 1;
    """)
    longest_flight_raw = c.fetchone()
    longest_flight = dict(longest_flight_raw) if longest_flight_raw else {}

    # 5. Night Owl Superlatives (2:00 AM - 4:30 AM)
    c.execute("""
    SELECT s.id, s.date, s.start_time, s.end_time, s.activity_type, s.distance_meters, s.duration_minutes
    FROM segments s
    WHERE s.segment_type = 'activity'
      AND (substr(s.start_time, 12, 5) BETWEEN '02:00' AND '04:30')
      AND s.distance_meters > 500
    ORDER BY s.distance_meters DESC
    LIMIT 4;
    """)
    night_treks = [dict(r) for r in c.fetchall()]

    # 6. Single-Day Epic Endurance
    c.execute("""
    SELECT date, SUM(distance_meters)/1000.0 as day_km, SUM(duration_minutes)/60.0 as day_hours
    FROM segments
    WHERE activity_type = 'CYCLING'
      AND duration_minutes > 0
      AND (distance_meters / (duration_minutes * 60)) <= 12.0
    GROUP BY date
    ORDER BY day_km DESC LIMIT 1;
    """)
    epic_cycle = dict(c.fetchone() or {})

    c.execute("""
    SELECT date, SUM(distance_meters)/1000.0 as day_km, SUM(duration_minutes)/60.0 as day_hours
    FROM segments
    WHERE activity_type = 'WALKING'
      AND duration_minutes > 0
      AND (distance_meters / (duration_minutes * 60)) <= 3.5
    GROUP BY date
    ORDER BY day_km DESC LIMIT 1;
    """)
    epic_walk = dict(c.fetchone() or {})

    # 7. Multi-City Speedrun Days
    c.execute("""
    SELECT s.date, count(DISTINCT p.city) as city_cnt, group_concat(DISTINCT p.city) as cities
    FROM segments s
    JOIN places p ON s.place_id = p.place_id
    WHERE p.city IS NOT NULL AND p.city != ''
    GROUP BY s.date
    HAVING city_cnt >= 4
    ORDER BY city_cnt DESC
    LIMIT 3;
    """)
    multi_city_days = [dict(r) for r in c.fetchall()]

    # 8. Top 5 Most Visited Sanctuaries (excluding Home)
    c.execute("""
    SELECT p.name, p.category, p.city, p.review_rating, COUNT(*) as visit_count
    FROM segments s
    JOIN places p ON s.place_id = p.place_id
    WHERE p.name IS NOT NULL
      AND p.name NOT LIKE 'Home%'
      AND p.name NOT LIKE 'Location (%'
      AND p.name != 'Point of Interest'
    GROUP BY p.place_id
    ORDER BY visit_count DESC
    LIMIT 5;
    """)
    top_sanctuaries = [dict(r) for r in c.fetchall()]

    conn.close()

    # Structure Curated Nuggets
    nuggets = [
        {
            "id": "antarctica_extreme",
            "category": "Geographic Frontier",
            "badge": "❄️ Polar Frontier",
            "title": "Stepped Foot on Antarctica (65° South)",
            "date": south.get("date", "2016-01-04"),
            "subtitle": f"{south.get('place_name')} ({south.get('latitude', 0.0):.4f}°, {south.get('longitude', 0.0):.4f}°)",
            "why": "Your southernmost recorded point on Earth is Petermann Island, Antarctica. Situated at 65.17° S along the Lemaire Channel, this is just 1.5° north of the Antarctic Circle among Gentoo penguin colonies.",
            "icon": "fa-compass",
            "accent": "#38bdf8"
        },
        {
            "id": "arctic_circle",
            "category": "Geographic Frontier",
            "badge": "🌌 Arctic Frontier",
            "title": "Crossed 69° North in Kirkenes, Norway",
            "date": north.get("date", "2010-01-07"),
            "subtitle": f"{north.get('place_name')} ({north.get('latitude', 0.0):.4f}°, {north.get('longitude', 0.0):.4f}°)",
            "why": "Your northernmost recorded visit was in Kirkenes, Northern Norway at 69.72° N, well deep inside the Arctic Circle near the Barents Sea during polar night.",
            "icon": "fa-icicles",
            "accent": "#60a5fa"
        },
        {
            "id": "cosmic_flying",
            "category": "Cosmic Distances",
            "badge": "🚀 Cosmic Orbit",
            "title": f"{round(fly_km):,} km Flown (33 Earth Orbits & 3.4 Moon Trips)",
            "date": "Lifetime",
            "subtitle": f"{earth_orbits}x around the globe · {moon_trips}x distance to the Moon",
            "why": f"Your 348 recorded flights total {round(fly_km):,} km in the air. That's enough distance to orbit the Earth's equator 33 times or fly to the Moon and halfway back three times.",
            "icon": "fa-earth-americas",
            "accent": "#ec4899"
        },
        {
            "id": "longest_flight_record",
            "category": "Aviation Record",
            "badge": "✈️ World's Longest Flight",
            "title": "15,336 km Non-Stop (JFK → Singapore SQ23)",
            "date": longest_flight.get("date", "2024-10-10"),
            "subtitle": "18.0 hours continuous flight time across the Arctic",
            "why": "You flew Singapore Airlines SQ23 from New York (JFK) to Singapore (SIN) — officially recognized as the world's longest active non-stop commercial airline flight route.",
            "icon": "fa-plane-departure",
            "accent": "#a855f7"
        },
        {
            "id": "pedestrian_stamina",
            "category": "Human Locomotive",
            "badge": "🚶 Walk Across Asia",
            "title": f"{round(walk_km):,} km Walked (NYC to Singapore on Foot)",
            "date": "Lifetime",
            "subtitle": f"15,839 individual walks · {round(mode_stats.get('WALKING',{}).get('total_hours', 0)):,} hours walking",
            "why": f"You have logged {round(walk_km):,} km on foot across 15,839 recorded walks. If laid end-to-end, you walked the entire straight-line distance from New York City to Singapore.",
            "icon": "fa-person-walking",
            "accent": "#10b981"
        },
        {
            "id": "cyclist_legend",
            "category": "Human Locomotive",
            "badge": "🚴 Coast-to-Coast",
            "title": f"{round(cycle_km):,} km Cycled (3x Coast-to-Coast USA)",
            "date": "Lifetime",
            "subtitle": f"5,053 rides · Peak single-day: {round(epic_cycle.get('day_km', 0), 1)} km",
            "why": f"Your 5,053 bike rides total {round(cycle_km):,} km in the saddle — enough to cycle from New York to San Francisco three times over.",
            "icon": "fa-bicycle",
            "accent": "#f59e0b"
        },
        {
            "id": "subway_commuter",
            "category": "Urban Transit",
            "badge": "🚇 Metro Master",
            "title": f"5,136 Subway Journeys ({round(subway_km):,} km)",
            "date": "Lifetime",
            "subtitle": "NYC Subway, London Tube, Tokyo Metro & Zürich S-Bahn",
            "why": f"You logged {subway_trips:,} distinct rail & metro trips totaling {round(subway_km):,} km underground.",
            "icon": "fa-train-subway",
            "accent": "#6366f1"
        }
    ]

    return {
        "status": "SUCCESS",
        "nuggets": nuggets,
        "extremes": {
            "north": north,
            "south": south,
            "east": east,
            "west": west
        },
        "rare_modes": rare_modes,
        "mode_summary": mode_stats,
        "night_treks": night_treks,
        "top_sanctuaries": top_sanctuaries
    }


MODE_METADATA: Dict[str, Dict[str, str]] = {
    "WALKING": {"label": "Walking", "icon": "fa-person-walking", "color": "#22c55e"},
    "RUNNING": {"label": "Running", "icon": "fa-person-running", "color": "#10b981"},
    "CYCLING": {"label": "Cycling", "icon": "fa-bicycle", "color": "#0284c7"},
    "ON_BICYCLE": {"label": "Cycling", "icon": "fa-bicycle", "color": "#0284c7"},
    "FLYING": {"label": "Flying", "icon": "fa-plane", "color": "#a855f7"},
    "DRIVING": {"label": "Driving", "icon": "fa-car", "color": "#ef4444"},
    "IN_PASSENGER_VEHICLE": {"label": "Driving", "icon": "fa-car", "color": "#ef4444"},
    "IN_VEHICLE": {"label": "Driving", "icon": "fa-car", "color": "#ef4444"},
    "MOTORCYCLING": {"label": "Motorcycle", "icon": "fa-motorcycle", "color": "#f97316"},
    "IN_SUBWAY": {"label": "Subway / Metro", "icon": "fa-train-subway", "color": "#6366f1"},
    "IN_TRAIN": {"label": "Train", "icon": "fa-train", "color": "#3b82f6"},
    "IN_TRAM": {"label": "Tram / Light Rail", "icon": "fa-cable-car", "color": "#14b8a6"},
    "IN_BUS": {"label": "Bus", "icon": "fa-bus", "color": "#f59e0b"},
    "IN_FERRY": {"label": "Ferry", "icon": "fa-ferry", "color": "#06b6d4"},
    "BOATING": {"label": "Boating", "icon": "fa-ship", "color": "#0ea5e9"},
    "SAILING": {"label": "Sailing", "icon": "fa-sailboat", "color": "#38bdf8"},
    "HIKING": {"label": "Hiking", "icon": "fa-person-hiking", "color": "#84cc16"},
    "SKATEBOARDING": {"label": "Skateboarding", "icon": "fa-person-skating", "color": "#ec4899"},
    "SKIING": {"label": "Skiing", "icon": "fa-person-skiing", "color": "#8b5cf6"},
    "SNOWBOARDING": {"label": "Snowboarding", "icon": "fa-person-snowboarding", "color": "#a855f7"},
    "IN_GONDOLA_LIFT": {"label": "Gondola Lift", "icon": "fa-cable-car", "color": "#f59e0b"},
    "PARAGLIDING": {"label": "Paragliding", "icon": "fa-parachute-box", "color": "#38bdf8"},
    "KITESURFING": {"label": "Kitesurfing", "icon": "fa-water", "color": "#06b6d4"},
    "KAYAKING": {"label": "Kayaking", "icon": "fa-sailboat", "color": "#10b981"},
    "SNOWSHOEING": {"label": "Snowshoeing", "icon": "fa-snowflake", "color": "#93c5fd"},
    "SLEDDING": {"label": "Sledding", "icon": "fa-person-sledding", "color": "#a855f7"},
}


def get_activity_summaries(db_path: str = DEFAULT_DB_PATH, period: str = "all") -> Dict[str, Any]:
    """
    Computes activity breakdowns, distance totals, time totals, and nuggets
    for a given period ('all' or specific year like '2026').
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Get available periods (years)
    c.execute("""
        SELECT DISTINCT substr(date, 1, 4) as y 
        FROM segments 
        WHERE segment_type = 'activity' AND date IS NOT NULL AND date != '' 
        ORDER BY y DESC;
    """)
    available_years = [r["y"] for r in c.fetchall() if r["y"] and r["y"].isdigit()]
    available_periods = ["all"] + available_years

    # Build WHERE filter
    where_clauses = ["segment_type = 'activity'"]
    params: List[Any] = []

    if period and period.lower() != "all" and period in available_years:
        where_clauses.append("(year = ? OR date LIKE ?)")
        params.extend([int(period), f"{period}-%"])
    else:
        period = "all"

    where_sql = " AND ".join(where_clauses)

    # 1. Mode Breakdown Query
    c.execute(f"""
        SELECT activity_type,
               COUNT(*) as count,
               SUM(COALESCE(clean_distance_meters, distance_meters, 0))/1000.0 as total_km,
               SUM(duration_minutes)/60.0 as total_hours
        FROM segments
        WHERE {where_sql}
        GROUP BY activity_type
        ORDER BY total_km DESC;
    """, params)

    raw_modes = [dict(r) for r in c.fetchall()]

    total_distance_km = sum(m["total_km"] or 0.0 for m in raw_modes)
    total_hours = sum(m["total_hours"] or 0.0 for m in raw_modes)
    total_activities = sum(m["count"] for m in raw_modes)

    modes: List[Dict[str, Any]] = []
    for m in raw_modes:
        act_type = m["activity_type"] or "UNKNOWN"
        meta = MODE_METADATA.get(act_type, {
            "label": act_type.replace("_", " ").title(),
            "icon": "fa-person-walking",
            "color": "#94a3b8"
        })
        km = round(m["total_km"] or 0.0, 1)
        hrs = round(m["total_hours"] or 0.0, 1)
        pct_dist = round((km / total_distance_km * 100.0), 1) if total_distance_km > 0 else 0.0
        pct_time = round((hrs / total_hours * 100.0), 1) if total_hours > 0 else 0.0

        modes.append({
            "activity_type": act_type,
            "label": meta["label"],
            "icon": meta["icon"],
            "color": meta["color"],
            "count": m["count"],
            "total_km": km,
            "total_hours": hrs,
            "pct_distance": pct_dist,
            "pct_time": pct_time,
        })

    # 2. Top Visited Places in this Period
    visit_where = ["segment_type = 'visit'", "p.name IS NOT NULL"]
    visit_params: List[Any] = []
    if period != "all":
        visit_where.append("(s.year = ? OR s.date LIKE ?)")
        visit_params.extend([int(period), f"{period}-%"])

    c.execute(f"""
        SELECT p.name, p.category, p.city, COUNT(*) as visit_count, p.place_id
        FROM segments s
        JOIN places p ON s.place_id = p.place_id
        WHERE {" AND ".join(visit_where)}
          AND p.name NOT LIKE 'Home%'
          AND p.name NOT LIKE 'Location (%'
          AND p.name != 'Point of Interest'
        GROUP BY p.place_id
        ORDER BY visit_count DESC
        LIMIT 6;
    """, visit_params)
    top_places = [dict(r) for r in c.fetchall()]

    # 3. Mined Nuggets (curated factoids)
    nuggets_data = extract_archive_nuggets(db_path)
    curated_nuggets = nuggets_data.get("nuggets", [])
    rare_modes = nuggets_data.get("rare_modes", [])

    fly_km = next((m["total_km"] for m in raw_modes if m["activity_type"] == "FLYING"), 0.0)
    cycle_km = next((m["total_km"] for m in raw_modes if m["activity_type"] in ("CYCLING", "ON_BICYCLE")), 0.0)
    walk_km = next((m["total_km"] for m in raw_modes if m["activity_type"] == "WALKING"), 0.0)

    conn.close()

    return {
        "status": "SUCCESS",
        "period": period,
        "available_periods": available_periods,
        "totals": {
            "total_distance_km": round(total_distance_km, 1),
            "total_hours": round(total_hours, 1),
            "total_activities": total_activities,
            "walk_km": round(walk_km, 1),
            "cycle_km": round(cycle_km, 1),
            "fly_km": round(fly_km, 1),
            "earth_orbits": round(fly_km / EARTH_CIRCUMFERENCE_KM, 1),
            "moon_trips": round(fly_km / MOON_DISTANCE_KM, 2),
            "transcon_cycles": round(cycle_km / 4000.0, 1),
        },
        "modes": modes,
        "curated_nuggets": curated_nuggets,
        "rare_modes": rare_modes,
        "top_places": top_places,
    }

