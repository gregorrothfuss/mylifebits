"""
End-to-End HTTP Wire Integration Test Suite for Timeline Server.
Exercises the complete server pipeline (wire HTTP parsing, headers, routing, static files,
API dispatch, gzip compression, and error formatting) via TimelineViewerHandler.
Runs 100% deterministically and isolated without external socket dependencies.
"""

from __future__ import annotations

import contextlib
import gzip
import io
import json
import os
import unittest
from typing import Any, Dict, Optional, Tuple

from server import TimelineViewerHandler
from tests.hermetic_fixture import hermetic_db_environment, write_verification_artifact


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

    _hermetic_stack: Optional[contextlib.ExitStack] = None
    _executed_requests: int = 0

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls._executed_requests = 0
        if "mylifebits_hermetic_" not in os.environ.get("TIMELINE_DB_PATH", ""):
            cls._hermetic_stack = contextlib.ExitStack()
            cls._hermetic_stack.enter_context(hermetic_db_environment())

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            write_verification_artifact(
                "test_e2e_server",
                {
                    "db_name": os.path.basename(os.environ.get("TIMELINE_DB_PATH", "")),
                    "hermetic": "mylifebits_hermetic_" in os.environ.get("TIMELINE_DB_PATH", ""),
                    "wire_requests_executed": cls._executed_requests,
                },
            )
        finally:
            if cls._hermetic_stack is not None:
                cls._hermetic_stack.close()
                cls._hermetic_stack = None
            super().tearDownClass()

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
        type(self)._executed_requests += 1
        all_headers = {
            "Host": "mylifebits.local",
            "Origin": "https://mylifebits.local",
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": "TimelineE2ETest/1.0",
        }
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
        self.assertIn(b"global-search-input", body)
        self.assertNotIn(b"<title>Pixel 8 VM", body)

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

    # --- 4. HTTP Security Hardening, ETag Revalidation & KML Export E2E Tests ---

    def test_22_security_headers_and_bfcache_safe_cache_control(self) -> None:
        status, headers, _, _ = self._execute_http("GET", "/")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(headers.get("cross-origin-resource-policy"), "same-origin")
        self.assertEqual(headers.get("x-frame-options"), "SAMEORIGIN")
        self.assertIn("default-src 'self'", headers.get("content-security-policy", ""))
        self.assertEqual(headers.get("cache-control"), "no-cache")
        self.assertNotIn("no-store", headers.get("cache-control", ""))
        self.assertNotEqual(headers.get("access-control-allow-origin"), "*")

    def test_23_etag_conditional_304_on_static_and_api(self) -> None:
        status1, headers1, _, _ = self._execute_http("GET", "/")
        self.assertEqual(status1, 200)
        static_etag = headers1.get("etag")
        assert static_etag is not None

        status2, _, body2, _ = self._execute_http("GET", "/", headers={"If-None-Match": static_etag})
        self.assertEqual(status2, 304)
        self.assertEqual(body2, b"")

        api_s1, api_h1, _ = self._get("/api/overview")
        self.assertEqual(api_s1, 200)
        api_etag = api_h1.get("etag")
        assert api_etag is not None

        api_s2, _, api_body2, _ = self._execute_http(
            "GET", "/api/overview", headers={"If-None-Match": api_etag}
        )
        self.assertEqual(api_s2, 304)
        self.assertEqual(api_body2, b"")

    def test_24_photo_and_preview_path_traversal_blocked(self) -> None:
        status1, _, _ = self._get("/api/photo?url=../../timeline_viewer.db")
        self.assertEqual(status1, 400)

        status2, _, _ = self._get("/api/photo?sha256=..%2F..%2Ftimeline_viewer.db")
        self.assertEqual(status2, 400)

        status3, _, _, _ = self._execute_http("GET", "/previews/..%2F..%2Ftimeline_viewer.db")
        self.assertIn(status3, (400, 403, 404))

    def test_25_photo_proxy_ssrf_blocked(self) -> None:
        status1, _, _ = self._get("/api/photo?url=https://127.0.0.1/secret.jpg")
        self.assertEqual(status1, 403)

        status2, _, _ = self._get("/api/photo?url=https://evil.example/photo.jpg")
        self.assertEqual(status2, 403)

    def test_26_cross_site_mutation_blocked(self) -> None:
        body = json.dumps({"id": 1}).encode("utf-8")
        status_sfs, _, _, _ = self._execute_http(
            "POST",
            "/api/segments/delete",
            headers={
                "Content-Type": "application/json",
                "Sec-Fetch-Site": "cross-site",
                "Origin": "https://evil.example",
            },
            body=body,
        )
        self.assertEqual(status_sfs, 403)

        status_origin, _, _, _ = self._execute_http(
            "POST",
            "/api/segments/delete",
            headers={
                "Content-Type": "application/json",
                "Sec-Fetch-Site": "",
                "Origin": "https://evil.example",
            },
            body=body,
        )
        self.assertEqual(status_origin, 403)

    def test_27_oversized_body_rejected_413(self) -> None:
        status, _, _, data = self._execute_http(
            "POST",
            "/api/segments/create",
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(3 * 1024 * 1024),
            },
            body=b"{}",
        )
        self.assertEqual(status, 413)
        self.assertEqual(data.get("status"), "ERROR")

    def test_28_device_adb_shell_metacharacter_rejected(self) -> None:
        status, _, data = self._post("/api/device/keyboard", {"text": "hello; rm -rf /"})
        self.assertEqual(status, 400)
        self.assertEqual(data.get("status"), "ERROR")

    def test_29_place_visits_deserializes_review_photos(self) -> None:
        status, _, data = self._get("/api/places/visits?place_id=ChIJmQJIxlVYwokRLgeuocVOGVU")
        self.assertEqual(status, 200)
        self.assertEqual(data.get("status"), "SUCCESS")
        place = data.get("place", {})
        self.assertIsInstance(place.get("review_photos"), list)
        self.assertGreaterEqual(len(place["review_photos"]), 1)

    def test_30_trips_kml_export_contract(self) -> None:
        status_all, headers_all, body_all, _ = self._execute_http("GET", "/api/trips/export.kml")
        self.assertEqual(status_all, 200)
        self.assertIn("application/vnd.google-earth.kml+xml", headers_all.get("content-type", ""))
        self.assertIn(b"<kml", body_all)
        self.assertIn(b"New York Architecture Tour", body_all)

        status_t, headers_t, body_t, _ = self._execute_http(
            "GET", "/api/trips/export.kml?trip_id=trip_hermetic_nyc_2024"
        )
        self.assertEqual(status_t, 200)
        self.assertIn("application/vnd.google-earth.kml+xml", headers_t.get("content-type", ""))
        self.assertIn(b"<gx:Tour>", body_t)

        status_missing, _, _, _ = self._execute_http(
            "GET", "/api/trips/export.kml?trip_id=nonexistent_trip"
        )
        self.assertEqual(status_missing, 404)

    def test_31_fts5_diacritic_and_operator_safe_search(self) -> None:
        status, _, data = self._get("/api/search?q=zurich")
        self.assertEqual(status, 200)
        titles = [r.get("title", "") for r in data.get("results", [])]
        self.assertTrue(any("Zürich" in t for t in titles))

        status_op, _, data_op = self._get("/api/search?q=AND+OR+NOT+%22%2A%28%29+cafe")
        self.assertEqual(status_op, 200)
        self.assertEqual(data_op.get("status"), "SUCCESS")

        status_punct, _, data_punct = self._get("/api/search?q=%22%2A%28%29---")
        self.assertEqual(status_punct, 200)
        self.assertEqual(data_punct.get("status"), "SUCCESS")

    def test_32_places_fts_year_and_map_points_bbox_contract(self) -> None:
        status_p, _, data_p = self._get("/api/places?q=zurich&year=2024")
        self.assertEqual(status_p, 200)
        names = [p.get("name") for p in data_p.get("places", [])]
        self.assertIn("Café Zürich Hauptbahnhof", names)

        status_b, _, data_b = self._get("/api/places/map-points?bbox=47.35,8.50,47.40,8.58")
        self.assertEqual(status_b, 200)
        pts = data_b.get("points", [])
        self.assertEqual(len(pts), 1)
        self.assertEqual(pts[0].get("place_id"), "ChIJGaK-SZcLkEcRA9wf5_GNbuY")
        for key in ("place_id", "name", "latitude", "longitude", "category", "visit_count"):
            self.assertIn(key, pts[0])

    def test_33_calendar_range_preserves_continuous_overnight_visit(self) -> None:
        status, _, data = self._get("/api/calendar-range?start_date=2024-10-01&end_date=2024-10-02")
        self.assertEqual(status, 200)
        day2_segs = data.get("days", {}).get("2024-10-02", {}).get("segments", [])
        overnight = [s for s in day2_segs if s.get("place_id") == "ChIJ_demo_home_01"]
        self.assertEqual(len(overnight), 1)
        self.assertEqual(overnight[0].get("start_time"), "2024-10-01T22:00:00-04:00")
        self.assertEqual(overnight[0].get("end_time"), "2024-10-02T07:30:00-04:00")
        self.assertEqual(overnight[0].get("started_previous_day"), 1)


if __name__ == "__main__":
    unittest.main()
