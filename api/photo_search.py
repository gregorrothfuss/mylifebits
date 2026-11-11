"""
Photo Semantic Search Engine & Visit Matcher.

Supports multi-tier semantic search:
1. Thread-safe vectorized NumPy dot-product over local SQLite CLIP ViT-B-32 embeddings.
2. Optional configured remote photo search endpoint (`PHOTOS_SEARCH_URL`) with verified TLS.
3. Local FTS5 (`photos_fts`) OCR, place, people, and filename search fallback.
"""

from __future__ import annotations

import datetime
import ipaddress
import json
import logging
import math
import os
import socket
import ssl
import threading
import time
import urllib.parse
import urllib.request
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from api.db import build_fts_match_query, get_db_path, query_all, query_one

logger = logging.getLogger("photo_search")

# Thread-safe in-memory LRU cache for photo semantic queries: (query -> (timestamp, photos_list))
_CACHE_LOCK = threading.Lock()
_SEARCH_CACHE: OrderedDict[str, Tuple[float, List[Dict[str, Any]]]] = OrderedDict()
_CACHE_MAX_SIZE = 250
_CACHE_TTL_SECONDS = 3600  # 1 hour

_CLIP_LOCK = threading.Lock()
_CLIP_MODEL: Any = None
_CLIP_TOKENIZER: Any = None
_CLIP_INITIALIZED = False

_EMBED_CACHE_LOCK = threading.Lock()
_EMBED_MATRIX_CACHE: Dict[Tuple[str, str], Tuple[int, int, List[str], np.ndarray]] = {}


def _haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Computes great-circle distance between two GPS coordinates in meters."""
    r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def _get_local_clip_query_vector(query: str) -> Optional[np.ndarray]:
    """Encodes query text to a normalized float32 vector using OpenCLIP if installed."""
    global _CLIP_MODEL, _CLIP_TOKENIZER, _CLIP_INITIALIZED
    with _CLIP_LOCK:
        if _CLIP_INITIALIZED and _CLIP_MODEL is None:
            return None
        try:
            import open_clip
            import torch

            if _CLIP_MODEL is None:
                device = "cpu"
                model, _, _ = open_clip.create_model_and_transforms(
                    "ViT-B-32", pretrained="laion2b_s34b_b79k"
                )
                _CLIP_TOKENIZER = open_clip.get_tokenizer("ViT-B-32")
                _CLIP_MODEL = model.to(device).eval()
                _CLIP_INITIALIZED = True

            tokens = _CLIP_TOKENIZER([query])
            with torch.no_grad():
                feat = _CLIP_MODEL.encode_text(tokens)
                feat /= feat.norm(dim=-1, keepdim=True)
                arr = np.asarray(feat.squeeze(0).cpu().numpy(), dtype=np.float32)
                return arr
        except Exception:
            _CLIP_INITIALIZED = True
            _CLIP_MODEL = None
            return None


def _load_embedding_matrix(tbl_name: str, q_dim: int) -> Optional[Tuple[List[str], np.ndarray]]:
    """Loads or returns cached normalized float32 matrix of photo embeddings."""
    db_path = get_db_path()
    sig_row = query_one(
        f"SELECT COUNT(*) as cnt, COALESCE(MAX(rowid), 0) as max_rid FROM {tbl_name};"
    )
    if not sig_row or int(sig_row.get("cnt") or 0) == 0:
        return None

    cnt = int(sig_row["cnt"])
    max_rid = int(sig_row["max_rid"])
    cache_key = (db_path, tbl_name)

    with _EMBED_CACHE_LOCK:
        cached = _EMBED_MATRIX_CACHE.get(cache_key)
        if cached is not None and cached[0] == cnt and cached[1] == max_rid:
            if cached[3].shape[1] == q_dim:
                return cached[2], cached[3]

    rows = query_all(f"SELECT sha256, vector FROM {tbl_name};")
    if not rows:
        return None

    expected_bytes = q_dim * 4
    shas: List[str] = []
    vecs: List[np.ndarray] = []
    for r in rows:
        sha = r.get("sha256")
        blob = r.get("vector")
        if not sha or not isinstance(blob, (bytes, bytearray, memoryview)):
            continue
        if len(blob) != expected_bytes:
            continue
        vec = np.frombuffer(blob, dtype="<f4")
        shas.append(str(sha))
        vecs.append(vec)

    if not vecs:
        return None

    matrix = np.vstack(vecs).astype(np.float32, copy=False)
    with _EMBED_CACHE_LOCK:
        _EMBED_MATRIX_CACHE.clear()
        _EMBED_MATRIX_CACHE[cache_key] = (cnt, max_rid, shas, matrix)
    return shas, matrix


def _query_local_vector_index(query: str, limit: int = 60) -> List[Dict[str, Any]]:
    """Searches photo_embeddings in SQLite using vectorized NumPy matrix dot-product."""
    tbl_check = query_one(
        """
        SELECT name FROM sqlite_master
        WHERE type = 'table' AND name IN ('photo_embeddings', 'embeddings')
        LIMIT 1;
        """
    )
    if not tbl_check:
        return []

    tbl_name = str(tbl_check["name"])
    cnt_check = query_one(f"SELECT COUNT(*) as cnt FROM {tbl_name};")
    if not cnt_check or int(cnt_check.get("cnt") or 0) == 0:
        return []

    query_vec = _get_local_clip_query_vector(query)
    if query_vec is None or query_vec.ndim != 1:
        return []

    loaded = _load_embedding_matrix(tbl_name, int(query_vec.shape[0]))
    if loaded is None:
        return []

    shas, matrix = loaded
    scores = matrix @ query_vec
    valid_idx = np.flatnonzero(scores >= 0.40)
    if valid_idx.size == 0:
        return []

    valid_scores = scores[valid_idx]
    if valid_idx.size > limit:
        top_rel = np.argpartition(valid_scores, -limit)[-limit:]
        top_rel = top_rel[np.argsort(valid_scores[top_rel])[::-1]]
    else:
        top_rel = np.argsort(valid_scores)[::-1]

    return [
        {"sha256": shas[int(valid_idx[i])], "score": round(float(valid_scores[i]), 3)}
        for i in top_rel
    ]


def _query_local_text_fallback(query: str, limit: int = 60) -> List[Dict[str, Any]]:
    """Fallback search over photo OCR text, place names, people, and filename via FTS5."""
    fts_expr = build_fts_match_query(query)
    rows: List[Dict[str, Any]] = []
    if fts_expr:
        rows = query_all(
            """
            SELECT p.sha256, p.filename, p.ocr_text, p.people, p.place_name, p.local_date
            FROM photos_fts f
            JOIN photos p ON p.rowid = f.rowid
            WHERE photos_fts MATCH ?
            LIMIT ?;
            """,
            (fts_expr, limit),
        )

    if not rows:
        wild = f"%{query}%"
        rows = query_all(
            """
            SELECT sha256, filename, ocr_text, people, place_name, local_date
            FROM photos
            WHERE (ocr_text LIKE ? OR place_name LIKE ? OR people LIKE ? OR filename LIKE ?)
            LIMIT ?;
            """,
            (wild, wild, wild, wild, limit),
        )

    results: List[Dict[str, Any]] = []
    q_low = query.lower()
    for r in rows:
        score = 0.70
        ocr = (r.get("ocr_text") or "").lower()
        pname = (r.get("place_name") or "").lower()
        people = (r.get("people") or "").lower()

        if q_low in ocr:
            score = 0.88
        elif q_low in pname:
            score = 0.82
        elif q_low in people:
            score = 0.90

        results.append({
            "sha256": r["sha256"],
            "score": score,
            "filename": r["filename"],
            "formatted_date": r["local_date"],
        })
    return results


def _is_allowed_remote_search_url(base_url: str) -> bool:
    """Validates optional PHOTOS_SEARCH_URL to prevent unexpected scheme or link-local SSRF."""
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host.endswith(".local") or host in ("127.0.0.1", "::1", "localhost"):
        return True
    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_link_local or ip.is_multicast:
            return False
    return True


def query_photo_semantic_index(query: str, limit: int = 60) -> List[Dict[str, Any]]:
    """
    Multi-tier photo semantic search:
    1. Local vector embeddings index (CLIP ViT-B-32 in SQLite).
    2. Optional configured remote photo service (`PHOTOS_SEARCH_URL`).
    3. Local FTS5 / metadata search fallback.
    """
    clean_q = query.strip().lower()
    if not clean_q:
        return []

    now = time.time()
    with _CACHE_LOCK:
        cached_entry = _SEARCH_CACHE.get(clean_q)
        if cached_entry is not None:
            cached_ts, cached_res = cached_entry
            if now - cached_ts < _CACHE_TTL_SECONDS:
                _SEARCH_CACHE.move_to_end(clean_q)
                return list(cached_res[:limit])

    photos: List[Dict[str, Any]] = []

    # Tier 1: Local SQLite vector index
    try:
        photos = _query_local_vector_index(clean_q, limit=limit)
    except Exception as e:
        logger.debug("Local vector search error: %s", e)
        photos = []

    # Tier 2: Optional remote photo search service (strictly opt-in via PHOTOS_SEARCH_URL)
    if not photos:
        base_url = os.environ.get("PHOTOS_SEARCH_URL", "").strip()
        if base_url and _is_allowed_remote_search_url(base_url):
            sep = "&" if "?" in base_url else "?"
            url = f"{base_url}{sep}q={urllib.parse.quote(clean_q)}"
            allow_insecure = os.environ.get("PHOTOS_TLS_INSECURE", "").strip().lower() in (
                "1",
                "true",
                "yes",
            )
            ctx = (
                ssl._create_unverified_context()
                if allow_insecure
                else ssl.create_default_context()
            )
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "MyLifeBits-PhotoSearch/2.0",
                    "Accept": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=4, context=ctx) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    photos = data.get("results", [])
            except Exception as e:
                logger.debug("Remote photo search unreachable: %s", e)
                photos = []

    # Tier 3: Local FTS5 OCR & metadata fallback
    if not photos:
        try:
            photos = _query_local_text_fallback(clean_q, limit=limit)
        except Exception as e:
            logger.debug("Local text fallback search error: %s", e)
            photos = []

    with _CACHE_LOCK:
        if clean_q in _SEARCH_CACHE:
            del _SEARCH_CACHE[clean_q]
        elif len(_SEARCH_CACHE) >= _CACHE_MAX_SIZE:
            _SEARCH_CACHE.popitem(last=False)
        _SEARCH_CACHE[clean_q] = (now, photos)

    return list(photos[:limit])


def _candidate_dates_for_timestamps(photo_rows: List[Dict[str, Any]]) -> List[str]:
    """Builds a compact set of candidate YYYY-MM-DD dates (including +/-1 day TZ/overnight margin)."""
    dates: Set[str] = set()
    for pr in photo_rows:
        ts = pr.get("timestamp_utc")
        if ts is not None:
            dt = datetime.datetime.fromtimestamp(float(ts), tz=datetime.timezone.utc).date()
            dates.add((dt - datetime.timedelta(days=1)).isoformat())
            dates.add(dt.isoformat())
            dates.add((dt + datetime.timedelta(days=1)).isoformat())
        ld = pr.get("local_date")
        if isinstance(ld, str) and len(ld) == 10:
            dates.add(ld)
    return sorted(dates)


def search_visits_by_photo_semantics(
    query: str,
    limit: int = 25,
    min_score: float = 0.60,
) -> List[Dict[str, Any]]:
    """Performs semantic concept search across photos and maps matching photos to visits."""
    clean_q = query.strip()
    if not clean_q:
        return []

    photos = query_photo_semantic_index(clean_q, limit=60)
    if not photos:
        return []

    sha_scores = {
        p["sha256"]: float(p.get("score", 0.0))
        for p in photos
        if p.get("sha256") and float(p.get("score", 0.0)) >= min_score
    }
    if not sha_scores:
        return []

    shas = list(sha_scores.keys())
    placeholders = ",".join("?" for _ in shas)
    photo_rows = query_all(
        f"""
        SELECT sha256, filename, timestamp_utc, local_date, latitude, longitude,
               place_id, place_name, city, preview_path
        FROM photos
        WHERE sha256 IN ({placeholders}) AND timestamp_utc IS NOT NULL;
        """,
        shas,
    )
    if not photo_rows:
        return []

    cand_dates = _candidate_dates_for_timestamps(photo_rows)
    if not cand_dates:
        return []

    date_holders = ",".join("?" for _ in cand_dates)
    all_candidate_segs = query_all(
        f"""
        SELECT id, date, start_ts, end_ts, start_time, end_time, duration_minutes,
               place_name, place_address, place_id, category, latitude, longitude, city
        FROM segments
        WHERE segment_type = 'visit' AND date IN ({date_holders});
        """,
        cand_dates,
    )
    if not all_candidate_segs:
        return []

    visits_by_id: Dict[int, Dict[str, Any]] = {}

    for pr in photo_rows:
        sha = pr["sha256"]
        ts = float(pr["timestamp_utc"])
        score = sha_scores.get(sha, 0.0)
        p_lat = pr.get("latitude")
        p_lng = pr.get("longitude")
        p_pid = pr.get("place_id")

        for seg in all_candidate_segs:
            s_start = seg["start_ts"]
            s_end = seg["end_ts"]
            if not (s_start <= ts <= s_end):
                continue

            s_lat = seg.get("latitude")
            s_lng = seg.get("longitude")
            s_pid = seg.get("place_id")

            matched = False
            if s_pid and p_pid and s_pid == p_pid:
                matched = True
            elif s_lat is not None and s_lng is not None and p_lat is not None and p_lng is not None:
                if _haversine_distance_m(s_lat, s_lng, p_lat, p_lng) <= 250.0:
                    matched = True
            elif p_lat is None and not p_pid:
                matched = True

            if not matched:
                continue

            sid = int(seg["id"])
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
                "timestamp_utc": pr["timestamp_utc"],
            })
            if score > visits_by_id[sid]["max_score"]:
                visits_by_id[sid]["max_score"] = score

    results = list(visits_by_id.values())
    for r in results:
        r["photos"].sort(key=lambda x: x["score"], reverse=True)
        r["photo_count"] = len(r["photos"])
        r["top_photo"] = r["photos"][0]
        r["max_score"] = round(r["max_score"], 3)

    results.sort(key=lambda x: (x["max_score"], x["photo_count"]), reverse=True)
    return results[:limit]


def get_places_with_photos_for_concept(
    query: str,
    limit: int = 80,
    min_score: float = 0.60,
) -> Dict[str, Dict[str, Any]]:
    """Returns place_ids where photos matching query were taken."""
    clean_q = query.strip()
    if not clean_q:
        return {}

    fts_expr = build_fts_match_query(clean_q)
    wcards = (f"{clean_q}%", f"% {clean_q}%", f"%, {clean_q}%")
    person_hit = False
    if fts_expr:
        p_check = query_one(
            """
            SELECT 1 as hit
            FROM photos_fts f
            JOIN photos p ON p.rowid = f.rowid
            WHERE photos_fts MATCH ?
              AND (p.people LIKE ? OR p.people LIKE ? OR p.people LIKE ?)
            LIMIT 1;
            """,
            (f"people : ({fts_expr})", *wcards),
        )
        person_hit = bool(p_check)
    else:
        p_check = query_one(
            "SELECT 1 as hit FROM photos WHERE people LIKE ? OR people LIKE ? OR people LIKE ? LIMIT 1;",
            wcards,
        )
        person_hit = bool(p_check)

    if person_hit:
        if fts_expr:
            sql = """
                WITH matched_people_photos AS (
                    SELECT p.sha256, p.filename, p.timestamp_utc, p.face_count
                    FROM photos_fts f
                    JOIN photos p ON p.rowid = f.rowid
                    WHERE photos_fts MATCH ?
                      AND (p.people LIKE ? OR p.people LIKE ? OR p.people LIKE ?)
                      AND p.timestamp_utc IS NOT NULL
                ),
                ranked_photos AS (
                    SELECT s.place_id, s.id as segment_id, p.sha256, p.filename,
                           ROW_NUMBER() OVER (
                               PARTITION BY s.place_id
                               ORDER BY (CASE WHEN p.face_count > 0 THEN 0 ELSE 1 END),
                                        (CASE WHEN p.filename LIKE 'Screen%' OR p.filename LIKE 'Screenshot%' THEN 1 ELSE 0 END),
                                        p.timestamp_utc DESC
                           ) as rn
                    FROM matched_people_photos p
                    JOIN segments s ON p.timestamp_utc >= s.start_ts AND p.timestamp_utc <= s.end_ts
                    WHERE s.segment_type = 'visit' AND s.place_id IS NOT NULL
                )
                SELECT place_id, count(DISTINCT segment_id) as visit_count, count(*) as photo_count,
                       max(CASE WHEN rn = 1 THEN sha256 END) as top_sha,
                       max(CASE WHEN rn = 1 THEN filename END) as top_filename
                FROM ranked_photos
                GROUP BY place_id;
            """
            p_rows = query_all(sql, (f"people : ({fts_expr})", *wcards))
        else:
            sql = """
                WITH ranked_photos AS (
                    SELECT s.place_id, s.id as segment_id, p.sha256, p.filename,
                           ROW_NUMBER() OVER (
                               PARTITION BY s.place_id
                               ORDER BY (CASE WHEN p.face_count > 0 THEN 0 ELSE 1 END),
                                        (CASE WHEN p.filename LIKE 'Screen%' OR p.filename LIKE 'Screenshot%' THEN 1 ELSE 0 END),
                                        p.timestamp_utc DESC
                           ) as rn
                    FROM (
                        SELECT sha256, filename, timestamp_utc, face_count
                        FROM photos
                        WHERE (people LIKE ? OR people LIKE ? OR people LIKE ?) AND timestamp_utc IS NOT NULL
                    ) p
                    JOIN segments s ON p.timestamp_utc >= s.start_ts AND p.timestamp_utc <= s.end_ts
                    WHERE s.segment_type = 'visit' AND s.place_id IS NOT NULL
                )
                SELECT place_id, count(DISTINCT segment_id) as visit_count, count(*) as photo_count,
                       max(CASE WHEN rn = 1 THEN sha256 END) as top_sha,
                       max(CASE WHEN rn = 1 THEN filename END) as top_filename
                FROM ranked_photos
                GROUP BY place_id;
            """
            p_rows = query_all(sql, wcards)

        person_places_map: Dict[str, Dict[str, Any]] = {}
        for r in p_rows:
            pid = r["place_id"]
            top_sha = r["top_sha"]
            person_places_map[pid] = {
                "place_id": pid,
                "photo_count": r["photo_count"],
                "visit_count": r["visit_count"],
                "max_score": 1.0,
                "top_photo": {
                    "sha256": top_sha,
                    "filename": r.get("top_filename"),
                    "preview_url": f"/api/photo?sha256={top_sha}" if top_sha else None,
                    "score": 1.0,
                },
            }
        return person_places_map

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
    photo_rows = query_all(
        f"""
        SELECT sha256, filename, timestamp_utc, local_date, latitude, longitude, place_id
        FROM photos
        WHERE sha256 IN ({placeholders}) AND timestamp_utc IS NOT NULL;
        """,
        shas,
    )
    if not photo_rows:
        return {}

    cand_dates = _candidate_dates_for_timestamps(photo_rows)
    all_segs: List[Dict[str, Any]] = []
    if cand_dates:
        date_holders = ",".join("?" for _ in cand_dates)
        all_segs = query_all(
            f"""
            SELECT id, place_id, latitude, longitude, start_ts, end_ts, duration_minutes
            FROM segments
            WHERE segment_type = 'visit' AND place_id IS NOT NULL AND date IN ({date_holders});
            """,
            cand_dates,
        )

    places_map: Dict[str, Dict[str, Any]] = {}

    for pr in photo_rows:
        sha = pr["sha256"]
        ts = float(pr["timestamp_utc"])
        p_lat = pr.get("latitude")
        p_lng = pr.get("longitude")
        p_pid = pr.get("place_id")

        segs = [s for s in all_segs if s["start_ts"] <= ts <= s["end_ts"]]
        assigned_pid: Optional[str] = None
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
                assigned_pid = str(best_seg["place_id"])

        if not assigned_pid and p_pid:
            assigned_pid = str(p_pid)

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
                },
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
