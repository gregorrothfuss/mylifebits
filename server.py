"""
High-Performance Local Multi-Threaded HTTP Server and REST API.
Serves the standalone Timeline Viewer UI and modular API routes.
"""

from __future__ import annotations

import http.server
import os
import socketserver
import urllib.parse
from typing import Any

import api
from api.router import Request

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


class TimelineViewerHandler(http.server.SimpleHTTPRequestHandler):
    """Dispatches API requests to api.router and serves static web assets from static/."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def _dispatch_api(self, method: str) -> None:
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)

        body = b""
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len > 0:
            body = self.rfile.read(content_len)

        headers = {k: v for k, v in self.headers.items()}
        req = Request(method=method, path=parsed.path, query_params=query, headers=headers, body=body)

        res = api.router.dispatch(req)
        accept_enc = self.headers.get("Accept-Encoding", "")
        res.write_to(self, accept_encoding=accept_enc)

    def do_GET(self) -> None:
        if self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if self.path.startswith("/api/"):
            self._dispatch_api("GET")
        else:
            if self.path in ("/", ""):
                self.path = "/index.html"
            elif self.path.startswith("/static/"):
                self.path = self.path[len("/static"):]
            super().do_GET()

    def do_POST(self) -> None:
        if self.path.startswith("/api/"):
            self._dispatch_api("POST")
        else:
            self.send_error(404, "File not found")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()


class ThreadedTimelineServer:
    """Multi-threaded web server wrapper."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        self.host = host
        self.port = port
        self.server: socketserver.ThreadingTCPServer | None = None

    def start(self) -> None:
        socketserver.TCPServer.allow_reuse_address = True
        self.server = socketserver.ThreadingTCPServer((self.host, self.port), TimelineViewerHandler)
        print(f"\n=======================================================")
        print(f"[*] Standalone Timeline Studio & Quality Engine (Clean V2)")
        print(f"[*] Local UI: http://localhost:{self.port}")
        print(f"=======================================================\n")
        try:
            self.server.serve_forever()
        except KeyboardInterrupt:
            print("\n[*] Shutting down server.")
        finally:
            if self.server:
                self.server.server_close()


if __name__ == "__main__":
    server = ThreadedTimelineServer(port=8080)
    server.start()
