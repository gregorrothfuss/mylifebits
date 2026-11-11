"""
High-Performance Local Multi-Threaded HTTP Server and REST API.
Serves the standalone Timeline Viewer UI and modular API routes.
"""

from __future__ import annotations

import http.server
import io
import os
import socketserver
import sys
import urllib.parse
from pathlib import Path
from typing import Any, BinaryIO, Set

import api
from api.response import error_response
from api.router import Request, is_allowed_origin
from api.routes.photos import find_preview_file, is_unsafe_identifier

STATIC_DIR = str(Path(__file__).resolve().parent / "static")
MAX_BODY_BYTES = 2 * 1024 * 1024  # 2 MiB hard request body limit

DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "style-src-elem 'self'; "
    "style-src-attr 'unsafe-inline'; "
    "font-src 'self'; "
    "img-src 'self' data: blob: https://*.google.com https://server.arcgisonline.com https://*.tile.openstreetmap.org https://tile.openstreetmap.org https://*.basemaps.cartocdn.com; "
    "connect-src 'self' https://*.google.com https://server.arcgisonline.com https://*.tile.openstreetmap.org https://tile.openstreetmap.org https://*.basemaps.cartocdn.com https://demotiles.maplibre.org https://tiles.openfreemap.org; "
    "worker-src 'self' blob:; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'self'"
)


class DaemonThreadingTCPServer(socketserver.ThreadingTCPServer):
    """Multi-threaded TCP server whose worker threads exit cleanly on shutdown."""

    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 128


class TimelineViewerHandler(http.server.SimpleHTTPRequestHandler):
    """Dispatches API requests to api.router and serves static web assets from static/."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._sent_header_names: Set[str] = set()
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def send_response(self, code: int, message: str | None = None) -> None:
        self._sent_header_names = set()
        super().send_response(code, message)

    def send_header(self, keyword: str, value: str) -> None:
        self._sent_header_names.add(keyword.lower())
        super().send_header(keyword, value)

    def _write_api_response(self, res: Any, method: str) -> None:
        accept_enc = self.headers.get("Accept-Encoding", "")
        origin = self.headers.get("Origin", "")
        host = self.headers.get("Host", "")
        if_none_match = self.headers.get("If-None-Match", "")
        res.write_to(
            self,
            accept_encoding=accept_enc,
            method=method,
            request_origin=origin,
            request_host=host,
            if_none_match=if_none_match,
        )

    def _dispatch_api(self, method: str) -> None:
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)

        raw_len = self.headers.get("Content-Length", "0")
        try:
            content_len = int(raw_len)
        except ValueError:
            self._write_api_response(error_response("Invalid Content-Length header", status_code=400), method)
            return

        if content_len < 0 or content_len > MAX_BODY_BYTES:
            self._write_api_response(
                error_response("Request payload exceeds 2 MiB limit", status_code=413),
                method,
            )
            return

        body = self.rfile.read(content_len) if content_len > 0 else b""
        headers = {k: v for k, v in self.headers.items()}
        req = Request(method=method, path=parsed.path, query_params=query, headers=headers, body=body)
        res = api.router.dispatch(req)
        self._write_api_response(res, method)

    def do_GET(self) -> None:
        if self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if self.path.startswith("/api/"):
            self._dispatch_api("GET")
        elif self.path.startswith("/previews/"):
            self._serve_preview(head_only=False)
        else:
            self._rewrite_static_path()
            super().do_GET()

    def do_HEAD(self) -> None:
        if self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if self.path.startswith("/api/"):
            self._dispatch_api("HEAD")
        elif self.path.startswith("/previews/"):
            self._serve_preview(head_only=True)
        else:
            self._rewrite_static_path()
            super().do_HEAD()

    def do_POST(self) -> None:
        if self.path.startswith("/api/"):
            self._dispatch_api("POST")
        else:
            self.send_error(405, "Method Not Allowed")

    def do_PUT(self) -> None:
        if self.path.startswith("/api/"):
            self._dispatch_api("PUT")
        else:
            self.send_error(405, "Method Not Allowed")

    def do_DELETE(self) -> None:
        if self.path.startswith("/api/"):
            self._dispatch_api("DELETE")
        else:
            self.send_error(405, "Method Not Allowed")

    def do_OPTIONS(self) -> None:
        origin = self.headers.get("Origin", "")
        host = self.headers.get("Host", "")
        self.send_response(204)
        if origin and is_allowed_origin(origin, host):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, PUT, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, If-None-Match")
            self.send_header("Vary", "Origin")
        self.end_headers()

    def _rewrite_static_path(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        clean_path = parsed_url.path
        if clean_path in ("/", "", "/studio", "/studio/", "/dashboard"):
            self.path = "/index.html"
        elif clean_path in ("/phone", "/phone/", "/vm", "/vm/"):
            self.path = "/phone.html"
        elif clean_path.startswith("/static/"):
            self.path = clean_path[len("/static") :]

    def send_head(self) -> BinaryIO | io.BytesIO | None:
        """Serves static assets with deterministic ETag / If-None-Match 304 support."""
        fs_path = Path(self.translate_path(self.path))
        try:
            resolved_static = Path(STATIC_DIR).resolve()
            resolved_target = fs_path.resolve()
            if not resolved_target.is_relative_to(resolved_static):
                self.send_error(403, "Forbidden")
                return None
        except OSError:
            self.send_error(404, "File not found")
            return None

        if fs_path.is_file():
            try:
                st = fs_path.stat()
                etag = f'"{st.st_mtime_ns:x}-{st.st_size:x}"'
                inm = self.headers.get("If-None-Match", "")
                if inm and etag in [c.strip().removeprefix("W/") for c in inm.split(",")]:
                    self.send_response(304)
                    self.send_header("ETag", etag)
                    self.end_headers()
                    return None

                ctype = self.guess_type(str(fs_path))
                f = open(fs_path, "rb")
                self.send_response(200)
                self.send_header("Content-type", ctype)
                self.send_header("Content-Length", str(st.st_size))
                self.send_header("ETag", etag)
                if self.path.startswith("/vendor/"):
                    self.send_header("Cache-Control", "public, max-age=86400")
                else:
                    self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                return f
            except OSError:
                self.send_error(404, "File not found")
                return None
        return super().send_head()

    def _serve_preview(self, head_only: bool = False) -> None:
        parsed_path = urllib.parse.urlparse(self.path).path
        rel = parsed_path.removeprefix("/previews/")
        if not rel or "/" in rel or is_unsafe_identifier(rel):
            self.send_error(400, "Invalid preview identifier")
            return

        file_path = find_preview_file(rel)
        if not file_path:
            self.send_error(404, "Preview not found")
            return

        try:
            data = file_path.read_bytes()
            self.send_response(200)
            mime = "image/webp" if file_path.suffix.lower() == ".webp" else "image/jpeg"
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
            self.end_headers()
            if not head_only:
                self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def end_headers(self) -> None:
        sent: Set[str] = getattr(self, "_sent_header_names", set())
        csp = os.environ.get("CSP_HEADER", DEFAULT_CSP)
        if "content-security-policy" not in sent and csp:
            self.send_header("Content-Security-Policy", csp)
        if "x-content-type-options" not in sent:
            self.send_header("X-Content-Type-Options", "nosniff")
        if "referrer-policy" not in sent:
            self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        if "cross-origin-resource-policy" not in sent:
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        if "x-frame-options" not in sent:
            self.send_header("X-Frame-Options", "SAMEORIGIN")
        if "permissions-policy" not in sent:
            self.send_header("Permissions-Policy", "camera=(), microphone=(), payment=(), usb=()")
        super().end_headers()


class ThreadedTimelineServer:
    """Multi-threaded web server wrapper bound to loopback by default."""

    def __init__(self, host: str | None = None, port: int = 8082) -> None:
        self.host = host or os.environ.get("HOST", "127.0.0.1")
        self.port = port
        self.server: DaemonThreadingTCPServer | None = None

    def start(self) -> None:
        from db import init_db

        init_db()
        public_url = os.environ.get("PUBLIC_URL", "https://mylifebits.local")
        self.server = DaemonThreadingTCPServer((self.host, self.port), TimelineViewerHandler)
        print("\n=======================================================")
        print("[*] Standalone Timeline Studio & Quality Engine")
        print(f"[*] Web UI: {public_url}")
        print("=======================================================\n")
        try:
            self.server.serve_forever()
        except KeyboardInterrupt:
            print("\n[*] Shutting down server.")
        finally:
            if self.server:
                self.server.server_close()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", sys.argv[1] if len(sys.argv) > 1 else 8082))
    server = ThreadedTimelineServer(port=port)
    server.start()
