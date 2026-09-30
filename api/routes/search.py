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
            day_photo = query_one("""
                SELECT sha256 FROM photos
                WHERE local_date = ? AND timestamp_utc IS NOT NULL
                ORDER BY (CASE WHEN face_count > 0 THEN 0 ELSE 1 END),
                         (CASE WHEN filename LIKE 'Screen%' OR filename LIKE 'Screenshot%' THEN 1 ELSE 0 END),
                         timestamp_utc DESC
                LIMIT 1;
            """, (dt,))
            d_sha = day_photo["sha256"] if day_photo else None
            results.append({
                "type": "DATE",
                "title": f"Day Timeline: {dt}",
                "subtitle": f"{r['cnt']} segments · {round((r.get('dist') or 0)/1000.0, 1)} km · {pnames[0] if pnames else 'Trip activity'}",
                "date": dt,
                "places": pnames,
                "preview_url": f"/api/photo?sha256={d_sha}" if d_sha else None,
                "sha256": d_sha,
                "icon": "fa-calendar-day"
            })

    # 2. Person & Contact Search (Authentic People Tagging)
    person_results: List[Dict[str, Any]] = []
    person_visit_results: List[Dict[str, Any]] = []
    is_person_query = False

    if not m_iso and not m_us:
        # Match candidate people by word boundaries in photos (starts with q, preceded by space, or preceded by comma)
        photo_people_rows = query_all("""
            SELECT people, count(*) as cnt
            FROM photos
            WHERE people LIKE ? OR people LIKE ? OR people LIKE ?
            GROUP BY people
            ORDER BY cnt DESC;
        """, (f"{q}%", f"% {q}%", f"%, {q}%"))

        candidate_counts: Dict[str, int] = {}
        for pr in photo_people_rows:
            raw_people = pr.get("people") or ""
            for nm in raw_people.split(","):
                nm = nm.strip()
                words = nm.split()
                if any(w.lower().startswith(q.lower()) for w in words):
                    candidate_counts[nm] = candidate_counts.get(nm, 0) + pr["cnt"]

        # Check contacts for exact name matches
        contact_rows = query_all("""
            SELECT name, email, phone, organization, full_address
            FROM contacts
            WHERE name LIKE ? OR name LIKE ?;
        """, (f"{q}%", f"% {q}%"))

        contact_map = {c["name"]: c for c in contact_rows}
        for cname in contact_map:
            if cname not in candidate_counts:
                candidate_counts[cname] = 0

        # Sort candidate people by photo count DESC, then name
        sorted_candidates = sorted(candidate_counts.items(), key=lambda x: (x[1], x[0]), reverse=True)

        if sorted_candidates:
            is_person_query = True
            for name, p_count in sorted_candidates[:3]:
                # Pick the best profile photo with detected faces, excluding screenshots
                best_photo_row = query_one("""
                    SELECT sha256, filename, face_count
                    FROM photos
                    WHERE (people LIKE ? OR people LIKE ? OR people LIKE ?) AND timestamp_utc IS NOT NULL
                    ORDER BY (CASE WHEN face_count > 0 THEN 0 ELSE 1 END),
                             (CASE WHEN filename LIKE 'Screen%' OR filename LIKE 'Screenshot%' THEN 1 ELSE 0 END),
                             timestamp_utc DESC
                    LIMIT 1;
                """, (f"{name}%", f"% {name}%", f"%, {name}%"))
                top_sha = best_photo_row["sha256"] if best_photo_row else None

                # Query visits with photos of this person, selecting best photo with face per visit
                all_p_visits = query_all("""
                    SELECT s.id, s.date, s.start_time, s.end_time, s.duration_minutes,
                           s.place_name, s.place_address, s.place_id, s.category, s.city, s.latitude, s.longitude,
                           count(p.sha256) as person_photo_cnt,
                           (
                               SELECT p2.sha256
                               FROM photos p2
                               WHERE p2.timestamp_utc >= s.start_ts AND p2.timestamp_utc <= s.end_ts
                                 AND (p2.people LIKE ? OR p2.people LIKE ? OR p2.people LIKE ?)
                               ORDER BY (CASE WHEN p2.face_count > 0 THEN 0 ELSE 1 END),
                                        (CASE WHEN p2.filename LIKE 'Screen%' OR p2.filename LIKE 'Screenshot%' THEN 1 ELSE 0 END),
                                        p2.timestamp_utc DESC
                               LIMIT 1
                           ) as photo_sha
                    FROM (
                        SELECT sha256, timestamp_utc
                        FROM photos
                        WHERE (people LIKE ? OR people LIKE ? OR people LIKE ?) AND timestamp_utc IS NOT NULL
                    ) p
                    JOIN segments s ON p.timestamp_utc >= s.start_ts AND p.timestamp_utc <= s.end_ts
                    WHERE s.segment_type = 'visit'
                    GROUP BY s.id
                    ORDER BY s.date DESC;
                """, (f"{name}%", f"% {name}%", f"%, {name}%", f"{name}%", f"% {name}%", f"%, {name}%"))

                total_v = len(all_p_visits)
                contact_info = contact_map.get(name)
                sub_parts = []
                if total_v > 0:
                    sub_parts.append(f"{total_v:,} visits")
                if p_count > 0:
                    sub_parts.append(f"{p_count:,} photos")
                if contact_info:
                    if contact_info.get("email"):
                        sub_parts.append(contact_info["email"])
                    elif contact_info.get("organization"):
                        sub_parts.append(contact_info["organization"])

                person_results.append({
                    "type": "PERSON",
                    "title": name,
                    "subtitle": " · ".join(sub_parts) if sub_parts else "Tagged person",
                    "name": name,
                    "photo_count": p_count,
                    "visit_count": total_v,
                    "preview_url": f"/api/photo?sha256={top_sha}" if top_sha else None,
                    "sha256": top_sha,
                    "icon": "fa-user",
                })

                for pv in all_p_visits[:8]:
                    p_sha = pv["photo_sha"]
                    cnt = pv["person_photo_cnt"]
                    pname = pv["place_name"] or "Visit"
                    loc = pv["city"] or pv["place_address"] or pv["date"]
                    person_visit_results.append({
                        "type": "PERSON_VISIT",
                        "segment_id": pv["id"],
                        "place_id": pv["place_id"],
                        "title": f"{pname} · {pv['date']}",
                        "subtitle": f"{cnt} photo{'s' if cnt > 1 else ''} with {name} · {loc}",
                        "date": pv["date"],
                        "time": f"{pv['start_time']} - {pv['end_time']}",
                        "category": pv.get("category") or "Other / POI",
                        "latitude": pv.get("latitude"),
                        "longitude": pv.get("longitude"),
                        "preview_url": f"/api/photo?sha256={p_sha}" if p_sha else None,
                        "sha256": p_sha,
                        "photo_count": cnt,
                        "icon": "fa-user-group",
                    })

    # 3. Photo Semantic Search (Visits matching visual concepts; skipped for people queries)
    photo_visits_results: List[Dict[str, Any]] = []
    if not m_iso and not m_us and not is_person_query:
        try:
            from api.photo_search import search_visits_by_photo_semantics
            photo_visits = search_visits_by_photo_semantics(q, limit=12, min_score=0.50)
            for v in photo_visits:
                top_p = v.get("top_photo") or {}
                cnt = v.get("photo_count", 1)
                photo_visits_results.append({
                    "type": "PHOTO_VISIT",
                    "segment_id": v["id"],
                    "place_id": v.get("place_id"),
                    "title": v["place_name"] or "Visit",
                    "subtitle": f"{cnt} photo match{'es' if cnt > 1 else ''} · {v.get('city') or v.get('place_address') or v['date']}",
                    "date": v["date"],
                    "time": f"{v['start_time']} - {v['end_time']}",
                    "category": v.get("category") or "Other / POI",
                    "latitude": v.get("latitude"),
                    "longitude": v.get("longitude"),
                    "preview_url": top_p.get("preview_url") or (f"/api/photo?sha256={top_p['sha256']}" if top_p.get("sha256") else None),
                    "sha256": top_p.get("sha256"),
                    "score": v["max_score"],
                    "photo_count": cnt,
                    "photos": v.get("photos", [])[:4],
                    "icon": "fa-camera-retro",
                })
        except Exception:
            pass

    # 4. Places / POI Search with Match Priority (Name > Address > Review)
    wildcard = f"%{q}%"
    place_limit = min(12, limit)
    if is_person_query:
        # For person queries, only match if the place name itself contains the query
        place_rows = query_all("""
            SELECT max(s.place_id) as place_id, s.place_name, s.place_address, s.category, s.latitude, s.longitude,
                   max(s.date) as last_date, count(s.id) as visit_count, min(s.date) as first_date,
                   p.review_text, p.review_rating, 1 as match_priority
            FROM segments s
            LEFT JOIN places p ON s.place_id = p.place_id
            WHERE s.segment_type = 'visit' AND s.place_name LIKE ?
            GROUP BY s.place_name, s.place_address
            ORDER BY visit_count DESC
            LIMIT ?;
        """, (wildcard, place_limit))
    else:
        place_rows = query_all("""
            SELECT max(s.place_id) as place_id, s.place_name, s.place_address, s.category, s.latitude, s.longitude,
                   max(s.date) as last_date, count(s.id) as visit_count, min(s.date) as first_date,
                   p.review_text, p.review_rating,
                   (CASE WHEN s.place_name LIKE ? THEN 1 WHEN s.place_address LIKE ? THEN 2 ELSE 3 END) as match_priority
            FROM segments s
            LEFT JOIN places p ON s.place_id = p.place_id
            WHERE s.segment_type = 'visit' AND (s.place_name LIKE ? OR s.place_address LIKE ? OR p.review_text LIKE ?)
            GROUP BY s.place_name, s.place_address
            ORDER BY match_priority ASC, visit_count DESC
            LIMIT ?;
        """, (wildcard, wildcard, wildcard, wildcard, wildcard, place_limit))

    place_results: List[Dict[str, Any]] = []
    review_match_count = 0
    for r in place_rows:
        is_review_only = (r["match_priority"] == 3)
        if is_review_only:
            review_match_count += 1
            if review_match_count > 3:
                continue
            rev = r.get("review_text") or ""
            idx = rev.lower().find(q.lower())
            start = max(0, idx - 18)
            end = min(len(rev), idx + len(q) + 26)
            snippet = ("..." if start > 0 else "") + rev[start:end].strip() + ("..." if end < len(rev) else "")
            sub = f"Review match: \"{snippet}\""
        else:
            sub = r["place_address"] or (f"{r['latitude']:.4f}, {r['longitude']:.4f}" if r.get("latitude") else "Unknown location")

        pid = r.get("place_id")
        pname = r.get("place_name")
        plat = r.get("latitude")
        plng = r.get("longitude")
        place_photo = None
        if pid:
            place_photo = query_one("""
                SELECT sha256 FROM photos
                WHERE place_id = ? AND timestamp_utc IS NOT NULL
                ORDER BY (CASE WHEN face_count > 0 THEN 0 ELSE 1 END),
                         (CASE WHEN filename LIKE 'Screen%' OR filename LIKE 'Screenshot%' THEN 1 ELSE 0 END),
                         timestamp_utc DESC
                LIMIT 1;
            """, (pid,))
        if not place_photo and pname:
            place_photo = query_one("""
                SELECT p.sha256 FROM photos p
                JOIN segments s ON p.timestamp_utc >= s.start_ts AND p.timestamp_utc <= s.end_ts
                WHERE s.place_name = ? AND p.timestamp_utc IS NOT NULL
                ORDER BY (CASE WHEN p.face_count > 0 THEN 0 ELSE 1 END),
                         (CASE WHEN p.filename LIKE 'Screen%' OR p.filename LIKE 'Screenshot%' THEN 1 ELSE 0 END),
                         p.timestamp_utc DESC
                LIMIT 1;
            """, (pname,))
        if not place_photo and plat is not None and plng is not None:
            place_photo = query_one("""
                SELECT sha256 FROM photos
                WHERE abs(latitude - ?) < 0.0008 AND abs(longitude - ?) < 0.0008 AND timestamp_utc IS NOT NULL
                ORDER BY (CASE WHEN face_count > 0 THEN 0 ELSE 1 END),
                         (CASE WHEN filename LIKE 'Screen%' OR filename LIKE 'Screenshot%' THEN 1 ELSE 0 END),
                         timestamp_utc DESC
                LIMIT 1;
            """, (plat, plng))
        p_sha = place_photo["sha256"] if place_photo else None

        place_results.append({
            "type": "PLACE",
            "place_id": pid,
            "title": r["place_name"] or r["place_address"] or "Visit",
            "subtitle": sub,
            "category": r["category"] or "Other / POI",
            "latitude": r["latitude"],
            "longitude": r["longitude"],
            "date": r["last_date"],
            "visit_count": r["visit_count"],
            "first_date": r["first_date"],
            "preview_url": f"/api/photo?sha256={p_sha}" if p_sha else None,
            "sha256": p_sha,
            "icon": "fa-location-dot",
            "is_review_match": is_review_only,
        })

    # 5. Categories Search (skipped for person queries)
    category_results: List[Dict[str, Any]] = []
    if not is_person_query:
        cat_rows = query_all("""
            SELECT category, count(DISTINCT date) as days_count, count(id) as visit_count, max(date) as last_date
            FROM segments
            WHERE category LIKE ? AND segment_type = 'visit'
            GROUP BY category
            LIMIT 3;
        """, (f"%{q}%",))

        for r in cat_rows:
            category_results.append({
                "type": "CATEGORY",
                "title": f"Category: {r['category']}",
                "subtitle": f"{r['visit_count']} visits across {r['days_count']} days · Last: {r['last_date']}",
                "date": r["last_date"],
                "icon": "fa-tag"
            })

    all_results = results + person_results + person_visit_results + photo_visits_results + place_results + category_results
    return json_response({"status": "SUCCESS", "count": len(all_results), "results": all_results[:limit]})


@router.get("/api/visits/search")
def search_visits(req: Request) -> Response:
    """
    Dedicated visit search by semantic visual concepts and text.
    Query params:
      q: search string (e.g. 'coffee', 'skiing', 'Central Park')
      semantic: 1 to enable CLIP photo semantic search (default: 1)
      limit: max results (default: 30)
      min_score: minimum semantic similarity score (default: 0.50)
    """
    q = req.get_str("q").strip()
    limit = min(100, max(1, req.get_int("limit", 30)))
    min_score = req.get_float("min_score", 0.50)
    use_semantic = req.get_int("semantic", 1) == 1

    if not q:
        return json_response({"status": "SUCCESS", "count": 0, "visits": []})

    visits: List[Dict[str, Any]] = []
    if use_semantic:
        try:
            from api.photo_search import search_visits_by_photo_semantics
            visits = search_visits_by_photo_semantics(q, limit=limit, min_score=min_score)
        except Exception:
            visits = []

    # If semantic search returned fewer than requested, backfill with direct text matches
    if len(visits) < limit:
        needed = limit - len(visits)
        seen_ids = {v["id"] for v in visits}
        text_matches = query_all("""
            SELECT id, date, start_ts, end_ts, start_time, end_time, duration_minutes,
                   place_name, place_address, place_id, category, latitude, longitude, city
            FROM segments
            WHERE segment_type = 'visit' AND (place_name LIKE ? OR place_address LIKE ?)
            ORDER BY start_ts DESC
            LIMIT ?;
        """, (f"%{q}%", f"%{q}%", needed * 2))

        for tm in text_matches:
            if tm["id"] in seen_ids:
                continue
            tm_photo = query_one("""
                SELECT sha256, filename FROM photos
                WHERE timestamp_utc >= ? AND timestamp_utc <= ? AND timestamp_utc IS NOT NULL
                ORDER BY (CASE WHEN face_count > 0 THEN 0 ELSE 1 END),
                         (CASE WHEN filename LIKE 'Screen%' OR filename LIKE 'Screenshot%' THEN 1 ELSE 0 END),
                         timestamp_utc DESC
                LIMIT 1;
            """, (tm["start_ts"], tm["end_ts"]))
            tm_sha = tm_photo["sha256"] if tm_photo else None
            top_p_obj = {"sha256": tm_sha, "preview_url": f"/api/photo?sha256={tm_sha}"} if tm_sha else None

            visits.append({
                "id": tm["id"],
                "date": tm["date"],
                "start_time": tm["start_time"],
                "end_time": tm["end_time"],
                "duration_minutes": tm["duration_minutes"],
                "place_name": tm["place_name"] or "Visit",
                "place_address": tm["place_address"],
                "place_id": tm["place_id"],
                "category": tm["category"] or "Other / POI",
                "city": tm["city"],
                "latitude": tm["latitude"],
                "longitude": tm["longitude"],
                "max_score": 1.0,
                "photo_count": 1 if tm_sha else 0,
                "photos": [top_p_obj] if top_p_obj else [],
                "top_photo": top_p_obj,
                "preview_url": f"/api/photo?sha256={tm_sha}" if tm_sha else None,
                "sha256": tm_sha,
            })
            seen_ids.add(tm["id"])
            if len(visits) >= limit:
                break

    return json_response({
        "status": "SUCCESS",
        "count": len(visits),
        "query": q,
        "visits": visits,
    })


@router.get("/api/people/visits")
def get_person_visits(req: Request) -> Response:
    """
    Returns exhaustive list of timeline visits where a person was present
    (tagged in photos or calendar events), ordered chronologically DESC.
    """
    name = req.get_str("name") or req.get_str("q")
    name = name.strip()
    if not name:
        return json_response({"status": "SUCCESS", "name": "", "count": 0, "visits": []})

    limit = min(2000, max(1, req.get_int("limit", 1500)))
    offset = max(0, req.get_int("offset", 0))
    name_wildcards = (f"{name}%", f"% {name}%", f"%, {name}%")

    # Query distinct visit segments overlapping photos of this person, selecting best photo with face
    sql = """
        SELECT s.id, s.date, s.start_time, s.end_time, s.duration_minutes,
               s.place_name, s.place_address, s.place_id, s.category, s.city, s.latitude, s.longitude,
               count(p.sha256) as photo_count,
               (
                   SELECT p2.sha256
                   FROM photos p2
                   WHERE p2.timestamp_utc >= s.start_ts AND p2.timestamp_utc <= s.end_ts
                     AND (p2.people LIKE ? OR p2.people LIKE ? OR p2.people LIKE ?)
                   ORDER BY (CASE WHEN p2.face_count > 0 THEN 0 ELSE 1 END),
                            (CASE WHEN p2.filename LIKE 'Screen%' OR p2.filename LIKE 'Screenshot%' THEN 1 ELSE 0 END),
                            p2.timestamp_utc DESC
                   LIMIT 1
               ) as top_sha
        FROM (
            SELECT sha256, timestamp_utc
            FROM photos
            WHERE (people LIKE ? OR people LIKE ? OR people LIKE ?) AND timestamp_utc IS NOT NULL
        ) p
        JOIN segments s ON p.timestamp_utc >= s.start_ts AND p.timestamp_utc <= s.end_ts
        WHERE s.segment_type = 'visit'
        GROUP BY s.id
        ORDER BY s.date DESC, s.start_ts DESC
        LIMIT ? OFFSET ?;
    """
    rows = query_all(sql, name_wildcards + name_wildcards + (limit, offset))

    # Fetch contact info if available
    contact = query_one("""
        SELECT name, email, phone, organization, full_address
        FROM contacts
        WHERE name LIKE ? OR name LIKE ?
        LIMIT 1;
    """, (f"{name}%", f"% {name}%"))

    visits = []
    for r in rows:
        top_sha = r.get("top_sha")

        visits.append({
            "id": r["id"],
            "date": r["date"],
            "start_time": r["start_time"],
            "end_time": r["end_time"],
            "duration_minutes": r["duration_minutes"],
            "place_name": r["place_name"] or "Visit",
            "place_address": r["place_address"],
            "place_id": r["place_id"],
            "category": r["category"] or "Other / POI",
            "city": r["city"],
            "latitude": r["latitude"],
            "longitude": r["longitude"],
            "photo_count": r["photo_count"],
            "preview_url": f"/api/photo?sha256={top_sha}" if top_sha else None,
            "sha256": top_sha,
        })

    # Compute total visit count across all time
    cnt_row = query_one("""
        SELECT count(DISTINCT s.id) as total_cnt
        FROM (
            SELECT timestamp_utc FROM photos
            WHERE (people LIKE ? OR people LIKE ? OR people LIKE ?) AND timestamp_utc IS NOT NULL
        ) p
        JOIN segments s ON p.timestamp_utc >= s.start_ts AND p.timestamp_utc <= s.end_ts
        WHERE s.segment_type = 'visit';
    """, name_wildcards)
    total_visits = cnt_row["total_cnt"] if cnt_row else len(visits)

    return json_response({
        "status": "SUCCESS",
        "name": name,
        "count": len(visits),
        "total_visits": total_visits,
        "contact": contact,
        "visits": visits,
    })


