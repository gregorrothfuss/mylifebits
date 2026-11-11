"""
HTTP Response & Serialization Layer.
Provides typed response abstractions with ETag revalidation, gzip compression, and same-origin CORS.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, Optional


class JSONEncoder(json.JSONEncoder):
    """Custom JSON encoder handling datetimes and common types."""

    def default(self, o: Any) -> Any:
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        if hasattr(o, "__dict__"):
            return o.__dict__
        return super().default(o)


def _etag_matches(if_none_match: str, etag: str) -> bool:
    if not if_none_match or not etag:
        return False
    candidates = [item.strip() for item in if_none_match.split(",")]
    if "*" in candidates:
        return True
    clean_etag = etag.removeprefix("W/")
    for cand in candidates:
        if cand.removeprefix("W/") == clean_etag:
            return True
    return False


@dataclass
class Response:
    """HTTP response container."""

    body: bytes
    status_code: int = 200
    content_type: str = "application/json; charset=utf-8"
    headers: Dict[str, str] = field(default_factory=dict)

    def write_to(
        self,
        handler: Any,
        accept_encoding: str = "",
        method: str = "GET",
        request_origin: str = "",
        request_host: str = "",
        if_none_match: str = "",
    ) -> None:
        """Writes headers and payload directly to a BaseHTTPRequestHandler instance."""
        from api.router import is_allowed_origin

        explicit_lower = {k.lower(): v for k, v in self.headers.items()}
        etag = explicit_lower.get("etag", "")
        if not etag and method in ("GET", "HEAD") and self.status_code == 200:
            digest = hashlib.sha256(self.body).hexdigest()[:32]
            etag = f'"{digest}"'

        cache_control = explicit_lower.get("cache-control", "no-cache")

        if method in ("GET", "HEAD") and self.status_code == 200 and _etag_matches(if_none_match, etag):
            handler.send_response(304)
            if etag:
                handler.send_header("ETag", etag)
            handler.send_header("Cache-Control", cache_control)
            if request_origin and is_allowed_origin(request_origin, request_host):
                handler.send_header("Access-Control-Allow-Origin", request_origin)
                handler.send_header("Vary", "Origin")
            for k, v in self.headers.items():
                if k.lower() not in ("etag", "cache-control", "content-length", "content-type"):
                    handler.send_header(k, v)
            handler.end_headers()
            return

        payload = self.body
        is_compressed = False

        if (
            "gzip" in accept_encoding
            and len(payload) > 512
            and "content-encoding" not in explicit_lower
        ):
            payload = gzip.compress(payload, compresslevel=6)
            is_compressed = True

        handler.send_response(self.status_code)
        handler.send_header("Content-Type", self.content_type)
        handler.send_header("Content-Length", str(len(payload)))
        handler.send_header("Cache-Control", cache_control)
        if etag and "etag" not in explicit_lower:
            handler.send_header("ETag", etag)

        if request_origin and is_allowed_origin(request_origin, request_host):
            handler.send_header("Access-Control-Allow-Origin", request_origin)
            handler.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, PUT, DELETE, OPTIONS")
            handler.send_header("Access-Control-Allow-Headers", "Content-Type, If-None-Match")
            handler.send_header("Vary", "Origin, Accept-Encoding")
        elif is_compressed:
            handler.send_header("Vary", "Accept-Encoding")

        if is_compressed:
            handler.send_header("Content-Encoding", "gzip")

        for k, v in self.headers.items():
            if k.lower() in ("cache-control", "content-type", "content-length"):
                continue
            handler.send_header(k, v)

        try:
            handler.end_headers()
            if method != "HEAD":
                handler.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass


def json_response(
    data: Any,
    status_code: int = 200,
    headers: Optional[Dict[str, str]] = None,
) -> Response:
    """Helper to construct a JSON response."""
    body_str = json.dumps(data, cls=JSONEncoder, separators=(",", ":"))
    return Response(
        body=body_str.encode("utf-8"),
        status_code=status_code,
        content_type="application/json; charset=utf-8",
        headers=headers or {},
    )


def error_response(
    message: str,
    status_code: int = 400,
    details: Optional[Dict[str, Any]] = None,
) -> Response:
    """Standardized error response."""
    payload: Dict[str, Any] = {"status": "ERROR", "error": message}
    if details:
        payload["details"] = details
    return json_response(payload, status_code=status_code)


def binary_response(
    data: bytes,
    content_type: str,
    status_code: int = 200,
    headers: Optional[Dict[str, str]] = None,
) -> Response:
    """Helper to construct a binary/media response."""
    return Response(
        body=data,
        status_code=status_code,
        content_type=content_type,
        headers=headers or {},
    )
