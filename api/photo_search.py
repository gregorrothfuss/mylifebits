"""
Photo Semantic Search Engine & Visit Matcher.
Connects with photos.local (CLIP ViT-B-32 vector index across 160k photos)
and resolves authentic visits where those photos were captured.
"""

from __future__ import annotations

import json
import logging
import math
import ssl
import time
import urllib.parse
import urllib.request
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from api.db import query_all, query_one

logger = logging.getLogger("photo_search")

# In-memory LRU cache for photo semantic queries: (query -> (timestamp, photos_list))
_SEARCH_CACHE: OrderedDict[str, Tuple[float, List[Dict[str, Any]]]] = OrderedDict()
_CACHE_MAX_SIZE = 250
_CACHE_TTL_SECONDS = 3600  # 1 hour


def _haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Computes great-circle distance between two GPS coordinates in meters."""
    r = 6371000.0  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def query_photo_semantic_index(query: str, limit: int = 60) -> List[Dict[str, Any]]:
    """
    Queries the semantic photo index via photos.local API.
    Returns list of dicts: [{sha256, score, filename, formatted_date, ...}]
    """
    clean_q = query.strip().lower()
    if not clean_q:
        return []

    now = time.time()
    if clean_q in _SEARCH_CACHE:
        cached_ts, cached_res = _SEARCH_CACHE[clean_q]
        if now - cached_ts < _CACHE_TTL_SECONDS:
            _SEARCH_CACHE.move_to_end(clean_q)
            return cached_res[:limit]

    # Query official photos.local service
    url = f"https://photos.local/api/search?q={urllib.parse.quote(clean_q)}"
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "LifeBits-VisitSearch/1.0", "Accept": "application/json"}
    )

    photos: List[Dict[str, Any]] = []
    try:
        with urllib.request.urlopen(req, timeout=12, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            photos = data.get("results", [])
    except Exception as e:
        logger.warning(f"photos.local search request failed: {e}")
        photos = []

    # Update LRU cache
    if clean_q in _SEARCH_CACHE:
        del _SEARCH_CACHE[clean_q]
    elif len(_SEARCH_CACHE) >= _CACHE_MAX_SIZE:
        _SEARCH_CACHE.popitem(last=False)
    _SEARCH_CACHE[clean_q] = (now, photos)

    return photos[:limit]


def search_visits_by_photo_semantics(
    query: str,
    limit: int = 25,
    min_score: float = 0.60,
) -> List[Dict[str, Any]]:
    """
    Performs semantic concept search across photos and maps matching photos
    to physical visits recorded in timeline_viewer.db.
    """
    clean_q = query.strip()
    if not clean_q:
        return []

    photos = query_photo_semantic_index(clean_q, limit=60)
    if not photos:
        return []

    # Collect sha256 to semantic score mapping
    sha_scores = {
        p["sha256"]: float(p.get("score", 0.0))
        for p in photos
        if p.get("sha256") and float(p.get("score", 0.0)) >= min_score
    }
    if not sha_scores:
        return []

    shas = list(sha_scores.keys())
    placeholders = ",".join("?" for _ in shas)

    # Fetch photo metadata from local photos table in timeline_viewer.db
    photo_rows = query_all(f"""
        SELECT sha256, filename, timestamp_utc, local_date, latitude, longitude,
               place_id, place_name, city, preview_path
        FROM photos
        WHERE sha256 IN ({placeholders}) AND timestamp_utc IS NOT NULL;
    """, shas)

    if not photo_rows:
        return []

    # Map photos to visit segments
    visits_by_id: Dict[int, Dict[str, Any]] = {}

    for pr in photo_rows:
        sha = pr["sha256"]
        ts = pr["timestamp_utc"]
        score = sha_scores.get(sha, 0.0)
        p_lat = pr.get("latitude")
        p_lng = pr.get("longitude")
        p_pid = pr.get("place_id")

        # Candidate visit segments overlapping the photo timestamp (+/- 60s clock drift tolerance)
        candidate_segs = query_all("""
            SELECT id, date, start_ts, end_ts, start_time, end_time, duration_minutes,
                   place_name, place_address, place_id, category, latitude, longitude, city
            FROM segments
            WHERE segment_type = 'visit'
              AND ? >= (start_ts - 60) AND ? <= (end_ts + 60);
        """, (ts, ts))

        for seg in candidate_segs:
            s_lat = seg.get("latitude")
            s_lng = seg.get("longitude")
            s_pid = seg.get("place_id")
            s_start = seg["start_ts"]
            s_end = seg["end_ts"]

            # Validate spatio-temporal alignment
            matched = False
            if s_pid and p_pid and s_pid == p_pid:
                matched = True
            elif s_lat is not None and s_lng is not None and p_lat is not None and p_lng is not None:
                dist = _haversine_distance_m(s_lat, s_lng, p_lat, p_lng)
                if dist <= 250.0:
                    matched = True
            elif p_lat is None and not p_pid and (s_start <= ts <= s_end):
                matched = True

            if not matched:
                continue

            sid = seg["id"]
            if sid not in visits_by_id:
                visits_by_id[sid] = {
                    "id": sid,
                    "date": seg["date"],
                    "start_time": seg["start_time"],
                    "end_time": seg["end_time"],
                    "duration_minutes": seg["duration_minutes"],
                    "place_name": seg["place_name"] or "Visit",
                    "place_address": seg["place_address"],
                    "place_id": seg["place_id"],
                    "category": seg["category"] or "Other / POI",
                    "city": seg["city"],
                    "latitude": s_lat,
                    "longitude": s_lng,
                    "max_score": score,
                    "photos": [],
                }

            visits_by_id[sid]["photos"].append({
                "sha256": sha,
                "score": round(score, 3),
                "filename": pr["filename"],
                "preview_url": f"/api/photo?sha256={sha}",
                "timestamp_utc": ts,
            })
            if score > visits_by_id[sid]["max_score"]:
                visits_by_id[sid]["max_score"] = score

    # Format results
    results = list(visits_by_id.values())
    for r in results:
        # Sort photos within visit by score DESC
        r["photos"].sort(key=lambda x: x["score"], reverse=True)
        r["photo_count"] = len(r["photos"])
        r["top_photo"] = r["photos"][0]
        r["max_score"] = round(r["max_score"], 3)

    # Sort visits by max photo score DESC, then photo count DESC
    results.sort(key=lambda x: (x["max_score"], x["photo_count"]), reverse=True)
    return results[:limit]


def get_places_with_photos_for_concept(
    query: str,
    limit: int = 80,
    min_score: float = 0.60,
) -> Dict[str, Dict[str, Any]]:
    """
    Returns place_ids where photos matching query were taken,
    mapping place_id -> {"photo_count": N, "max_score": float, "top_photo": dict}.
    Enforces strict single-place attribution per photo to prevent duplicate cards.
    """
    clean_q = query.strip()
    if not clean_q:
        return {}

    # Check if query matches tagged people in photos
    person_check = query_one(
        "SELECT count(*) as cnt FROM photos WHERE people LIKE ? LIMIT 1;",
        (f"%{clean_q}%",)
    )
    if person_check and person_check.get("cnt", 0) > 0:
        sql = """
            SELECT s.id, s.place_id, s.place_name, count(p.sha256) as photo_count,
                   max(p.sha256) as top_sha, max(p.filename) as top_filename
            FROM (
                SELECT sha256, filename, timestamp_utc, place_id
                FROM photos
                WHERE people LIKE ? AND timestamp_utc IS NOT NULL
            ) p
            JOIN segments s ON p.timestamp_utc >= s.start_ts AND p.timestamp_utc <= s.end_ts
            WHERE s.segment_type = 'visit' AND s.place_id IS NOT NULL
            GROUP BY s.id;
        """
        p_rows = query_all(sql, (f"%{clean_q}%",))
        places_map: Dict[str, Dict[str, Any]] = {}
        for r in p_rows:
            pid = r["place_id"]
            if pid not in places_map:
                places_map[pid] = {
                    "place_id": pid,
                    "photo_count": 0,
                    "visit_count": 0,
                    "max_score": 1.0,
                    "top_photo": {
                        "sha256": r["top_sha"],
                        "filename": r.get("top_filename"),
                        "preview_url": f"/api/photo?sha256={r['top_sha']}",
                        "score": 1.0,
                    }
                }
            places_map[pid]["visit_count"] += 1
            places_map[pid]["photo_count"] += r["photo_count"]
        return places_map

    photos = query_photo_semantic_index(clean_q, limit=limit)
    if not photos:
        return {}

    sha_scores = {
        p["sha256"]: float(p.get("score", 0.0))
        for p in photos
        if p.get("sha256") and float(p.get("score", 0.0)) >= min_score
    }
    if not sha_scores:
        return {}

    shas = list(sha_scores.keys())
    placeholders = ",".join("?" for _ in shas)

    # Fetch photo metadata
    photo_rows = query_all(f"""
        SELECT sha256, filename, timestamp_utc, latitude, longitude, place_id
        FROM photos
        WHERE sha256 IN ({placeholders}) AND timestamp_utc IS NOT NULL;
    """, shas)

    places_map: Dict[str, Dict[str, Any]] = {}

    for pr in photo_rows:
        sha = pr["sha256"]
        ts = pr["timestamp_utc"]
        p_lat = pr.get("latitude")
        p_lng = pr.get("longitude")
        p_pid = pr.get("place_id")

        # Find overlapping visit segment
        segs = query_all("""
            SELECT id, place_id, latitude, longitude, start_ts, end_ts, duration_minutes
            FROM segments
            WHERE segment_type = 'visit' AND ? >= start_ts AND ? <= end_ts AND place_id IS NOT NULL;
        """, (ts, ts))

        assigned_pid = None
        if segs:
            best_seg = None
            best_dist = 999999.0
            for s in segs:
                s_pid = s["place_id"]
                s_lat = s.get("latitude")
                s_lng = s.get("longitude")
                if p_pid and s_pid == p_pid:
                    best_seg = s
                    break
                if p_lat is not None and p_lng is not None and s_lat is not None and s_lng is not None:
                    d = _haversine_distance_m(s_lat, s_lng, p_lat, p_lng)
                    if d < best_dist and d <= 500.0:
                        best_dist = d
                        best_seg = s
                elif best_seg is None:
                    best_seg = s
            if best_seg:
                assigned_pid = best_seg["place_id"]

        if not assigned_pid and p_pid:
            assigned_pid = p_pid

        if not assigned_pid:
            continue

        score = sha_scores[sha]
        if assigned_pid not in places_map:
            places_map[assigned_pid] = {
                "place_id": assigned_pid,
                "photo_count": 0,
                "max_score": score,
                "top_photo": {
                    "sha256": sha,
                    "filename": pr.get("filename"),
                    "preview_url": f"/api/photo?sha256={sha}",
                    "score": round(score, 3),
                }
            }
        places_map[assigned_pid]["photo_count"] += 1
        if score > places_map[assigned_pid]["max_score"]:
            places_map[assigned_pid]["max_score"] = score
            places_map[assigned_pid]["top_photo"] = {
                "sha256": sha,
                "filename": pr.get("filename"),
                "preview_url": f"/api/photo?sha256={sha}",
                "score": round(score, 3),
            }

    return places_map


