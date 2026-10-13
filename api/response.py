"""
HTTP Response & Serialization Layer.
Provides typed response abstractions with automatic gzip compression and CORS headers.
"""

from __future__ import annotations

import gzip
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


@dataclass
class Response:
    """HTTP response container."""

    body: bytes
    status_code: int = 200
    content_type: str = "application/json; charset=utf-8"
    headers: Dict[str, str] = field(default_factory=dict)

    def write_to(self, handler: Any, accept_encoding: str = "") -> None:
        """Writes headers and payload directly to a BaseHTTPRequestHandler instance."""
        payload = self.body
        is_compressed = False

        if (
            "gzip" in accept_encoding
            and len(payload) > 512
            and not self.headers.get("Content-Encoding")
        ):
            payload = gzip.compress(payload, compresslevel=6)
            is_compressed = True

        handler.send_response(self.status_code)
        handler.send_header("Content-Type", self.content_type)
        handler.send_header("Content-Length", str(len(payload)))
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE")
        handler.send_header("Access-Control-Allow-Headers", "*")
        handler.send_header("Cache-Control", "no-cache, no-store, must-revalidate")

        if is_compressed:
            handler.send_header("Content-Encoding", "gzip")

        for k, v in self.headers.items():
            handler.send_header(k, v)

        handler.end_headers()
        handler.wfile.write(payload)


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
