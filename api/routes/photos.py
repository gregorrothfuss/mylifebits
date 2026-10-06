"""
Photo Proxy and Index API with local disk caching and gregor_cos photo vault integration.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from api.db import query_all, query_one
from api.response import Response, binary_response, error_response, json_response
from api.router import Request, router

CACHE_DIR = Path(os.environ.get("PHOTO_CACHE_DIR", str(Path.home() / ".mylifebits" / "photo_cache")))
SSL_CTX = ssl._create_unverified_context()

# Candidate directories where local photo previews reside
def _get_previews_search_dirs() -> List[Path]:
    dirs = []
    env_dir = os.environ.get("PREVIEWS_DIR")
    if env_dir:
        dirs.append(Path(env_dir))
    dirs.extend([
        Path(__file__).resolve().parent.parent.parent / "previews",
        Path.home() / "photos" / "previews",
        Path.home() / "projects" / "photos_vault" / "previews",
    ])
    return dirs

PREVIEWS_SEARCH_DIRS = _get_previews_search_dirs()


def find_preview_file(identifier: str) -> Optional[Path]:
    """Finds a WebP or JPEG preview file by sha256 or filename."""
    if not identifier:
        return None

    clean_id = identifier.strip().replace("previews/", "").replace("/previews/", "")
    # Check for direct file or sha256
    m_sha = re.search(r"([0-9a-fA-F]{64})", clean_id)
    candidates = []
    if m_sha:
        sha = m_sha.group(1).lower()
        candidates.extend([f"{sha}.webp", f"{sha}.jpg", f"{sha}.jpeg", sha])
    candidates.append(clean_id)
    if not clean_id.endswith(".webp") and not clean_id.endswith(".jpg"):
        candidates.append(f"{clean_id}.webp")

    for base_dir in PREVIEWS_SEARCH_DIRS:
        if not base_dir.exists():
            continue
        for cand in candidates:
            p = base_dir / cand
            if p.is_file() and p.stat().st_size > 0:
                return p

    return None


@router.get("/api/photo")
def proxy_photo(req: Request) -> Response:
    """
    Proxies and caches remote photos, and serves local previews from gregor_cos.
    Supports ?sha256=<hash> or ?url=<preview_path_or_url>.
    """
    req_sha = req.get_str("sha256")
    raw_url = req.get_str("url")
    size = req.get_str("size", "400")

    if not req_sha and raw_url and "sha256=" in raw_url:
        try:
            parsed = urllib.parse.urlparse(raw_url)
            qs = urllib.parse.parse_qs(parsed.query)
            if "sha256" in qs and qs["sha256"]:
                req_sha = qs["sha256"][0]
        except Exception:
            pass

    # 1. Check local gregor_cos previews via direct sha256 or preview URL
    local_ident = req_sha or raw_url
    if local_ident and not local_ident.startswith("http"):
        local_path = find_preview_file(local_ident)
        if not local_path and req_sha:
            # Fallback to database preview_path or filename mapping
            p_row = query_one("SELECT preview_path, filename FROM photos WHERE sha256 = ? LIMIT 1;", (req_sha,))
            if p_row:
                if p_row.get("preview_path"):
                    local_path = find_preview_file(p_row["preview_path"])
                if not local_path and p_row.get("filename"):
                    local_path = find_preview_file(p_row["filename"])
        if not local_path and not req_sha and local_ident:
            p_row = query_one("SELECT preview_path FROM photos WHERE filename = ? OR preview_path = ? LIMIT 1;", (local_ident, local_ident))
            if p_row and p_row.get("preview_path"):
                local_path = find_preview_file(p_row["preview_path"])

        if local_path:
            try:
                data = local_path.read_bytes()
                mime = "image/webp" if local_path.suffix.lower() == ".webp" else "image/jpeg"
                return binary_response(
                    data,
                    content_type=mime,
                    status_code=200,
                    headers={
                        "Cache-Control": "public, max-age=31536000, immutable",
                        "Access-Control-Allow-Origin": "*",
                    },
                )
            except Exception:
                pass

    # 2. Remote photo proxying (Google User Content)
    if not raw_url or not raw_url.startswith("http"):
        return error_response("Missing or invalid 'url' or 'sha256' parameter", status_code=400)

    target_url = raw_url
    if size in ("orig", "0"):
        target_url = re.sub(r"=[a-zA-Z0-9_\-]+$", "=s0", raw_url)
        if not target_url.endswith("=s0") and "=" not in target_url.split("/")[-1]:
            target_url += "=s0"
    elif size.isdigit():
        s_val = int(size)
        target_url = re.sub(r"=[a-zA-Z0-9_\-]+$", f"=w{s_val}-h{s_val}-n-k", raw_url)
        if "=" not in target_url.split("/")[-1]:
            target_url += f"=w{s_val}-h{s_val}-n-k"

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    url_hash = hashlib.sha256(target_url.encode("utf-8")).hexdigest()
    cache_path = CACHE_DIR / f"{url_hash}.jpg"

    image_data: Optional[bytes] = None
    if cache_path.exists() and cache_path.stat().st_size > 100:
        try:
            image_data = cache_path.read_bytes()
        except Exception:
            image_data = None

    if not image_data:
        for attempt in range(3):
            try:
                fetch_req = urllib.request.Request(
                    target_url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                        ),
                        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                    },
                )
                with urllib.request.urlopen(fetch_req, timeout=10, context=SSL_CTX) as resp:
                    data = resp.read()
                if data and len(data) > 100:
                    image_data = data
                    cache_path.write_bytes(data)
                    break
            except Exception:
                time.sleep(0.2 * (attempt + 1))

    if image_data and len(image_data) > 100:
        return binary_response(
            image_data,
            content_type="image/jpeg",
            status_code=200,
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    return error_response("Failed to fetch image", status_code=404)


@router.get("/api/photos")
def get_photos(req: Request) -> Response:
    """
    Returns paginated photos filtered by date, place_id, or bounding timestamps.
    """
    date_str = req.get_str("date")
    place_id = req.get_str("place_id")
    q = req.get_str("q")
    start_ts = req.get_float("start_ts", 0.0)
    end_ts = req.get_float("end_ts", 0.0)
    limit = min(500, max(1, req.get_int("limit", 100)))
    offset = max(0, req.get_int("offset", 0))

    where: List[str] = ["1=1"]
    params: List[Any] = []

    if date_str:
        where.append("local_date = ?")
        params.append(date_str)

    if place_id:
        where.append("place_id = ?")
        params.append(place_id)

    if start_ts > 0:
        where.append("timestamp_utc >= ?")
        params.append(int(start_ts))

    if end_ts > 0:
        where.append("timestamp_utc <= ?")
        params.append(int(end_ts))

    if q:
        where.append("(place_name LIKE ? OR address LIKE ? OR filename LIKE ?)")
        wild = f"%{q}%"
        params.extend([wild, wild, wild])

    where_sql = "WHERE " + " AND ".join(where)

    total_row = query_one(f"SELECT COUNT(*) as cnt FROM photos {where_sql};", params)
    total = total_row["cnt"] if total_row else 0

    sql = f"""
        SELECT sha256, filename, preview_path, timestamp_utc, timezone_offset,
               local_date, latitude, longitude, place_id, place_name, address, city, country, people, face_count
        FROM photos
        {where_sql}
        ORDER BY timestamp_utc ASC
        LIMIT ? OFFSET ?;
    """
    rows = query_all(sql, params + [limit, offset])

    for r in rows:
        r["preview_url"] = f"/api/photo?sha256={r['sha256']}"
        raw_p = r.get("people")
        if isinstance(raw_p, str) and raw_p.strip():
            try:
                r["people"] = json.loads(raw_p)
            except Exception:
                r["people"] = [raw_p]
        elif not isinstance(raw_p, list):
            r["people"] = []

    return json_response({
        "status": "SUCCESS",
        "count": len(rows),
        "total": total,
        "limit": limit,
        "offset": offset,
        "photos": rows,
    })
