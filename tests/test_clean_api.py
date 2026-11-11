"""
Comprehensive Integration Test Suite for Clean Modular Timeline API.
Tests all registered API endpoints, request validation, error handling, and segment CRUD.
"""

from __future__ import annotations

import contextlib
import json
import os
import unittest
from typing import Any, Dict, Optional

import api
from api.router import Request
from tests.hermetic_fixture import hermetic_db_environment, write_verification_artifact


class TestCleanTimelineAPI(unittest.TestCase):
    """Direct dispatch test suite verifying all API domain routes."""

    _hermetic_stack: Optional[contextlib.ExitStack] = None
    _dispatched_calls: int = 0

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls._dispatched_calls = 0
        if "mylifebits_hermetic_" not in os.environ.get("TIMELINE_DB_PATH", ""):
            cls._hermetic_stack = contextlib.ExitStack()
            cls._hermetic_stack.enter_context(hermetic_db_environment())

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            write_verification_artifact(
                "test_clean_api",
                {
                    "db_name": os.path.basename(os.environ.get("TIMELINE_DB_PATH", "")),
                    "hermetic": "mylifebits_hermetic_" in os.environ.get("TIMELINE_DB_PATH", ""),
                    "dispatched_calls": cls._dispatched_calls,
                },
            )
        finally:
            if cls._hermetic_stack is not None:
                cls._hermetic_stack.close()
                cls._hermetic_stack = None
            super().tearDownClass()

    def _call(
        self,
        method: str,
        path: str,
        query: Dict[str, Any] | None = None,
        body: Dict[str, Any] | None = None,
    ) -> tuple[int, Dict[str, Any]]:
        type(self)._dispatched_calls += 1
        query_params = {}
        if query:
            for k, v in query.items():
                query_params[k] = [str(v)] if not isinstance(v, list) else [str(x) for x in v]

        raw_body = json.dumps(body).encode("utf-8") if body else b""
        req = Request(
            method=method,
            path=path,
            query_params=query_params,
            headers={"origin": "https://mylifebits.local", "sec-fetch-site": "same-origin"},
            body=raw_body,
        )
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

        # 2. Valid place_id (dynamic from current DB)
        from api.db import query_one
        row = query_one("SELECT place_id FROM places WHERE visit_count > 0 LIMIT 1;")
        pid = row["place_id"] if row else "ChIJ_demo_home_01"
        status, res = self._call("GET", "/api/places/visits", {"place_id": pid})
        self.assertEqual(status, 200)
        self.assertEqual(res.get("status"), "SUCCESS")
        self.assertIsInstance(res.get("visits"), list)
        self.assertIsInstance(res.get("count"), int)
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

    def test_16_gap_scoped_proposal_auto_accept(self):
        from api.db import get_db, query_one

        with get_db() as conn:
            c = conn.cursor()
            c.execute(
                """
                INSERT INTO gaps (
                    start_time, end_time, start_ts, end_ts, duration_hours, date, year,
                    prev_lat, prev_lng, next_lat, next_lng, jump_distance_km, status
                ) VALUES (
                    '2024-10-03T12:00:00Z', '2024-10-03T14:00:00Z', 1727956800.0, 1727964000.0,
                    2.0, '2024-10-03', 2024, 40.7128, -74.0060, 40.7135, -74.0055, 0.1, 'OPEN'
                );
                """
            )
            shared_id = int(c.lastrowid)
            c.execute(
                """
                INSERT INTO fix_proposals (
                    target_type, target_id, date, proposed_action, confidence,
                    reasoning, patch_data_json, status, source, created_at
                ) VALUES (?, ?, '2024-10-03', 'INSERT_VISIT', 0.9, 'Gap proposal', '{}', 'PENDING', 'TEST_GAP', '2024-10-03T12:00:00Z');
                """,
                ("gap", shared_id),
            )
            gap_prop_id = int(c.lastrowid)
            c.execute(
                """
                INSERT INTO fix_proposals (
                    target_type, target_id, date, proposed_action, confidence,
                    reasoning, patch_data_json, status, source, created_at
                ) VALUES (?, ?, '2024-10-03', 'HYDRATE_PLACE', 0.9, 'Segment proposal', '{}', 'PENDING', 'TEST_SEG', '2024-10-03T12:00:00Z');
                """,
                ("segment", shared_id),
            )
            seg_prop_id = int(c.lastrowid)

        status, res_c = self._call(
            "POST",
            "/api/segments/create",
            body={
                "segment_type": "visit",
                "place_name": "Scoped Gap Bakery",
                "category": "Food & Drink",
                "date": "2024-10-03",
                "start_time": "2024-10-03T12:15:00Z",
                "end_time": "2024-10-03T13:15:00Z",
                "start_ts": 1727957700.0,
                "end_ts": 1727961300.0,
                "latitude": 40.7130,
                "longitude": -74.0058,
                "gap_id": shared_id,
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(res_c.get("status"), "SUCCESS")

        gap_prop = query_one("SELECT status FROM fix_proposals WHERE id = ?;", (gap_prop_id,))
        seg_prop = query_one("SELECT status FROM fix_proposals WHERE id = ?;", (seg_prop_id,))
        self.assertEqual(gap_prop["status"], "ACCEPTED")
        self.assertEqual(seg_prop["status"], "PENDING")

    def test_17_resolve_unconfirmed_visit_and_chord_polyline(self):
        from api.db import get_db, query_one

        with get_db() as conn:
            c = conn.cursor()
            c.execute(
                """
                INSERT INTO segments (
                    segment_type, start_time, end_time, start_ts, end_ts, duration_minutes,
                    date, year, month, day, latitude, longitude, place_name,
                    is_unconfirmed, hierarchy_level, source
                ) VALUES (
                    'visit', '2024-10-04T09:00:00Z', '2024-10-04T10:00:00Z', 1728032400.0, 1728036000.0,
                    60.0, '2024-10-04', 2024, 10, 4, 46.9480, 7.4474, 'Unknown Stop',
                    1, 0, 'ON_DEVICE_2026'
                );
                """
            )
            unconf_seg_id = int(c.lastrowid)
            c.execute(
                """
                INSERT INTO fix_proposals (
                    target_type, target_id, date, proposed_action, confidence,
                    reasoning, patch_data_json, status, source, decision_key, created_at
                ) VALUES (
                    'segment', ?, '2024-10-04', 'RESOLVE_UNCONFIRMED_VISIT', 0.95,
                    'Confirm venue', ?, 'PENDING', 'PHOTO_CORPUS', 'dkey_unconf_test_17', '2024-10-04T09:00:00Z'
                );
                """,
                (
                    unconf_seg_id,
                    json.dumps({"target_place": "Aare Roastery", "category": "Food & Drink"}),
                ),
            )
            unconf_prop_id = int(c.lastrowid)

            c.execute(
                """
                INSERT INTO gaps (
                    start_time, end_time, start_ts, end_ts, duration_hours, date, year,
                    prev_lat, prev_lng, next_lat, next_lng, jump_distance_km, status
                ) VALUES (
                    '2024-10-04T10:00:00Z', '2024-10-04T10:30:00Z', 1728036000.0, 1728037800.0,
                    0.5, '2024-10-04', 2024, 46.9480, 7.4474, 46.9550, 7.4350, 2.5, 'OPEN'
                );
                """
            )
            chord_gap_id = int(c.lastrowid)
            c.execute(
                """
                INSERT INTO fix_proposals (
                    target_type, target_id, date, proposed_action, confidence,
                    reasoning, patch_data_json, status, source, created_at
                ) VALUES (
                    'gap', ?, '2024-10-04', 'SYNTHESIZE_TRANSIT_LEG', 0.9,
                    'Bridge transit chord', ?, 'PENDING', 'TRANSIT_HEALER', '2024-10-04T10:00:00Z'
                );
                """,
                (
                    chord_gap_id,
                    json.dumps({"mode": "IN_TRAM", "duration_minutes": 30.0, "distance_km": 2.5}),
                ),
            )
            chord_prop_id = int(c.lastrowid)

        st_u, res_u = self._call("POST", "/api/fixes/apply", body={"proposal_id": unconf_prop_id})
        self.assertEqual(st_u, 200)
        self.assertEqual(res_u.get("status"), "SUCCESS")

        seg_after = query_one(
            "SELECT place_id, place_name, is_unconfirmed FROM segments WHERE id = ?;",
            (unconf_seg_id,),
        )
        self.assertEqual(seg_after["is_unconfirmed"], 0)
        self.assertEqual(seg_after["place_name"], "Aare Roastery")
        self.assertTrue(str(seg_after["place_id"]).startswith("ChIJ"))

        place_after = query_one(
            "SELECT visit_count FROM places WHERE place_id = ?;",
            (seg_after["place_id"],),
        )
        self.assertIsNotNone(place_after)
        self.assertGreaterEqual(place_after["visit_count"], 1)

        ud_row = query_one(
            "SELECT decision_type FROM user_decisions WHERE decision_key = 'dkey_unconf_test_17';"
        )
        self.assertIsNotNone(ud_row)
        self.assertEqual(ud_row["decision_type"], "ACCEPT_PROPOSAL")

        st_c, res_c = self._call("POST", "/api/fixes/apply", body={"proposal_id": chord_prop_id})
        self.assertEqual(st_c, 200)
        self.assertEqual(res_c.get("status"), "SUCCESS")

        chord_seg = query_one(
            "SELECT has_snapped_path, path_points_json FROM segments WHERE date = '2024-10-04' AND activity_type = 'IN_TRAM';"
        )
        self.assertIsNotNone(chord_seg)
        self.assertEqual(chord_seg["has_snapped_path"], 0)
        self.assertEqual(len(json.loads(chord_seg["path_points_json"])), 2)

    def test_18_physics_airport_anchors_and_city_state_bounds(self):
        from api.db import get_db, query_one
        from enrichment.layered_engine import LayeredTimelineEngine
        from enrichment.trip_inferencer import resolve_coord_country

        sg_country, _, _ = resolve_coord_country(1.3521, 103.8198)
        hk_country, _, _ = resolve_coord_country(22.3193, 114.1694)
        self.assertEqual(sg_country, "Singapore")
        self.assertEqual(hk_country, "Hong Kong")

        with get_db() as conn:
            c = conn.cursor()
            # 1) >300 km & >250 km/h WITHOUT airport endpoints (central Kansas -> central Nebraska) -> must NOT become FLYING
            c.execute(
                """
                INSERT INTO segments (
                    segment_type, activity_type, start_time, end_time, start_ts, end_ts,
                    duration_minutes, distance_meters, date, year, month, day,
                    latitude, longitude, end_lat, end_lng, hierarchy_level, source
                ) VALUES (
                    'activity', 'IN_PASSENGER_VEHICLE', '2024-10-05T08:00:00Z', '2024-10-05T09:00:00Z',
                    1728115200.0, 1728118800.0, 60.0, 360000.0, '2024-10-05', 2024, 10, 5,
                    38.5000, -98.5000, 41.7000, -99.5000, 0, 'ON_DEVICE_2026'
                );
                """
            )
            non_airport_id = int(c.lastrowid)

            # 2) >300 km & >250 km/h WITH verified airport endpoints (JFK -> ZRH) -> MUST become FLYING
            c.execute(
                """
                INSERT INTO segments (
                    segment_type, activity_type, start_time, end_time, start_ts, end_ts,
                    duration_minutes, distance_meters, date, year, month, day,
                    latitude, longitude, end_lat, end_lng, hierarchy_level, source
                ) VALUES (
                    'activity', 'IN_PASSENGER_VEHICLE', '2024-10-05T10:00:00Z', '2024-10-05T17:30:00Z',
                    1728122400.0, 1728149400.0, 450.0, 6320000.0, '2024-10-05', 2024, 10, 5,
                    40.6413, -73.7781, 47.4647, 8.5492, 0, 'ON_DEVICE_2026'
                );
                """
            )
            airport_flight_id = int(c.lastrowid)

            # 3) Short <300 km FLYING segment -> MUST demote to IN_PASSENGER_VEHICLE
            c.execute(
                """
                INSERT INTO segments (
                    segment_type, activity_type, start_time, end_time, start_ts, end_ts,
                    duration_minutes, distance_meters, date, year, month, day,
                    latitude, longitude, end_lat, end_lng, hierarchy_level, source
                ) VALUES (
                    'activity', 'FLYING', '2024-10-05T19:00:00Z', '2024-10-05T19:45:00Z',
                    1728154800.0, 1728157500.0, 45.0, 85000.0, '2024-10-05', 2024, 10, 5,
                    47.4647, 8.5492, 46.9480, 7.4474, 0, 'ON_DEVICE_2026'
                );
                """
            )
            short_flight_id = int(c.lastrowid)

        le = LayeredTimelineEngine(os.environ["TIMELINE_DB_PATH"])
        le.sanitize_physics_and_polylines()

        s_non_air = query_one("SELECT activity_type FROM segments WHERE id = ?;", (non_airport_id,))
        s_air = query_one("SELECT activity_type FROM segments WHERE id = ?;", (airport_flight_id,))
        s_short = query_one("SELECT activity_type FROM segments WHERE id = ?;", (short_flight_id,))

        self.assertNotEqual(s_non_air["activity_type"], "FLYING")
        self.assertEqual(s_air["activity_type"], "FLYING")
        self.assertEqual(s_short["activity_type"], "IN_PASSENGER_VEHICLE")


if __name__ == "__main__":
    unittest.main()
