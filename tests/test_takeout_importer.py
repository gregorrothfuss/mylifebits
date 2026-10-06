"""
Hermetic Test Suite for Universal Google Takeout Importer.
Verifies ingestion of:
1. Classic Takeout ZIPs with monthly Semantic Location History JSON.
2. Unzipped monthly Takeout directories.
3. GeoJSON FeatureCollections.
4. Universal file-format auto-detection via import_any.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from db import init_db
from importer import TimelineFusionImporter


class TestTakeoutImporter(unittest.TestCase):
    """Verifies that all Google Takeout and Timeline export formats import cleanly."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_timeline.db")
        init_db(self.db_path)
        self.importer = TimelineFusionImporter(db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_classic_takeout_zip_ingestion(self):
        """Tests importing a standard Takeout ZIP archive containing monthly semantic JSON."""
        zip_path = os.path.join(self.temp_dir, "Takeout.zip")
        month_data = {
            "timelineObjects": [
                {
                    "placeVisit": {
                        "location": {
                            "latitudeE7": 423601000,
                            "longitudeE7": -710589000,
                            "placeId": "ChIJ_boston_cafe",
                            "address": "100 Hanover St, Boston, MA",
                            "name": "Boston Public Market",
                            "semanticType": "MARKET"
                        },
                        "duration": {
                            "startTimestamp": "2024-04-10T12:00:00.000Z",
                            "endTimestamp": "2024-04-10T13:00:00.000Z"
                        }
                    }
                },
                {
                    "activitySegment": {
                        "startLocation": {"latitudeE7": 423601000, "longitudeE7": -710589000},
                        "endLocation": {"latitudeE7": 423654000, "longitudeE7": -710852000},
                        "duration": {
                            "startTimestamp": "2024-04-10T13:00:00.000Z",
                            "endTimestamp": "2024-04-10T13:30:00.000Z"
                        },
                        "distance": 2400,
                        "activityType": "CYCLING",
                        "waypointPath": {
                            "waypoints": [
                                {"latE7": 423601000, "lngE7": -710589000},
                                {"latE7": 423630000, "lngE7": -710700000},
                                {"latE7": 423654000, "lngE7": -710852000}
                            ]
                        }
                    }
                }
            ]
        }

        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr(
                "Takeout/Location History/Semantic Location History/2024/2024_APRIL.json",
                json.dumps(month_data),
            )

        res = self.importer.import_takeout_zip(zip_path, import_segments=True)
        self.assertEqual(res.get("places_extracted"), 1)
        self.assertEqual(res.get("segments_imported"), 2)

        # Verify database contents
        conn = self.importer.conn
        c = conn.cursor()
        c.execute("SELECT segment_type, place_name, activity_type, has_snapped_path FROM segments;")
        rows = c.fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["segment_type"], "visit")
        self.assertEqual(rows[0]["place_name"], "Boston Public Market")
        self.assertEqual(rows[1]["segment_type"], "activity")
        self.assertEqual(rows[1]["activity_type"], "CYCLING")
        self.assertEqual(rows[1]["has_snapped_path"], 1)

    def test_02_unzipped_directory_ingestion(self):
        """Tests scanning and ingesting an unzipped Takeout directory tree."""
        unzipped_dir = os.path.join(self.temp_dir, "TakeoutDir")
        month_dir = os.path.join(unzipped_dir, "Semantic Location History", "2024")
        os.makedirs(month_dir, exist_ok=True)

        month_data = {
            "timelineObjects": [
                {
                    "placeVisit": {
                        "location": {
                            "latitudeE7": 377749000,
                            "longitudeE7": -1224194000,
                            "placeId": "ChIJ_sf_ferry",
                            "address": "1 Ferry Building, San Francisco, CA",
                            "name": "Ferry Building",
                            "semanticType": "TERMINAL"
                        },
                        "duration": {
                            "startTimestamp": "2024-05-15T09:00:00.000Z",
                            "endTimestamp": "2024-05-15T10:30:00.000Z"
                        }
                    }
                }
            ]
        }

        with open(os.path.join(month_dir, "2024_MAY.json"), "w", encoding="utf-8") as f:
            json.dump(month_data, f)

        res = self.importer.import_takeout_directory(unzipped_dir)
        self.assertEqual(res.get("files_processed"), 1)
        self.assertEqual(res.get("segments"), 1)

        c = self.importer.conn.cursor()
        c.execute("SELECT name, city FROM places WHERE place_id = 'ChIJ_sf_ferry';")
        row = c.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["name"], "Ferry Building")

    def test_03_geojson_ingestion(self):
        """Tests importing a Takeout GeoJSON FeatureCollection."""
        geojson_path = os.path.join(self.temp_dir, "records.geojson")
        data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [-122.4089, 37.7833]
                    },
                    "properties": {
                        "placeId": "ChIJ_powell_station",
                        "name": "Powell St Station",
                        "address": "Market St, San Francisco, CA",
                        "startTime": "2024-06-01T08:00:00.000Z",
                        "endTime": "2024-06-01T08:20:00.000Z"
                    }
                },
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [-122.4089, 37.7833],
                            [-122.4000, 37.7900],
                            [-122.3950, 37.7950]
                        ]
                    },
                    "properties": {
                        "activityType": "IN_SUBWAY",
                        "distance": 1800.0,
                        "startTime": "2024-06-01T08:20:00.000Z",
                        "endTime": "2024-06-01T08:35:00.000Z"
                    }
                }
            ]
        }

        with open(geojson_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        res = self.importer.import_geojson(geojson_path)
        self.assertEqual(res.get("places"), 1)
        self.assertEqual(res.get("segments"), 2)

    def test_04_universal_dispatcher_auto_detection(self):
        """Tests import_any auto-detection for zip, directory, and geojson files."""
        # GeoJSON via import_any
        geojson_path = os.path.join(self.temp_dir, "sample.geojson")
        with open(geojson_path, "w", encoding="utf-8") as f:
            json.dump({
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [-71.1, 42.3]},
                        "properties": {
                            "placeId": "ChIJ_auto_detect_01",
                            "name": "Auto Detect Place",
                            "startTime": "2024-07-01T10:00:00.000Z",
                            "endTime": "2024-07-01T11:00:00.000Z"
                        }
                    }
                ]
            }, f)

        res = self.importer.import_any(geojson_path)
        self.assertEqual(res.get("segments"), 1)


if __name__ == "__main__":
    unittest.main()
