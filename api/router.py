"""
Lightweight, Typed HTTP Router & Request Dispatcher.
Dispatches requests to registered domain route handlers with strict parameter parsing and error handling.
"""

from __future__ import annotations

import json
import logging
import traceback
import urllib.parse
from typing import Any, Callable, Dict, List, Optional

from api.response import Response, error_response, json_response

logger = logging.getLogger("timeline.api")


class Request:
    """Encapsulates an incoming HTTP request."""

    def __init__(
        self,
        method: str,
        path: str,
        query_params: Dict[str, List[str]],
        headers: Dict[str, str],
        body: bytes = b"",
    ):
        self.method = method.upper()
        self.path = path
        self.query_params = query_params
        self.headers = headers
        self.raw_body = body
        self._parsed_json: Optional[Dict[str, Any]] = None

    def get_str(self, key: str, default: str = "") -> str:
        """Retrieves a string query parameter."""
        val = self.query_params.get(key)
        if isinstance(val, (list, tuple)):
            val = val[0] if val else None
        return str(val).strip() if val is not None else default

    def get_int(self, key: str, default: int = 0) -> int:
        """Retrieves an integer query parameter."""
        val = self.query_params.get(key)
        if isinstance(val, (list, tuple)):
            val = val[0] if val else None
        if val is None:
            return default
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        """Retrieves a float query parameter."""
        val = self.query_params.get(key)
        if isinstance(val, (list, tuple)):
            val = val[0] if val else None
        if val is None:
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        """Retrieves a boolean query parameter."""
        val = self.query_params.get(key, [None])[0]
        if val is None:
            return default
        return val.lower() in ("1", "true", "yes", "on")

    def json(self) -> Dict[str, Any]:
        """Parses the request body as JSON."""
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
        self._routes: Dict[tuple[str, str], RouteHandler] = {}

    def get(self, path: str) -> Callable[[RouteHandler], RouteHandler]:
        return self.route("GET", path)

    def post(self, path: str) -> Callable[[RouteHandler], RouteHandler]:
        return self.route("POST", path)

    def route(self, method: str, path: str) -> Callable[[RouteHandler], RouteHandler]:
        def decorator(handler: RouteHandler) -> RouteHandler:
            self._routes[(method.upper(), path)] = handler
            return handler

        return decorator

    def dispatch(self, req: Request) -> Response:
        """Dispatches an incoming request to the matching route handler."""
        if req.method == "OPTIONS":
            return Response(body=b"", status_code=204)

        handler = self._routes.get((req.method, req.path))
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
