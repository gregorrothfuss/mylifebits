"""
Lightweight, Typed HTTP Router & Request Dispatcher.
Dispatches requests to registered domain route handlers with strict parameter parsing,
same-origin mutation guards, and structured error handling.
"""

from __future__ import annotations

import json
import logging
import os
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple

from api.response import Response, error_response

logger = logging.getLogger("timeline.api")

_DEFAULT_ALLOWED_ORIGINS: Tuple[str, ...] = (
    "https://mylifebits.local",
    "http://mylifebits.local",
)


def is_allowed_origin(origin: str, host_header: str = "") -> bool:
    """Checks whether an Origin header matches configured same-origin domains."""
    clean_origin = (origin or "").strip().rstrip("/")
    if not clean_origin:
        return False

    allowed = set(_DEFAULT_ALLOWED_ORIGINS)
    extra = os.environ.get("ALLOWED_ORIGINS", "").strip()
    if extra:
        for item in extra.split(","):
            if item.strip():
                allowed.add(item.strip().rstrip("/"))

    clean_host = (host_header or "").strip()
    if clean_host:
        allowed.add(f"https://{clean_host}")
        allowed.add(f"http://{clean_host}")

    return clean_origin in allowed


class Request:
    """Encapsulates an incoming HTTP request."""

    def __init__(
        self,
        method: str,
        path: str,
        query_params: Dict[str, List[str]],
        headers: Dict[str, str],
        body: bytes = b"",
    ) -> None:
        self.method = method.upper()
        self.path = path
        self.query_params = query_params
        self.headers = headers
        self._headers_lower: Dict[str, str] = {k.lower(): v for k, v in headers.items()}
        self.raw_body = body
        self._parsed_json: Optional[Dict[str, Any]] = None

    def get_header(self, name: str, default: str = "") -> str:
        """Retrieves an HTTP header case-insensitively."""
        return self._headers_lower.get(name.lower(), default)

    def _first_param(self, key: str) -> Optional[str]:
        vals = self.query_params.get(key)
        if not vals:
            return None
        first = vals[0]
        return str(first) if first is not None else None

    def get_str(self, key: str, default: str = "") -> str:
        """Retrieves a string query parameter."""
        val = self._first_param(key)
        return val.strip() if val is not None else default

    def get_int(self, key: str, default: int = 0) -> int:
        """Retrieves an integer query parameter."""
        val = self._first_param(key)
        if val is None:
            return default
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        """Retrieves a float query parameter."""
        val = self._first_param(key)
        if val is None:
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        """Retrieves a boolean query parameter."""
        val = self._first_param(key)
        if val is None:
            return default
        return val.strip().lower() in ("1", "true", "yes", "on")

    def json(self) -> Dict[str, Any]:
        """Parses the request body as a JSON object."""
        if self._parsed_json is not None:
            return self._parsed_json
        if not self.raw_body:
            self._parsed_json = {}
            return self._parsed_json
        try:
            parsed = json.loads(self.raw_body.decode("utf-8"))
            if not isinstance(parsed, dict):
                raise ValueError("JSON root must be an object")
            self._parsed_json = parsed
            return self._parsed_json
        except Exception as e:
            raise ValueError(f"Invalid JSON payload: {e}") from e


RouteHandler = Callable[[Request], Response]


class Router:
    """Simple, high-performance route registry."""

    def __init__(self) -> None:
        self._routes: Dict[Tuple[str, str], RouteHandler] = {}

    def get(self, path: str) -> Callable[[RouteHandler], RouteHandler]:
        return self.route("GET", path)

    def post(self, path: str) -> Callable[[RouteHandler], RouteHandler]:
        return self.route("POST", path)

    def put(self, path: str) -> Callable[[RouteHandler], RouteHandler]:
        return self.route("PUT", path)

    def delete(self, path: str) -> Callable[[RouteHandler], RouteHandler]:
        return self.route("DELETE", path)

    def route(self, method: str, path: str) -> Callable[[RouteHandler], RouteHandler]:
        def decorator(handler: RouteHandler) -> RouteHandler:
            self._routes[(method.upper(), path)] = handler
            return handler

        return decorator

    def dispatch(self, req: Request) -> Response:
        """Dispatches an incoming request to the matching route handler."""
        if req.method == "OPTIONS":
            return Response(body=b"", status_code=204)

        if req.method in ("POST", "PUT", "DELETE", "PATCH"):
            sec_fetch_site = req.get_header("sec-fetch-site").strip().lower()
            if sec_fetch_site and sec_fetch_site not in ("same-origin", "none"):
                return error_response(
                    "Cross-site state mutation forbidden",
                    status_code=403,
                )
            origin = req.get_header("origin").strip()
            if origin and not is_allowed_origin(origin, req.get_header("host")):
                return error_response(
                    "Cross-origin state mutation forbidden",
                    status_code=403,
                )

        lookup_method = "GET" if req.method == "HEAD" else req.method
        handler = self._routes.get((lookup_method, req.path))
        if not handler:
            return error_response(
                f"Endpoint not found: {req.method} {req.path}",
                status_code=404,
            )

        try:
            return handler(req)
        except ValueError as ve:
            return error_response(str(ve), status_code=400)
        except Exception as e:
            logger.error(
                "Unhandled error in %s %s: %s\n%s",
                req.method,
                req.path,
                e,
                traceback.format_exc(),
            )
            return error_response(
                f"Internal server error: {e}",
                status_code=500,
            )


router = Router()
