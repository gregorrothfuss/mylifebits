"""
Unit & Integration Tests for POI Reconciliation & Nameless Place Elimination.
"""

import json
import sqlite3
import unittest

import api.router
from api.router import Request
from enrichment.place_reconciler import (
    is_nameless_place,
    reconcile_place_spatial,
    resolve_visit_place,
    get_aliased_place,
    record_place_alias,
)

DEFAULT_DB_PATH = "timeline_viewer.db"


class TestPlaceReconciliation(unittest.TestCase):

    def test_is_nameless_place_detection(self):
        """Validates identification of generic placeholders and raw coordinate strings."""
        self.assertTrue(is_nameless_place(None))
        self.assertTrue(is_nameless_place(""))
        self.assertTrue(is_nameless_place("Unconfirmed Location"))
        self.assertTrue(is_nameless_place("Place"))
        self.assertTrue(is_nameless_place("Saved Location"))
        self.assertTrue(is_nameless_place("Point of Interest"))
        self.assertTrue(is_nameless_place("Location (40.7114, -73.9611)"))
        self.assertTrue(is_nameless_place("location (42.0755, -73.9516)"))

        # Valid POIs should not be flagged as nameless
        self.assertFalse(is_nameless_place("Canary Cafe"))
        self.assertFalse(is_nameless_place("Home (298 E 2nd St)"))
        self.assertFalse(is_nameless_place("Pi Bakerie"))
        self.assertFalse(is_nameless_place("Google NYC"))

    def test_reconcile_canary_cafe_spatial(self):
        """Asserts that (40.7114074, -73.9610993) resolves to Canary Cafe from catalog."""
        res = reconcile_place_spatial(DEFAULT_DB_PATH, 40.7114074, -73.9610993, date_str="2026-09-18")
        self.assertIsNotNone(res)
        self.assertEqual(res["name"], "Canary Cafe")
        self.assertEqual(res["category"], "Food & Drink")
        self.assertIn("171 S 4th St", res["address"])

    def test_resolve_visit_place_fallback_elimination(self):
        """Verifies resolve_visit_place heals nameless visits without returning raw coordinates."""
        res = resolve_visit_place(
            DEFAULT_DB_PATH,
            40.7114074,
            -73.9610993,
            current_name="Unconfirmed Location",
            date_str="2026-09-18",
            allow_reverse_geocode=False,
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["name"], "Canary Cafe")

    def test_day_api_zero_coordinate_titles_on_september_18(self):
        """Asserts that /api/day for 2026-09-18 contains 0 raw coordinate titles or unconfirmed cards."""
        req = Request(
            method="GET",
            path="/api/day",
            query_params={"date": ["2026-09-18"]},
            headers={},
            body=b"",
        )
        res = api.router.dispatch(req)
        self.assertEqual(res.status_code, 200)

        data = json.loads(res.body.decode("utf-8"))
        segments = data.get("segments", [])
        visits = [s for s in segments if s.get("segment_type") == "visit"]
        self.assertGreater(len(visits), 0)

        canary_found = False
        for v in visits:
            name = v.get("place_name", "")
            self.assertFalse(
                is_nameless_place(name),
                f"Found unhealed nameless place in /api/day: '{name}' on visit {v.get('id')}",
            )
            self.assertFalse(
                name.startswith("Location ("),
                f"Found raw coordinate title: '{name}'",
            )
            if "Canary Cafe" in name:
                canary_found = True

        self.assertTrue(canary_found, "Expected Canary Cafe visit on 2026-09-18 between 08:08 and 08:24")

    def test_place_aliases_resolution(self):
        """Verifies that new/mutated Place IDs resolve to canonical places via place_aliases."""
        conn = sqlite3.connect(DEFAULT_DB_PATH)
        # Canary Cafe alternate Place ID from recent export
        alt_pid = "ChIJd3OTBwBbwokRW7-99uZXpts"
        aliased = get_aliased_place(conn, alt_pid)
        self.assertIsNotNone(aliased)
        self.assertEqual(aliased["name"], "Canary Cafe")
        self.assertEqual(aliased["place_id"], "ChIJl8jLJM9bwokRpcorN5sMbis")
        conn.close()


if __name__ == "__main__":
    unittest.main()
