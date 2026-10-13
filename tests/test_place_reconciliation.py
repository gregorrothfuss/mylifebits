"""
Unit & Integration Tests for POI Reconciliation & Nameless Place Elimination.
Uses a hermetic temporary SQLite database with zero dependency on personal data.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from db import init_db
from enrichment.place_reconciler import (
    get_aliased_place,
    is_nameless_place,
    reconcile_place_spatial,
    record_place_alias,
    resolve_visit_place,
)


class TestPlaceReconciliation(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_reconcile.db")
        init_db(self.db_path)

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO places (place_id, name, address, category, city, latitude, longitude, visit_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                "ChIJ_canary_cafe_test00001",
                "Canary Cafe",
                "171 S 4th St, Brooklyn, NY 11211, USA",
                "Food & Drink",
                "New York",
                40.7114074,
                -73.9610993,
                3,
            ),
        )
        c.execute(
            """
            INSERT INTO places (place_id, name, address, category, city, latitude, longitude, visit_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                "ChIJs--MqP1YwokRBwAhjXWIHn8",
                "New York City Hall",
                "City Hall Park, New York, NY 10007, USA",
                "Services & Civic",
                "New York",
                40.7127744,
                -74.006059,
                5,
            ),
        )
        conn.commit()
        conn.close()

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_is_nameless_place_detection(self) -> None:
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
        self.assertFalse(is_nameless_place("Pi Bakerie"))
        self.assertFalse(is_nameless_place("Google NYC"))

    def test_reconcile_canary_cafe_spatial(self) -> None:
        """Asserts that coordinates within radius resolve to Canary Cafe from catalog."""
        res = reconcile_place_spatial(
            self.db_path, 40.7114074, -73.9610993, date_str="2026-09-18"
        )
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res["name"], "Canary Cafe")
        self.assertEqual(res["category"], "Food & Drink")
        self.assertIn("171 S 4th St", res["address"])

    def test_resolve_visit_place_fallback_elimination(self) -> None:
        """Verifies resolve_visit_place heals nameless visits without returning raw coordinates."""
        res = resolve_visit_place(
            self.db_path,
            40.7114074,
            -73.9610993,
            current_name="Unconfirmed Location",
            date_str="2026-09-18",
            allow_reverse_geocode=False,
        )
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res["name"], "Canary Cafe")

    def test_place_aliases_resolution(self) -> None:
        """Verifies that recorded Place ID aliases resolve to canonical places via place_aliases."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        alt_pid = "ChIJOwg_06VPwokRYv534QaPC8g"
        canonical_pid = "ChIJs--MqP1YwokRBwAhjXWIHn8"
        record_place_alias(conn, alt_pid, canonical_pid)
        conn.commit()

        aliased = get_aliased_place(conn, alt_pid)
        self.assertIsNotNone(aliased)
        assert aliased is not None
        self.assertEqual(aliased["name"], "New York City Hall")
        self.assertEqual(aliased["place_id"], canonical_pid)
        conn.close()


if __name__ == "__main__":
    unittest.main()
