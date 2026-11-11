"""
Universal Search Engine (Dates, Months, Places, Categories, Locations, and Events).

Powered by external-content SQLite FTS5 indexes (`places_fts`, `photos_fts`, `segments_fts`)
and batched photo resolution to eliminate full-table `LIKE` scans and N+1 round-trips.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from api.db import build_fts_match_query, query_all, query_one
from api.response import Response, json_response
from api.router import Request, router


def _resolve_place_photos_batch(place_rows: List[Dict[str, Any]]) -> Dict[int, str]:
    """Resolves top preview photo sha256 per place row index using batched queries + sargable bbox."""
    resolved: Dict[int, str] = {}
    if not place_rows:
        return resolved

    # 1. Batch lookup by place_id using idx_photos_place_id
    pids = sorted({str(r["place_id"]) for r in place_rows if r.get("place_id")})
    by_pid: Dict[str, str] = {}
    if pids:
        holders = ",".join("?" for _ in pids)
        pid_rows = query_all(
            f"""
            WITH ranked AS (
                SELECT place_id, sha256,
                       ROW_NUMBER() OVER (
                           PARTITION BY place_id
                           ORDER BY (CASE WHEN face_count > 0 THEN 0 ELSE 1 END),
                                    (CASE WHEN filename LIKE 'Screen%' OR filename LIKE 'Screenshot%' THEN 1 ELSE 0 END),
                                    timestamp_utc DESC
                       ) as rn
                FROM photos
                WHERE place_id IN ({holders}) AND timestamp_utc IS NOT NULL
            )
            SELECT place_id, sha256 FROM ranked WHERE rn = 1;
            """,
            pids,
        )
        by_pid = {str(row["place_id"]): str(row["sha256"]) for row in pid_rows if row.get("sha256")}

    unmatched_indices: List[int] = []
    for idx, r in enumerate(place_rows):
        pid = str(r["place_id"]) if r.get("place_id") else ""
        if pid and pid in by_pid:
            resolved[idx] = by_pid[pid]
        else:
            unmatched_indices.append(idx)

    if not unmatched_indices:
        return resolved

    # 2. Batch lookup by place_name using idx_photos_place_name
    pnames = sorted({
        str(place_rows[idx]["place_name"])
        for idx in unmatched_indices
        if place_rows[idx].get("place_name")
    })
    by_pname: Dict[str, str] = {}
    if pnames:
        holders = ",".join("?" for _ in pnames)
        name_rows = query_all(
            f"""
            WITH ranked AS (
                SELECT place_name, sha256,
                       ROW_NUMBER() OVER (
                           PARTITION BY place_name
                           ORDER BY (CASE WHEN face_count > 0 THEN 0 ELSE 1 END),
                                    (CASE WHEN filename LIKE 'Screen%' OR filename LIKE 'Screenshot%' THEN 1 ELSE 0 END),
                                    timestamp_utc DESC
                       ) as rn
                FROM photos
                WHERE place_name IN ({holders}) AND timestamp_utc IS NOT NULL
            )
            SELECT place_name, sha256 FROM ranked WHERE rn = 1;
            """,
            pnames,
        )
        by_pname = {
            str(row["place_name"]): str(row["sha256"])
            for row in name_rows
            if row.get("sha256")
        }

    still_unmatched: List[int] = []
    for idx in unmatched_indices:
        pname = str(place_rows[idx]["place_name"]) if place_rows[idx].get("place_name") else ""
        if pname and pname in by_pname:
            resolved[idx] = by_pname[pname]
        else:
            still_unmatched.append(idx)

    # 3. Sargable bounding-box range lookup on idx_photos_coords(latitude, longitude)
    for idx in still_unmatched:
        plat = place_rows[idx].get("latitude")
        plng = place_rows[idx].get("longitude")
        if plat is None or plng is None:
            continue
        f_lat = float(plat)
        f_lng = float(plng)
        coord_photo = query_one(
            """
            SELECT sha256 FROM photos
            WHERE latitude BETWEEN ? AND ?
              AND longitude BETWEEN ? AND ?
              AND timestamp_utc IS NOT NULL
            ORDER BY (CASE WHEN face_count > 0 THEN 0 ELSE 1 END),
                     (CASE WHEN filename LIKE 'Screen%' OR filename LIKE 'Screenshot%' THEN 1 ELSE 0 END),
                     timestamp_utc DESC
            LIMIT 1;
            """,
            (f_lat - 0.0008, f_lat + 0.0008, f_lng - 0.0008, f_lng + 0.0008),
        )
        if coord_photo and coord_photo.get("sha256"):
            resolved[idx] = str(coord_photo["sha256"])

    return resolved


@router.get("/api/search")
def search(req: Request) -> Response:
    """Multi-modal timeline search."""
    q = req.get_str("q").strip()
    limit = min(50, max(1, req.get_int("limit", 25)))
    if not q:
        return json_response({"status": "SUCCESS", "count": 0, "results": []})

    fts_expr = build_fts_match_query(q)
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
        r = query_one(
            "SELECT count(*) as cnt, sum(distance_meters) as dist FROM segments WHERE date = ?;",
            (dt,),
        )
        if r and r.get("cnt", 0) > 0:
            p_rows = query_all(
                "SELECT DISTINCT place_name FROM segments WHERE date = ? AND place_name IS NOT NULL LIMIT 4;",
                (dt,),
            )
            pnames = [row["place_name"] for row in p_rows if row.get("place_name")]
            day_photo = query_one(
                """
                SELECT sha256 FROM photos
                WHERE local_date = ? AND timestamp_utc IS NOT NULL
                ORDER BY (CASE WHEN face_count > 0 THEN 0 ELSE 1 END),
                         (CASE WHEN filename LIKE 'Screen%' OR filename LIKE 'Screenshot%' THEN 1 ELSE 0 END),
                         timestamp_utc DESC
                LIMIT 1;
                """,
                (dt,),
            )
            d_sha = day_photo["sha256"] if day_photo else None
            results.append({
                "type": "DATE",
                "title": f"Day Timeline: {dt}",
                "subtitle": f"{r['cnt']} segments · {round((r.get('dist') or 0)/1000.0, 1)} km · {pnames[0] if pnames else 'Trip activity'}",
                "date": dt,
                "places": pnames,
                "preview_url": f"/api/photo?sha256={d_sha}" if d_sha else None,
                "sha256": d_sha,
                "icon": "fa-calendar-day",
            })

    # 2. Person & Contact Search (Indexed via photos_fts)
    person_results: List[Dict[str, Any]] = []
    person_visit_results: List[Dict[str, Any]] = []
    is_person_query = False

    if not m_iso and not m_us:
        if fts_expr:
            photo_people_rows = query_all(
                """
                SELECT p.people, count(*) as cnt
                FROM photos_fts f
                JOIN photos p ON p.rowid = f.rowid
                WHERE photos_fts MATCH ?
                  AND (p.people LIKE ? OR p.people LIKE ? OR p.people LIKE ?)
                GROUP BY p.people
                ORDER BY cnt DESC;
                """,
                (f"people : ({fts_expr})", f"{q}%", f"% {q}%", f"%, {q}%"),
            )
        else:
            photo_people_rows = query_all(
                """
                SELECT people, count(*) as cnt
                FROM photos
                WHERE people LIKE ? OR people LIKE ? OR people LIKE ?
                GROUP BY people
                ORDER BY cnt DESC;
                """,
                (f"{q}%", f"% {q}%", f"%, {q}%"),
            )

        candidate_counts: Dict[str, int] = {}
        for pr in photo_people_rows:
            raw_people = pr.get("people") or ""
            for nm in raw_people.split(","):
                nm = nm.strip()
                words = nm.split()
                if any(w.lower().startswith(q.lower()) for w in words):
                    candidate_counts[nm] = candidate_counts.get(nm, 0) + pr["cnt"]

        contact_rows = query_all(
            """
            SELECT name, email, phone, organization, full_address
            FROM contacts
            WHERE name LIKE ? OR name LIKE ?;
            """,
            (f"{q}%", f"% {q}%"),
        )
        contact_map = {c["name"]: c for c in contact_rows}
        for cname in contact_map:
            if cname not in candidate_counts:
                candidate_counts[cname] = 0

        sorted_candidates = sorted(
            candidate_counts.items(), key=lambda x: (x[1], x[0]), reverse=True
        )

        if sorted_candidates:
            is_person_query = True
            for name, p_count in sorted_candidates[:3]:
                name_fts = build_fts_match_query(name)
                name_wcards = (f"{name}%", f"% {name}%", f"%, {name}%")
                if name_fts:
                    best_photo_row = query_one(
                        """
                        SELECT p.sha256, p.filename, p.face_count
                        FROM photos_fts f
                        JOIN photos p ON p.rowid = f.rowid
                        WHERE photos_fts MATCH ?
                          AND (p.people LIKE ? OR p.people LIKE ? OR p.people LIKE ?)
                          AND p.timestamp_utc IS NOT NULL
                        ORDER BY (CASE WHEN p.face_count > 0 THEN 0 ELSE 1 END),
                                 (CASE WHEN p.filename LIKE 'Screen%' OR p.filename LIKE 'Screenshot%' THEN 1 ELSE 0 END),
                                 p.timestamp_utc DESC
                        LIMIT 1;
                        """,
                        (f"people : ({name_fts})", *name_wcards),
                    )
                    all_p_visits = query_all(
                        """
                        WITH person_photos AS (
                            SELECT p.sha256, p.filename, p.timestamp_utc, p.face_count
                            FROM photos_fts f
                            JOIN photos p ON p.rowid = f.rowid
                            WHERE photos_fts MATCH ?
                              AND (p.people LIKE ? OR p.people LIKE ? OR p.people LIKE ?)
                              AND p.timestamp_utc IS NOT NULL
                        ),
                        visit_photo_ranks AS (
                            SELECT s.id, s.date, s.start_time, s.end_time, s.duration_minutes,
                                   s.place_name, s.place_address, s.place_id, s.category, s.city,
                                   s.latitude, s.longitude, p.sha256,
                                   ROW_NUMBER() OVER (
                                       PARTITION BY s.id
                                       ORDER BY (CASE WHEN p.face_count > 0 THEN 0 ELSE 1 END),
                                                (CASE WHEN p.filename LIKE 'Screen%' OR p.filename LIKE 'Screenshot%' THEN 1 ELSE 0 END),
                                                p.timestamp_utc DESC
                                   ) as rn
                            FROM person_photos p
                            JOIN segments s ON p.timestamp_utc >= s.start_ts AND p.timestamp_utc <= s.end_ts
                            WHERE s.segment_type = 'visit'
                        )
                        SELECT id, date, start_time, end_time, duration_minutes,
                               place_name, place_address, place_id, category, city, latitude, longitude,
                               count(*) as person_photo_cnt,
                               max(CASE WHEN rn = 1 THEN sha256 END) as photo_sha
                        FROM visit_photo_ranks
                        GROUP BY id
                        ORDER BY date DESC;
                        """,
                        (f"people : ({name_fts})", *name_wcards),
                    )
                else:
                    best_photo_row = query_one(
                        """
                        SELECT sha256, filename, face_count
                        FROM photos
                        WHERE (people LIKE ? OR people LIKE ? OR people LIKE ?) AND timestamp_utc IS NOT NULL
                        ORDER BY (CASE WHEN face_count > 0 THEN 0 ELSE 1 END),
                                 (CASE WHEN filename LIKE 'Screen%' OR filename LIKE 'Screenshot%' THEN 1 ELSE 0 END),
                                 timestamp_utc DESC
                        LIMIT 1;
                        """,
                        name_wcards,
                    )
                    all_p_visits = query_all(
                        """
                        SELECT s.id, s.date, s.start_time, s.end_time, s.duration_minutes,
                               s.place_name, s.place_address, s.place_id, s.category, s.city, s.latitude, s.longitude,
                               count(p.sha256) as person_photo_cnt,
                               max(p.sha256) as photo_sha
                        FROM (
                            SELECT sha256, timestamp_utc
                            FROM photos
                            WHERE (people LIKE ? OR people LIKE ? OR people LIKE ?) AND timestamp_utc IS NOT NULL
                        ) p
                        JOIN segments s ON p.timestamp_utc >= s.start_ts AND p.timestamp_utc <= s.end_ts
                        WHERE s.segment_type = 'visit'
                        GROUP BY s.id
                        ORDER BY s.date DESC;
                        """,
                        name_wcards,
                    )

                top_sha = best_photo_row["sha256"] if best_photo_row else None
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
                    "preview_url": top_p.get("preview_url")
                    or (f"/api/photo?sha256={top_p['sha256']}" if top_p.get("sha256") else None),
                    "sha256": top_p.get("sha256"),
                    "score": v["max_score"],
                    "photo_count": cnt,
                    "photos": v.get("photos", [])[:4],
                    "icon": "fa-camera-retro",
                })
        except Exception:
            pass

    # 4. Places / POI Search via places_fts (with fallback for mid-word or punctuation queries)
    wildcard = f"%{q}%"
    place_limit = min(12, limit)
    place_rows: List[Dict[str, Any]] = []
    if is_person_query:
        if fts_expr:
            place_rows = query_all(
                """
                SELECT p.place_id, p.name as place_name, p.address as place_address, p.category,
                       p.latitude, p.longitude, substr(p.last_visit_time, 1, 10) as last_date,
                       p.visit_count, substr(p.first_visit_time, 1, 10) as first_date,
                       p.review_text, p.review_rating, 1 as match_priority
                FROM places_fts f
                JOIN places p ON p.rowid = f.rowid
                WHERE places_fts MATCH ? AND p.visit_count > 0
                ORDER BY p.visit_count DESC
                LIMIT ?;
                """,
                (f"name : ({fts_expr})", place_limit),
            )
        if not place_rows:
            place_rows = query_all(
                """
                SELECT place_id, name as place_name, address as place_address, category, latitude, longitude,
                       substr(last_visit_time, 1, 10) as last_date, visit_count, substr(first_visit_time, 1, 10) as first_date,
                       review_text, review_rating, 1 as match_priority
                FROM places
                WHERE visit_count > 0 AND name LIKE ?
                ORDER BY visit_count DESC
                LIMIT ?;
                """,
                (wildcard, place_limit),
            )
    else:
        if fts_expr:
            place_rows = query_all(
                """
                SELECT p.place_id, p.name as place_name, p.address as place_address, p.category,
                       p.latitude, p.longitude, substr(p.last_visit_time, 1, 10) as last_date,
                       p.visit_count, substr(p.first_visit_time, 1, 10) as first_date,
                       p.review_text, p.review_rating,
                       (CASE
                            WHEN p.name LIKE ? THEN 1
                            WHEN p.address LIKE ? OR p.city LIKE ? THEN 2
                            ELSE 3
                        END) as match_priority
                FROM places_fts f
                JOIN places p ON p.rowid = f.rowid
                WHERE places_fts MATCH ? AND p.visit_count > 0
                ORDER BY match_priority ASC, p.visit_count DESC
                LIMIT ?;
                """,
                (wildcard, wildcard, wildcard, fts_expr, place_limit),
            )
        if not place_rows:
            place_rows = query_all(
                """
                SELECT place_id, name as place_name, address as place_address, category, latitude, longitude,
                       substr(last_visit_time, 1, 10) as last_date, visit_count, substr(first_visit_time, 1, 10) as first_date,
                       review_text, review_rating,
                       (CASE WHEN name LIKE ? THEN 1 WHEN address LIKE ? THEN 2 ELSE 3 END) as match_priority
                FROM places
                WHERE visit_count > 0 AND (name LIKE ? OR address LIKE ? OR review_text LIKE ?)
                ORDER BY match_priority ASC, visit_count DESC
                LIMIT ?;
                """,
                (wildcard, wildcard, wildcard, wildcard, wildcard, place_limit),
            )

    batch_photos = _resolve_place_photos_batch(place_rows)
    place_results: List[Dict[str, Any]] = []
    review_match_count = 0
    for idx, r in enumerate(place_rows):
        is_review_only = (
            r["match_priority"] == 3
            and bool(r.get("review_text"))
            and q.lower() in str(r.get("review_text") or "").lower()
        )
        if is_review_only:
            review_match_count += 1
            if review_match_count > 3:
                continue
            rev = r.get("review_text") or ""
            pos = rev.lower().find(q.lower())
            start = max(0, pos - 18)
            end = min(len(rev), pos + len(q) + 26)
            snippet = (
                ("..." if start > 0 else "")
                + rev[start:end].strip()
                + ("..." if end < len(rev) else "")
            )
            sub = f'Review match: "{snippet}"'
        else:
            sub = r["place_address"] or (
                f"{r['latitude']:.4f}, {r['longitude']:.4f}"
                if r.get("latitude")
                else "Unknown location"
            )

        place_sha: Optional[str] = batch_photos.get(idx)
        place_results.append({
            "type": "PLACE",
            "place_id": r.get("place_id"),
            "title": r["place_name"] or r["place_address"] or "Visit",
            "subtitle": sub,
            "category": r["category"] or "Other / POI",
            "latitude": r["latitude"],
            "longitude": r["longitude"],
            "date": r["last_date"],
            "visit_count": r["visit_count"],
            "first_date": r["first_date"],
            "preview_url": f"/api/photo?sha256={place_sha}" if place_sha else None,
            "sha256": place_sha,
            "icon": "fa-location-dot",
            "is_review_match": is_review_only,
        })

    # 5. Categories Search (fast scan over idx_segments_category)
    category_results: List[Dict[str, Any]] = []
    if not is_person_query:
        cat_rows = query_all(
            """
            SELECT category, count(DISTINCT date) as days_count, count(id) as visit_count, max(date) as last_date
            FROM segments
            WHERE category LIKE ? AND segment_type = 'visit'
            GROUP BY category
            LIMIT 3;
            """,
            (f"%{q}%",),
        )
        for r in cat_rows:
            category_results.append({
                "type": "CATEGORY",
                "title": f"Category: {r['category']}",
                "subtitle": f"{r['visit_count']} visits across {r['days_count']} days · Last: {r['last_date']}",
                "date": r["last_date"],
                "icon": "fa-tag",
            })

    all_results = (
        results
        + person_results
        + person_visit_results
        + place_results
        + photo_visits_results
        + category_results
    )
    final_results = all_results[:limit]
    from api.routes.photos import find_preview_file

    for item in final_results:
        cand_sha = item.get("sha256")
        if cand_sha and find_preview_file(str(cand_sha)) is None:
            item["preview_url"] = None
            item["sha256"] = None

    return json_response({"status": "SUCCESS", "count": len(all_results), "results": final_results})


@router.get("/api/visits/search")
def search_visits(req: Request) -> Response:
    """Dedicated visit search by semantic visual concepts and FTS5 text."""
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

    if len(visits) < limit:
        needed = limit - len(visits)
        seen_ids = {v["id"] for v in visits}
        fts_expr = build_fts_match_query(q)
        text_matches: List[Dict[str, Any]] = []
        if fts_expr:
            text_matches = query_all(
                """
                SELECT s.id, s.date, s.start_ts, s.end_ts, s.start_time, s.end_time,
                       s.duration_minutes, s.place_name, s.place_address, s.place_id,
                       s.category, s.latitude, s.longitude, s.city
                FROM segments_fts f
                JOIN segments s ON s.id = f.rowid
                WHERE segments_fts MATCH ? AND s.segment_type = 'visit'
                ORDER BY s.start_ts DESC
                LIMIT ?;
                """,
                (fts_expr, needed * 2),
            )
        if not text_matches:
            text_matches = query_all(
                """
                SELECT id, date, start_ts, end_ts, start_time, end_time, duration_minutes,
                       place_name, place_address, place_id, category, latitude, longitude, city
                FROM segments
                WHERE segment_type = 'visit' AND (place_name LIKE ? OR place_address LIKE ?)
                ORDER BY start_ts DESC
                LIMIT ?;
                """,
                (f"%{q}%", f"%{q}%", needed * 2),
            )

        for tm in text_matches:
            if tm["id"] in seen_ids:
                continue
            tm_photo = query_one(
                """
                SELECT sha256, filename FROM photos
                WHERE timestamp_utc >= ? AND timestamp_utc <= ? AND timestamp_utc IS NOT NULL
                ORDER BY (CASE WHEN face_count > 0 THEN 0 ELSE 1 END),
                         (CASE WHEN filename LIKE 'Screen%' OR filename LIKE 'Screenshot%' THEN 1 ELSE 0 END),
                         timestamp_utc DESC
                LIMIT 1;
                """,
                (tm["start_ts"], tm["end_ts"]),
            )
            tm_sha = tm_photo["sha256"] if tm_photo else None
            top_p_obj = (
                {"sha256": tm_sha, "preview_url": f"/api/photo?sha256={tm_sha}"}
                if tm_sha
                else None
            )

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
    """Returns exhaustive list of timeline visits where a person was present."""
    name = (req.get_str("name") or req.get_str("q")).strip()
    if not name:
        return json_response({"status": "SUCCESS", "name": "", "count": 0, "visits": []})

    limit = min(2000, max(1, req.get_int("limit", 1500)))
    offset = max(0, req.get_int("offset", 0))
    name_wildcards = (f"{name}%", f"% {name}%", f"%, {name}%")
    name_fts = build_fts_match_query(name)

    if name_fts:
        sql = """
            WITH person_photos AS (
                SELECT p.sha256, p.filename, p.timestamp_utc, p.face_count
                FROM photos_fts f
                JOIN photos p ON p.rowid = f.rowid
                WHERE photos_fts MATCH ?
                  AND (p.people LIKE ? OR p.people LIKE ? OR p.people LIKE ?)
                  AND p.timestamp_utc IS NOT NULL
            ),
            visit_photo_ranks AS (
                SELECT s.id, s.date, s.start_ts, s.start_time, s.end_time, s.duration_minutes,
                       s.place_name, s.place_address, s.place_id, s.category, s.city,
                       s.latitude, s.longitude, p.sha256,
                       ROW_NUMBER() OVER (
                           PARTITION BY s.id
                           ORDER BY (CASE WHEN p.face_count > 0 THEN 0 ELSE 1 END),
                                    (CASE WHEN p.filename LIKE 'Screen%' OR p.filename LIKE 'Screenshot%' THEN 1 ELSE 0 END),
                                    p.timestamp_utc DESC
                       ) as rn
                FROM person_photos p
                JOIN segments s ON p.timestamp_utc >= s.start_ts AND p.timestamp_utc <= s.end_ts
                WHERE s.segment_type = 'visit'
            )
            SELECT id, date, start_time, end_time, duration_minutes,
                   place_name, place_address, place_id, category, city, latitude, longitude,
                   count(*) as photo_count,
                   max(CASE WHEN rn = 1 THEN sha256 END) as top_sha
            FROM visit_photo_ranks
            GROUP BY id
            ORDER BY date DESC, start_ts DESC
            LIMIT ? OFFSET ?;
        """
        rows = query_all(sql, (f"people : ({name_fts})", *name_wildcards, limit, offset))
        cnt_row = query_one(
            """
            SELECT count(DISTINCT s.id) as total_cnt
            FROM photos_fts f
            JOIN photos p ON p.rowid = f.rowid
            JOIN segments s ON p.timestamp_utc >= s.start_ts AND p.timestamp_utc <= s.end_ts
            WHERE photos_fts MATCH ?
              AND (p.people LIKE ? OR p.people LIKE ? OR p.people LIKE ?)
              AND p.timestamp_utc IS NOT NULL
              AND s.segment_type = 'visit';
            """,
            (f"people : ({name_fts})", *name_wildcards),
        )
    else:
        sql = """
            SELECT s.id, s.date, s.start_time, s.end_time, s.duration_minutes,
                   s.place_name, s.place_address, s.place_id, s.category, s.city, s.latitude, s.longitude,
                   count(p.sha256) as photo_count,
                   max(p.sha256) as top_sha
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
        rows = query_all(sql, (*name_wildcards, limit, offset))
        cnt_row = query_one(
            """
            SELECT count(DISTINCT s.id) as total_cnt
            FROM (
                SELECT timestamp_utc FROM photos
                WHERE (people LIKE ? OR people LIKE ? OR people LIKE ?) AND timestamp_utc IS NOT NULL
            ) p
            JOIN segments s ON p.timestamp_utc >= s.start_ts AND p.timestamp_utc <= s.end_ts
            WHERE s.segment_type = 'visit';
            """,
            name_wildcards,
        )

    contact = query_one(
        """
        SELECT name, email, phone, organization, full_address
        FROM contacts
        WHERE name LIKE ? OR name LIKE ?
        LIMIT 1;
        """,
        (f"{name}%", f"% {name}%"),
    )

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

    total_visits = cnt_row["total_cnt"] if cnt_row else len(visits)
    return json_response({
        "status": "SUCCESS",
        "name": name,
        "count": len(visits),
        "total_visits": total_visits,
        "contact": contact,
        "visits": visits,
    })
