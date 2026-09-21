"""
Photo Proxy API for Google User Content with local disk caching.
"""

from __future__ import annotations

import hashlib
import os
import re
import ssl
import time
import urllib.request
from pathlib import Path
from typing import Optional

from api.response import Response, binary_response, error_response
from api.router import Request, router

CACHE_DIR = Path.home() / ".gregor_mylifebits" / "photo_cache"
SSL_CTX = ssl._create_unverified_context()


@router.get("/api/photo")
def proxy_photo(req: Request) -> Response:
    """Proxies and caches remote photos."""
    raw_url = req.get_str("url")
    size = req.get_str("size", "400")

    if not raw_url or not raw_url.startswith("http"):
        return error_response("Missing or invalid 'url' parameter", status_code=400)

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
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
                    }
                )
                with urllib.request.urlopen(fetch_req, timeout=10, context=SSL_CTX) as resp:
                    data = resp.read()
                if data and len(data) > 100:
                    image_data = data
                    cache_path.write_bytes(data)
                    break
            except Exception as e:
                time.sleep(0.2 * (attempt + 1))

    if image_data and len(image_data) > 100:
        return binary_response(
            image_data,
            content_type="image/jpeg",
            status_code=200,
            headers={"Cache-Control": "public, max-age=31536000, immutable"}
        )

    return error_response("Failed to fetch image", status_code=404)
