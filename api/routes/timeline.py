"""
Daily Timeline, Calendar, and Gap Stitching Routes.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from api.db import DEFAULT_DB_PATH, query_all, query_one
from api.response import Response, error_response, json_response
from api.router import Request, router
from breadcrumbs import haversine_distance
from enrichment.local_timezone import format_local_time_strings
from life_periods import get_date_aware_label


@router.get("/api/calendar")
def get_calendar(req: Request) -> Response:
    """Returns aggregated day counts for calendar navigation."""
    year = req.get_int("year", 0)
    month = req.get_int("month", 0)

    sql = """
    SELECT date, year, month, day,
           COUNT(*) as total_segments,
           SUM(CASE WHEN segment_type = 'visit' THEN 1 ELSE 0 END) as visits,
           SUM(CASE WHEN segment_type = 'activity' THEN 1 ELSE 0 END) as activities,
           SUM(CASE WHEN hierarchy_level = 1 THEN 1 ELSE 0 END) as child_visits,
           SUM(CASE WHEN is_unconfirmed = 1 THEN 1 ELSE 0 END) as unconfirmed,
           SUM(CASE WHEN has_snapped_path = 1 THEN 1 ELSE 0 END) as snapped_paths
    FROM segments
    """
    params: List[Any] = []
    where: List[str] = []
    if year > 0:
        where.append("year = ?")
        params.append(year)
    if month > 0:
        where.append("month = ?")
        params.append(month)

    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " GROUP BY date ORDER BY date ASC;"

    days = query_all(sql, params)

    # Attach gap counts
    gap_rows = query_all("SELECT date, COUNT(*) as gap_count FROM gaps GROUP BY date;")
    gap_map = {r["date"]: r["gap_count"] for r in gap_rows}

    for d in days:
        d["gaps"] = gap_map.get(d["date"], 0)

    return json_response({"status": "SUCCESS", "days": days})


@router.get("/api/day")
def get_day(req: Request) -> Response:
    """Returns detailed daily itinerary including segments, gaps, raw signals, and anomalies."""
    date_str = req.get_str("date")
    if not date_str or not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return error_response("Missing or invalid 'date' parameter (expected YYYY-MM-DD)", status_code=400)

    # 1. Fetch segments for date (including multi-day visits spanning across midnight)
    segments = query_all("""
        SELECT s.*, p.name as catalog_place_name, p.address as catalog_place_address,
               p.semantic_type as catalog_semantic_type, p.category as catalog_category,
               p.city as catalog_city, p.country as catalog_country,
               p.user_confirmed as catalog_confirmed,
               p.review_rating as catalog_review_rating, p.review_text as catalog_review_text,
               p.review_photos as catalog_review_photos, p.review_photo_count as catalog_review_photo_count,
               p.has_review as catalog_has_review
        FROM segments s
        LEFT JOIN places p ON s.place_id = p.place_id
        WHERE s.date = ? OR (s.segment_type = 'visit' AND substr(s.start_time, 1, 10) < ? AND substr(s.end_time, 1, 10) >= ?)
        ORDER BY s.start_ts ASC, s.end_ts ASC;
    """, (date_str, date_str, date_str))

    for s in segments:
        if s.get("start_time") and str(s["start_time"])[:10] < date_str:
            s["started_previous_day"] = 1

        if s["segment_type"] == "visit":
            cur_name = s.get("catalog_place_name") or s.get("place_name")
            cur_cat = s.get("catalog_category") or s.get("category")
            cur_addr = s.get("catalog_place_address") or s.get("place_address")

            s["place_name"] = cur_name
            s["category"] = cur_cat
            s["place_address"] = cur_addr

            label, cat = get_date_aware_label(DEFAULT_DB_PATH, cur_name, s.get("latitude"), s.get("longitude"), date_str)
            if label:
                s["place_name"] = label
                s["catalog_place_name"] = label
                s["category"] = cat
                s["catalog_category"] = cat
            elif not cur_name or cur_name.strip() in ["Place", "Home/Place", "Unconfirmed Location"]:
                fallback_name = cur_addr or (
                    f"Location ({s['latitude']:.4f}, {s['longitude']:.4f})" if s.get("latitude") else "Point of Interest"
                )
                s["place_name"] = fallback_name
                s["catalog_place_name"] = fallback_name

            s["review_rating"] = s.get("catalog_review_rating") or s.get("review_rating")
            s["review_text"] = s.get("catalog_review_text") or s.get("review_text")

            # Parse review photos
            raw_photos = s.get("catalog_review_photos") or s.get("review_photos")
            if isinstance(raw_photos, str) and raw_photos.strip():
                try:
                    s["review_photos"] = json.loads(raw_photos)
                except Exception:
                    s["review_photos"] = []
            elif isinstance(raw_photos, list):
                s["review_photos"] = raw_photos
            else:
                s["review_photos"] = []

            # Parse with_people
            raw_people = s.get("with_people")
            if isinstance(raw_people, str) and raw_people.strip():
                try:
                    s["with_people"] = json.loads(raw_people)
                except Exception:
                    s["with_people"] = []
            elif isinstance(raw_people, list):
                s["with_people"] = raw_people
            else:
                s["with_people"] = []

        elif s["segment_type"] == "activity":
            coords = []
            if s.get("path_points_json"):
                try:
                    coords = json.loads(s["path_points_json"])
                except Exception:
                    coords = []

            if not coords and s.get("latitude") is not None and s.get("end_lat") is not None:
                coords = [[s["latitude"], s["longitude"]], [s["end_lat"], s["end_lng"]]]

            if coords and len(coords) >= 2:
                s["path_points"] = coords
                s["has_snapped_path"] = 1 if len(coords) >= 3 else 0
            else:
                s["path_points"] = None

        # Compute accurate local time
        t1, t2, tz_str = format_local_time_strings(
            s.get("latitude"), s.get("longitude"),
            s.get("start_ts"), s.get("end_ts"),
            s.get("start_time") or "", s.get("end_time") or "",
            s.get("end_lat"), s.get("end_lng")
        )
        s["local_start_time"] = t1
        s["local_end_time"] = t2
        s["local_timezone"] = tz_str

    # 2. Fetch recorded gaps
    gaps = query_all("""
        SELECT g.*,
               s1.place_name as prev_name, s1.activity_type as prev_activity,
               s2.place_name as next_name, s2.activity_type as next_activity
        FROM gaps g
        LEFT JOIN segments s1 ON g.prev_segment_id = s1.id
        LEFT JOIN segments s2 ON g.next_segment_id = s2.id
        WHERE g.date = ? AND (g.status IS NULL OR g.status != 'RESOLVED')
        ORDER BY g.start_ts ASC;
    """, (date_str,))

    # 3. Dynamic gap detection (>= 3 min between consecutive segments)
    sorted_segs = sorted(
        [s for s in segments if s.get("start_ts") and s.get("end_ts")],
        key=lambda x: x["start_ts"]
    )
    if sorted_segs:
        max_end = sorted_segs[0]["end_ts"]
        anchor = sorted_segs[0]
        for i in range(len(sorted_segs) - 1):
            curr = sorted_segs[i]
            nxt = sorted_segs[i + 1]

            if curr["end_ts"] > max_end:
                max_end = curr["end_ts"]
                anchor = curr

            diff_s = nxt["start_ts"] - max_end
            if diff_s >= 180:  # 3 min threshold
                is_covered = any(abs(g.get("start_ts", 0) - max_end) < 120 for g in gaps)
                if not is_covered:
                    # Clean coordinates: derive strictly from anchor/next segments (NO NYC fallback)
                    p_lat = anchor.get("end_lat") if anchor.get("end_lat") is not None else anchor.get("latitude")
                    p_lng = anchor.get("end_lng") if anchor.get("end_lng") is not None else anchor.get("longitude")
                    n_lat = nxt.get("latitude")
                    n_lng = nxt.get("longitude")

                    dist_km = 0.0
                    if p_lat is not None and p_lng is not None and n_lat is not None and n_lng is not None:
                        dist_km = haversine_distance(p_lat, p_lng, n_lat, n_lng) / 1000.0

                    dur_h = diff_s / 3600.0
                    ref_lat = p_lat if p_lat is not None else n_lat
                    ref_lng = p_lng if p_lng is not None else n_lng

                    gt1, gt2, gtz = format_local_time_strings(
                        ref_lat, ref_lng, max_end, nxt["start_ts"],
                        anchor.get("end_time") or "", nxt.get("start_time") or ""
                    )
                    gaps.append({
                        "id": f"dyn_{anchor.get('id')}_{nxt.get('id')}",
                        "date": date_str,
                        "start_ts": max_end,
                        "end_ts": nxt["start_ts"],
                        "start_time": anchor.get("end_time"),
                        "end_time": nxt.get("start_time"),
                        "duration_hours": dur_h,
                        "duration_minutes": dur_h * 60.0,
                        "distance_km": dist_km,
                        "jump_distance_km": dist_km,
                        "prev_lat": p_lat,
                        "prev_lng": p_lng,
                        "next_lat": n_lat,
                        "next_lng": n_lng,
                        "prev_name": anchor.get("place_name") or anchor.get("activity_type"),
                        "prev_activity": anchor.get("activity_type"),
                        "next_name": nxt.get("place_name") or nxt.get("activity_type"),
                        "next_activity": nxt.get("activity_type"),
                        "local_start_time": gt1,
                        "local_end_time": gt2,
                        "local_timezone": gtz,
                        "status": "PENDING"
                    })
                    max_end = max(max_end, nxt["end_ts"])
                    anchor = nxt

    # Format local times on all gaps
    for g in gaps:
        if not g.get("local_start_time"):
            lat = g.get("prev_lat") if g.get("prev_lat") is not None else g.get("next_lat")
            lng = g.get("prev_lng") if g.get("prev_lng") is not None else g.get("next_lng")
            gt1, gt2, gtz = format_local_time_strings(
                lat, lng, g.get("start_ts"), g.get("end_ts"),
                g.get("start_time") or "", g.get("end_time") or ""
            )
            g["local_start_time"] = gt1
            g["local_end_time"] = gt2
            g["local_timezone"] = gtz

    # 4. Raw Signals buffer
    raw_signals = query_all("""
        SELECT timestamp, ts, latitude, longitude, accuracy_meters, altitude_meters, speed_mps, source
        FROM raw_signals
        WHERE date = ?
        ORDER BY ts ASC;
    """, (date_str,))

    # 5. Anomalies & Fix Proposals
    anomalies = query_all("SELECT * FROM anomalies WHERE date = ?;", (date_str,))
    fixes = query_all("SELECT * FROM fix_proposals WHERE date = ?;", (date_str,))
    memories = query_all("SELECT * FROM memories WHERE date = ? ORDER BY start_ts ASC;", (date_str,))

    # 6. Fetch photos for date from photo index (gregor_cos)
    day_photos = query_all("""
        SELECT sha256, filename, preview_path, timestamp_utc, timezone_offset,
               local_date, latitude, longitude, place_id, place_name, address, city, country, people, face_count
        FROM photos
        WHERE local_date = ?
        ORDER BY timestamp_utc ASC;
    """, (date_str,))

    if segments:
        valid_starts = [s["start_ts"] for s in segments if s.get("start_ts")]
        valid_ends = [s["end_ts"] for s in segments if s.get("end_ts")]
        if valid_starts and valid_ends:
            min_ts = min(valid_starts)
            max_ts = max(valid_ends)
            extra_photos = query_all("""
                SELECT sha256, filename, preview_path, timestamp_utc, timezone_offset,
                       local_date, latitude, longitude, place_id, place_name, address, city, country, people, face_count
                FROM photos
                WHERE timestamp_utc >= ? AND timestamp_utc <= ? AND (local_date != ? OR local_date IS NULL)
                ORDER BY timestamp_utc ASC;
            """, (min_ts, max_ts, date_str))
            seen_shas = {p["sha256"] for p in day_photos}
            for ep in extra_photos:
                if ep["sha256"] not in seen_shas:
                    day_photos.append(ep)
                    seen_shas.add(ep["sha256"])

    for p in day_photos:
        p["preview_url"] = f"/api/photo?sha256={p['sha256']}"
        raw_p = p.get("people")
        if isinstance(raw_p, str) and raw_p.strip():
            try:
                p["people"] = json.loads(raw_p)
            except Exception:
                p["people"] = [raw_p]
        elif not isinstance(raw_p, list):
            p["people"] = []

    # Attach matching photos to visit & activity segments
    for s in segments:
        s_photos = []
        if s["segment_type"] == "visit":
            for p in day_photos:
                p_ts = p.get("timestamp_utc")
                p_pid = p.get("place_id")
                match = False
                if s.get("place_id") and p_pid and s["place_id"] == p_pid:
                    if s.get("start_ts") and s.get("end_ts") and p_ts:
                        if s["start_ts"] - 3600 <= p_ts <= s["end_ts"] + 3600:
                            match = True
                    else:
                        match = True
                elif s.get("start_ts") and s.get("end_ts") and p_ts:
                    if s["start_ts"] - 120 <= p_ts <= s["end_ts"] + 120:
                        if s.get("latitude") is not None and p.get("latitude") is not None:
                            dist_m = haversine_distance(s["latitude"], s["longitude"], p["latitude"], p["longitude"])
                            if dist_m <= 250:
                                match = True
                        else:
                            match = True
                if match:
                    s_photos.append(p)

            s["photos"] = s_photos
            s["photo_count"] = len(s_photos)
            if s_photos:
                existing_urls = list(s.get("review_photos") or [])
                for sp in s_photos:
                    url = f"/api/photo?sha256={sp['sha256']}"
                    if url not in existing_urls:
                        existing_urls.append(url)
                s["review_photos"] = existing_urls

        elif s["segment_type"] == "activity":
            if s.get("start_ts") and s.get("end_ts"):
                for p in day_photos:
                    p_ts = p.get("timestamp_utc")
                    if p_ts and s["start_ts"] <= p_ts <= s["end_ts"]:
                        s_photos.append(p)
            s["photos"] = s_photos
            s["photo_count"] = len(s_photos)
            if s_photos:
                s["review_photos"] = [f"/api/photo?sha256={sp['sha256']}" for sp in s_photos]

    return json_response({
        "status": "SUCCESS",
        "date": date_str,
        "segments": segments,
        "gaps": gaps,
        "raw_signals": raw_signals,
        "anomalies": anomalies,
        "fix_proposals": fixes,
        "memories": memories,
        "photos": day_photos,
        "photo_count": len(day_photos),
    })


@router.get("/api/calendar-range")
def get_calendar_range(req: Request) -> Response:
    """Returns calendar days matrix across a custom date range with gaps and anomalies."""
    import datetime

    start_date = req.get_str("start_date")
    end_date = req.get_str("end_date")
    if not start_date or not end_date:
        max_row = query_one("SELECT MAX(date) as max_date FROM segments WHERE date IS NOT NULL;")
        max_d = max_row["max_date"] if max_row else "2026-08-20"
        end_dt = datetime.date.fromisoformat(max_d)
        start_dt = end_dt - datetime.timedelta(days=6)
        start_date = start_dt.isoformat()
        end_date = end_dt.isoformat()

    start_ts_min = int(datetime.datetime.combine(datetime.date.fromisoformat(start_date), datetime.time.min).timestamp())
    end_ts_max = int(datetime.datetime.combine(datetime.date.fromisoformat(end_date), datetime.time.max).timestamp())

    all_segs = query_all("""
        SELECT id, segment_type, activity_type, place_name, place_id, place_address, category,
               start_time, end_time, start_ts, end_ts, duration_minutes,
               latitude, longitude, end_lat, end_lng, distance_meters, date, source
        FROM segments
        WHERE (date >= ? AND date <= ?) OR (start_ts <= ? AND end_ts >= ?)
        ORDER BY start_ts ASC;
    """, (start_date, end_date, end_ts_max, start_ts_min))

    days_data: Dict[str, Any] = {}
    cur = datetime.date.fromisoformat(start_date)
    end_d = datetime.date.fromisoformat(end_date)

    while cur <= end_d:
        d_str = cur.isoformat()
        day_start_ts = int(datetime.datetime.combine(cur, datetime.time.min).timestamp())
        day_end_ts = int(datetime.datetime.combine(cur, datetime.time.max).timestamp())

        raw_day_segs = [s for s in all_segs if (s.get("start_ts") or 0) <= day_end_ts and (s.get("end_ts") or 0) >= day_start_ts]
        day_segs = []
        for s in raw_day_segs:
            s_copy = dict(s)
            clamp_s_ts = max(day_start_ts, s["start_ts"])
            clamp_e_ts = min(day_end_ts, s["end_ts"])
            s_copy["start_ts"] = clamp_s_ts
            s_copy["end_ts"] = clamp_e_ts
            s_copy["duration_minutes"] = max(1.0, round((clamp_e_ts - clamp_s_ts) / 60.0, 1))

            dt1 = datetime.datetime.fromtimestamp(clamp_s_ts)
            dt2 = datetime.datetime.fromtimestamp(clamp_e_ts)
            s_copy["start_time"] = f"{d_str}T{dt1.strftime('%H:%M:%S')}"
            s_copy["end_time"] = f"{d_str}T{dt2.strftime('%H:%M:%S')}"
            day_segs.append(s_copy)

        gaps = []
        anomalies = []
        for i in range(len(day_segs)):
            s = day_segs[i]
            if i < len(day_segs) - 1:
                nxt = day_segs[i + 1]
                diff_s = (nxt.get("start_ts") or 0) - (s.get("end_ts") or 0)
                if diff_s > 180:
                    gap_dur_min = round(diff_s / 60.0, 1)
                    gaps.append({
                        "start_ts": s.get("end_ts"),
                        "end_ts": nxt.get("start_ts"),
                        "start_time": s.get("end_time"),
                        "end_time": nxt.get("start_time"),
                        "duration_minutes": gap_dur_min,
                        "severity": "MAJOR" if gap_dur_min > 60 else "MEDIUM" if gap_dur_min > 15 else "MINOR"
                    })

        days_data[d_str] = {
            "date": d_str,
            "weekday": cur.strftime("%A"),
            "segments": day_segs,
            "gaps": gaps,
            "anomalies": anomalies,
            "total_duration_minutes": sum(s.get("duration_minutes") or 0 for s in day_segs),
            "total_gap_minutes": sum(g.get("duration_minutes") or 0 for g in gaps),
        }
        cur += datetime.timedelta(days=1)

    return json_response({
        "status": "SUCCESS",
        "start_date": start_date,
        "end_date": end_date,
        "days": days_data
    })
