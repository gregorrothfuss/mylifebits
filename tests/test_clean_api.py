"""
Comprehensive Integration Test Suite for Clean Modular Timeline API.
Tests all registered API endpoints, request validation, error handling, and segment CRUD.
"""

from __future__ import annotations

import json
import unittest
from typing import Any, Dict

import api
from api.router import Request


class TestCleanTimelineAPI(unittest.TestCase):
    """Direct dispatch test suite verifying all API domain routes."""

    def _call(
        self,
        method: str,
        path: str,
        query: Dict[str, Any] | None = None,
        body: Dict[str, Any] | None = None,
    ) -> tuple[int, Dict[str, Any]]:
        query_params = {}
        if query:
            for k, v in query.items():
                query_params[k] = [str(v)] if not isinstance(v, list) else [str(x) for x in v]

        raw_body = json.dumps(body).encode("utf-8") if body else b""
        req = Request(method=method, path=path, query_params=query_params, headers={}, body=raw_body)
        res = api.router.dispatch(req)
        data = {}
        if res.content_type.startswith("application/json") and res.body:
            data = json.loads(res.body.decode("utf-8"))
        return res.status_code, data

    def test_01_overview(self):
        status, data = self._call("GET", "/api/overview")
        self.assertEqual(status, 200)
        self.assertEqual(data.get("status"), "SUCCESS")
        scorecard = data.get("scorecard", {})
        self.assertIn("total_segments", scorecard)
        self.assertIn("place_hydration_rate_pct", scorecard)
        self.assertIn("category_breakdown", scorecard)
        self.assertIn("top_cities", scorecard)

    def test_02_calendar(self):
        status, data = self._call("GET", "/api/calendar", {"year": "2024", "month": "10"})
        self.assertEqual(status, 200)
        self.assertEqual(data.get("status"), "SUCCESS")
        self.assertIsInstance(data.get("days"), list)

    def test_03_day(self):
        status, data = self._call("GET", "/api/day", {"date": "2024-10-01"})
        self.assertEqual(status, 200)
        self.assertEqual(data.get("status"), "SUCCESS")
        self.assertEqual(data.get("date"), "2024-10-01")
        self.assertIn("segments", data)
        self.assertIn("gaps", data)
        self.assertIn("raw_signals", data)

    def test_04_places(self):
        status, data = self._call("GET", "/api/places", {"limit": 10})
        self.assertEqual(status, 200)
        self.assertEqual(data.get("status"), "SUCCESS")
        self.assertIsInstance(data.get("places"), list)
        self.assertTrue(len(data.get("places")) > 0)

    def test_05_places_map_points(self):
        status, data = self._call("GET", "/api/places/map-points", {"limit": 50})
        self.assertEqual(status, 200)
        self.assertEqual(data.get("status"), "SUCCESS")
        self.assertIn("points", data)

    def test_06_diagnostics_gaps(self):
        status, data = self._call("GET", "/api/diagnostics/gaps", {"limit": 10})
        self.assertEqual(status, 200)
        self.assertEqual(data.get("status"), "SUCCESS")
        self.assertIn("gaps", data)

    def test_07_heatmap(self):
        status, data = self._call("GET", "/api/heatmap")
        self.assertEqual(status, 200)
        self.assertEqual(data.get("status"), "SUCCESS")
        self.assertIn("points", data)

    def test_08_search(self):
        # Search place
        status, data = self._call("GET", "/api/search", {"q": "New York"})
        self.assertEqual(status, 200)
        self.assertEqual(data.get("status"), "SUCCESS")
        self.assertIn("results", data)

        # Search date
        status, data_d = self._call("GET", "/api/search", {"q": "2015-03-28"})
        self.assertEqual(status, 200)
        self.assertEqual(data_d.get("status"), "SUCCESS")

    def test_09_export_geojson(self):
        status, data = self._call("GET", "/api/export", {"date": "2024-10-01", "format": "geojson"})
        self.assertEqual(status, 200)
        self.assertEqual(data.get("type"), "FeatureCollection")
        self.assertIn("features", data)

    def test_10_trips(self):
        status, data = self._call("GET", "/api/trips", {"limit": 5})
        self.assertEqual(status, 200)
        self.assertEqual(data.get("status"), "SUCCESS")
        self.assertIn("trips", data)

    def test_11_segment_crud(self):
        # 1. Create
        create_payload = {
            "segment_type": "visit",
            "place_name": "Test Modern Cafe",
            "place_address": "123 Clean Architecture Blvd",
            "category": "Food & Drink",
            "date": "2024-10-01",
            "start_time": "2024-10-01T10:00:00-04:00",
            "end_time": "2024-10-01T11:00:00-04:00",
            "start_ts": 1727791200.0,
            "end_ts": 1727794800.0,
            "latitude": 40.75,
            "longitude": -73.98
        }
        status, res_c = self._call("POST", "/api/segments/create", body=create_payload)
        self.assertEqual(status, 200)
        self.assertEqual(res_c.get("status"), "SUCCESS")
        new_id = res_c.get("id")
        self.assertIsNotNone(new_id)

        # 2. Update
        update_payload = {
            "id": new_id,
            "place_name": "Updated Modern Cafe",
            "category": "Coffee Shop"
        }
        status, res_u = self._call("POST", "/api/segments/update", body=update_payload)
        self.assertEqual(status, 200)
        self.assertEqual(res_u.get("status"), "SUCCESS")

        # 3. Delete
        status, res_d = self._call("POST", "/api/segments/delete", body={"id": new_id})
        self.assertEqual(status, 200)
        self.assertEqual(res_d.get("status"), "SUCCESS")

    def test_12_proposals_alias(self):
        # Verify /api/proposals/edit-and-apply alias route exists and validates missing payload
        status, res = self._call("POST", "/api/proposals/edit-and-apply", body={})
        self.assertEqual(status, 400)
        self.assertEqual(res.get("status"), "ERROR")

    def test_14_places_visits(self):
        # 1. Missing place_id parameter
        status, res = self._call("GET", "/api/places/visits")
        self.assertEqual(status, 400)
        self.assertEqual(res.get("status"), "ERROR")

        # 2. Valid place_id (Miami International Airport)
        status, res = self._call("GET", "/api/places/visits", {"place_id": "ChIJ2-pYhL122YgRz5k_c4b9r3I"})
        self.assertEqual(status, 200)
        self.assertEqual(res.get("status"), "SUCCESS")
        self.assertEqual(res.get("count"), 14)
        self.assertIsInstance(res.get("visits"), list)
        self.assertEqual(len(res.get("visits")), 14)
    def test_15_activity_summaries(self):
        # 1. Activity summaries default (all time)
        status, res = self._call("GET", "/api/insights/activity-summaries")
        self.assertEqual(status, 200)
        self.assertEqual(res.get("status"), "SUCCESS")
        self.assertIn("totals", res)
        self.assertIn("modes", res)
        self.assertIn("available_periods", res)

        # 2. Activity summaries specific year
        status_y, res_y = self._call("GET", "/api/insights/activity-summaries", {"period": "2026"})
        self.assertEqual(status_y, 200)
        self.assertEqual(res_y.get("period"), "2026")
        self.assertGreater(len(res_y.get("modes", [])), 0)

        # 3. Nuggets list structure
        status_n, res_n = self._call("GET", "/api/insights/nuggets")
        self.assertEqual(status_n, 200)
        self.assertEqual(res_n.get("status"), "SUCCESS")
        self.assertIsInstance(res_n.get("nuggets"), list)
        self.assertGreater(len(res_n.get("nuggets")), 0)


if __name__ == "__main__":
    unittest.main()
