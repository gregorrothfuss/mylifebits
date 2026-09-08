"""
End-to-End HTTP Wire Integration Test Suite for Timeline Server.
Exercises the complete server pipeline (wire HTTP parsing, headers, routing, static files,
API dispatch, gzip compression, and error formatting) via TimelineViewerHandler.
Runs 100% deterministically and isolated without external socket dependencies.
"""

from __future__ import annotations

import gzip
import io
import json
import unittest
from typing import Any, Dict, Optional, Tuple

from server import TimelineViewerHandler


class MockSocket:
    """Simulates a TCP client socket communicating with BaseHTTPRequestHandler."""

    def __init__(self, raw_input: bytes):
        self.rfile = io.BytesIO(raw_input)
        self.wfile = io.BytesIO()

    def makefile(self, mode: str, *args: Any, **kwargs: Any) -> io.BytesIO:
        return self.rfile if "r" in mode else self.wfile

    def sendall(self, data: bytes) -> None:
        self.wfile.write(data)


class MockServer:
    """Minimal server stub for BaseHTTPRequestHandler initialization."""
    pass


class TestTimelineServerE2E(unittest.TestCase):
    """Full HTTP wire integration tests covering static assets, API endpoints, and data mutations."""

    def _execute_http(
        self,
        method: str,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        body: bytes = b"",
    ) -> Tuple[int, Dict[str, str], bytes, Any]:
        """
        Synthesizes an HTTP/1.1 wire request, executes TimelineViewerHandler,
        and parses status, headers, and decoded payload.
        """
        all_headers = {"Host": "localhost", "User-Agent": "TimelineE2ETest/1.0"}
        if headers:
            all_headers.update(headers)
        if body and "Content-Length" not in all_headers:
            all_headers["Content-Length"] = str(len(body))

        header_lines = [f"{k}: {v}" for k, v in all_headers.items()]
        raw_request = (
            f"{method} {path} HTTP/1.1\r\n"
            + "\r\n".join(header_lines)
            + "\r\n\r\n"
        ).encode("utf-8") + body

        sock = MockSocket(raw_request)
        # Suppress stderr log output from BaseHTTPRequestHandler during test execution
        import sys
        old_stderr = sys.stderr
        sys.stderr = io.StringIO()
        try:
            TimelineViewerHandler(sock, ("127.0.0.1", 54321), MockServer)
        finally:
            sys.stderr = old_stderr

        raw_output = sock.wfile.getvalue()
        if not raw_output:
            return 500, {}, b"", None

        # Parse HTTP wire response
        header_end = raw_output.find(b"\r\n\r\n")
        if header_end == -1:
            return 500, {}, b"", None

        head = raw_output[:header_end].decode("iso-8859-1")
        body_bytes = raw_output[header_end + 4 :]

        lines = head.split("\r\n")
        status_parts = lines[0].split(" ", 2)
        status_code = int(status_parts[1]) if len(status_parts) > 1 else 500

        resp_headers: Dict[str, str] = {}
        for h_line in lines[1:]:
            if ":" in h_line:
                hk, hv = h_line.split(":", 1)
                resp_headers[hk.strip().lower()] = hv.strip()

        # Decompress gzip if present
        if resp_headers.get("content-encoding") == "gzip":
            body_bytes = gzip.decompress(body_bytes)

        parsed_json = None
        if "application/json" in resp_headers.get("content-type", ""):
            try:
                parsed_json = json.loads(body_bytes.decode("utf-8"))
            except Exception:
                parsed_json = None

        return status_code, resp_headers, body_bytes, parsed_json

    def _get(self, path: str, headers: Optional[Dict[str, str]] = None) -> Tuple[int, Dict[str, str], Any]:
        status, resp_headers, _, parsed_json = self._execute_http("GET", path, headers)
        return status, resp_headers, parsed_json

    def _post(self, path: str, payload: Dict[str, Any]) -> Tuple[int, Dict[str, str], Any]:
        body = json.dumps(payload).encode("utf-8")
        status, resp_headers, _, parsed_json = self._execute_http(
            "POST",
            path,
            headers={"Content-Type": "application/json"},
            body=body,
        )
        return status, resp_headers, parsed_json

    # --- 1. Static Asset Serving Tests ---

    def test_01_static_root_serves_index_html(self) -> None:
        status, headers, body, _ = self._execute_http("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("content-type", ""))
        self.assertIn(b"Timeline", body)

    def test_02_static_app_js_direct(self) -> None:
        status, headers, body, _ = self._execute_http("GET", "/app.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", headers.get("content-type", ""))
        self.assertTrue(len(body) > 1000)

    def test_03_static_app_js_with_prefix(self) -> None:
        status, headers, body, _ = self._execute_http("GET", "/static/app.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", headers.get("content-type", ""))
        self.assertTrue(len(body) > 1000)

    def test_04_static_style_css(self) -> None:
        status, headers, body, _ = self._execute_http("GET", "/style.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", headers.get("content-type", ""))

    def test_05_favicon_204(self) -> None:
        status, _, _, _ = self._execute_http("GET", "/favicon.ico")
        self.assertEqual(status, 204)

    # --- 2. Live API Read Contract Tests ---

    def test_10_api_overview_contract(self) -> None:
        status, headers, data = self._get("/api/overview", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers.get("content-type", ""))
        self.assertEqual(data.get("status"), "SUCCESS")
        scorecard = data.get("scorecard", {})
        self.assertIn("total_segments", scorecard)
        self.assertIn("category_breakdown", scorecard)
        self.assertIn("top_cities", scorecard)
        self.assertIsInstance(scorecard["category_breakdown"], list)
        self.assertIsInstance(scorecard["top_cities"], list)

    def test_11_api_calendar_contract(self) -> None:
        status, _, data = self._get("/api/calendar?year=2024&month=10")
        self.assertEqual(status, 200)
        self.assertEqual(data.get("status"), "SUCCESS")
        self.assertIsInstance(data.get("days"), list)

    def test_12_api_calendar_range_contract(self) -> None:
        status, _, data = self._get("/api/calendar-range?start_date=2024-10-01&end_date=2024-10-03")
        self.assertEqual(status, 200)
        self.assertEqual(data.get("status"), "SUCCESS")
        days = data.get("days")
        self.assertIsInstance(days, dict)
        if "2024-10-01" in days:
            day_obj = days["2024-10-01"]
            self.assertIn("segments", day_obj)
            self.assertIn("gaps", day_obj)

    def test_13_api_places_contract(self) -> None:
        status, _, data = self._get("/api/places?limit=5")
        self.assertEqual(status, 200)
        self.assertEqual(data.get("status"), "SUCCESS")
        self.assertIn("total", data)
        self.assertIn("places", data)
        self.assertIn("categories", data)
        self.assertIn("cities", data)
        self.assertIsInstance(data["places"], list)

    def test_14_api_places_map_points_object_contract(self) -> None:
        status, _, data = self._get("/api/places/map-points?limit=10")
        self.assertEqual(status, 200)
        self.assertEqual(data.get("status"), "SUCCESS")
        points = data.get("points", [])
        self.assertIsInstance(points, list)
        if points:
            first_pt = points[0]
            self.assertIsInstance(first_pt, dict)
            self.assertIn("latitude", first_pt)
            self.assertIn("longitude", first_pt)
            self.assertIn("name", first_pt)

    def test_15_api_fixes_counts_contract(self) -> None:
        status, _, data = self._get("/api/fixes?status=PENDING")
        self.assertEqual(status, 200)
        self.assertEqual(data.get("status"), "SUCCESS")
        self.assertIn("fixes", data)
        self.assertIn("counts", data)
        counts = data["counts"]
        self.assertIn("pending", counts)
        self.assertIn("accepted", counts)
        self.assertIn("rejected", counts)
        self.assertIn("total", counts)

    def test_16_api_photo_proxy_endpoint(self) -> None:
        # Verify photo proxy returns 400 for empty url
        status, _, _ = self._get("/api/photo")
        self.assertEqual(status, 400)

        # Verify photo proxy returns 400 for invalid url
        status, _, _ = self._get("/api/photo?url=invalid_url")
        self.assertEqual(status, 400)

    # --- 3. Live API Write / Mutation Tests ---

    def test_20_segment_crud_lifecycle(self) -> None:
        # Create
        create_payload = {
            "date": "2099-01-01",
            "segment_type": "visit",
            "place_name": "E2E Test Venue",
            "place_address": "123 Test St",
            "category": "Food & Drink",
            "start_time": "2099-01-01T10:00:00",
            "end_time": "2099-01-01T11:00:00",
            "start_ts": 4070908800.0,
            "end_ts": 4070912400.0,
            "duration_minutes": 60.0,
            "latitude": 40.7128,
            "longitude": -74.0060,
        }
        status, _, res = self._post("/api/segments/create", create_payload)
        self.assertEqual(status, 200)
        self.assertEqual(res.get("status"), "SUCCESS")
        seg_id = res.get("id")
        self.assertIsNotNone(seg_id)

        # Update
        update_payload = {
            "id": seg_id,
            "place_name": "E2E Test Venue Updated",
            "category": "Shopping",
        }
        status, _, res = self._post("/api/segments/update", update_payload)
        self.assertEqual(status, 200)
        self.assertEqual(res.get("status"), "SUCCESS")

        # Delete
        delete_payload = {"id": seg_id}
        status, _, res = self._post("/api/segments/delete", delete_payload)
        self.assertEqual(status, 200)
        self.assertEqual(res.get("status"), "SUCCESS")

    def test_21_proposal_edit_and_apply_alias(self) -> None:
        # Test that both /api/fixes/edit-and-apply and /api/proposals/edit-and-apply exist
        status1, _, _ = self._post("/api/fixes/edit-and-apply", {})
        self.assertEqual(status1, 400)  # Valid route, 400 because missing proposal_id

        status2, _, _ = self._post("/api/proposals/edit-and-apply", {})
        self.assertEqual(status2, 400)  # Valid route, 400 because missing proposal_id


if __name__ == "__main__":
    unittest.main()
