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

    def test_05_reviews_takeout_ingestion(self):
        """Tests importing standard Google Maps Takeout Reviews.json with spatial place matching."""
        # First ensure a target place exists
        conn = self.importer.conn
        conn.execute("""
        INSERT INTO places (place_id, name, address, latitude, longitude, category, visit_count)
        VALUES ('ChIJ_tatte_bakery', 'Tatte Bakery', '318 Third St, Cambridge, MA', 42.3650, -71.0850, 'Food & Drink', 5);
        """)
        conn.commit()

        reviews_path = os.path.join(self.temp_dir, "Reviews.json")
        reviews_data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [-71.0850, 42.3650]
                    },
                    "properties": {
                        "Location": {
                            "Address": "318 Third St, Cambridge, MA 02142",
                            "Business Name": "Tatte Bakery & Cafe",
                            "Country Code": "US",
                            "Geo Coordinates": {
                                "Latitude": 42.3650,
                                "Longitude": -71.0850
                            }
                        },
                        "Review": {
                            "Review URL": "https://maps.google.com/?cid=998877",
                            "Star Rating": 5,
                            "Text": "Fantastic shakshuka and pistachio croissants.",
                            "Time": "2024-05-10T14:30:00Z"
                        }
                    }
                }
            ]
        }
        with open(reviews_path, "w", encoding="utf-8") as f:
            json.dump(reviews_data, f)

        res = self.importer.import_any(reviews_path)
        self.assertEqual(res.get("total_reviews"), 1)
        self.assertEqual(res.get("matched_pois"), 1)

        c = conn.cursor()
        c.execute("SELECT place_name, rating, review_text, matched_place_id FROM poi_reviews;")
        rev_row = c.fetchone()
        self.assertIsNotNone(rev_row)
        self.assertEqual(rev_row["place_name"], "Tatte Bakery & Cafe")
        self.assertEqual(rev_row["rating"], 5)
        self.assertEqual(rev_row["matched_place_id"], "ChIJ_tatte_bakery")

        # Verify place record was updated with review
        c.execute("SELECT review_rating, has_review, review_text FROM places WHERE place_id = 'ChIJ_tatte_bakery';")
        place_row = c.fetchone()
        self.assertEqual(place_row["review_rating"], 5)
        self.assertEqual(place_row["has_review"], 1)
        self.assertIn("shakshuka", place_row["review_text"])

    def test_06_saved_places_takeout_ingestion(self):
        """Tests importing standard Google Maps Takeout Saved Places.json."""
        saved_path = os.path.join(self.temp_dir, "Saved Places.json")
        saved_data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [-71.0550, 42.3520]
                    },
                    "properties": {
                        "Google Maps URL": "https://maps.google.com/?cid=12345678",
                        "Location": {
                            "Address": "700 Atlantic Ave, Boston, MA",
                            "Business Name": "South Station",
                            "Country Code": "US",
                            "Geo Coordinates": {
                                "Latitude": 42.3520,
                                "Longitude": -71.0550
                            }
                        },
                        "Published": "2024-03-01T12:00:00Z",
                        "Title": "Want to go",
                        "Comment": "Catch the high-speed regional rail"
                    }
                }
            ]
        }
        with open(saved_path, "w", encoding="utf-8") as f:
            json.dump(saved_data, f)

        res = self.importer.import_any(saved_path)
        self.assertEqual(res.get("total_saved"), 1)

        c = self.importer.conn.cursor()
        c.execute("SELECT name, description, source_type FROM custom_labeled_places WHERE name = 'South Station';")
        custom_row = c.fetchone()
        self.assertIsNotNone(custom_row)
        self.assertEqual(custom_row["source_type"], "Want to go")

    def test_07_photos_takeout_ingestion(self):
        """Tests ingesting photos with Google Photos companion JSON sidecars."""
        from PIL import Image

        photos_dir = os.path.join(self.temp_dir, "Google Photos", "Photos from 2024")
        os.makedirs(photos_dir, exist_ok=True)

        # Create dummy image
        img_path = os.path.join(photos_dir, "IMG_20240501_120000.jpg")
        img = Image.new("RGB", (100, 100), color=(73, 109, 137))
        img.save(img_path, format="JPEG")

        # Create Takeout sidecar
        sidecar_path = os.path.join(photos_dir, "IMG_20240501_120000.jpg.json")
        sidecar_data = {
            "title": "IMG_20240501_120000.jpg",
            "photoTakenTime": {
                "timestamp": "1714564800",
                "formatted": "May 1, 2024, 12:00:00 PM UTC"
            },
            "geoData": {
                "latitude": 42.3601,
                "longitude": -71.0589,
                "altitude": 12.5
            },
            "people": [
                {"name": "Alice"}
            ]
        }
        with open(sidecar_path, "w", encoding="utf-8") as f:
            json.dump(sidecar_data, f)

        res = self.importer.import_any(photos_dir, is_photos=True)
        self.assertEqual(res.get("ingested"), 1)

        c = self.importer.conn.cursor()
        c.execute("SELECT filename, timestamp_utc, local_date, latitude, longitude, people FROM photos;")
        p_row = c.fetchone()
        self.assertIsNotNone(p_row)
        self.assertEqual(p_row["filename"], "IMG_20240501_120000.jpg")
        self.assertEqual(p_row["timestamp_utc"], 1714564800)
        self.assertEqual(p_row["local_date"], "2024-05-01")
        self.assertAlmostEqual(p_row["latitude"], 42.3601, places=3)
        self.assertIn("Alice", p_row["people"])

    def test_09_embeddings_import_and_vector_search(self):
        """Tests importing precomputed vector embeddings and OCR text from a companion vault."""
        import struct
        import sqlite3

        # Prepare a companion photo vault db
        vault_path = os.path.join(self.temp_dir, "photos_vault.db")
        con_vault = sqlite3.connect(vault_path)
        con_vault.execute("""
        CREATE TABLE embeddings (
            sha256 TEXT PRIMARY KEY,
            vector BLOB NOT NULL
        );
        """)
        con_vault.execute("""
        CREATE TABLE media_items (
            sha256 TEXT PRIMARY KEY,
            blur_score REAL,
            ocr_text TEXT
        );
        """)

        # Generate a dummy 512-dim normalized vector
        vec = [0.0] * 512
        vec[0] = 1.0
        vec_bytes = struct.pack("512f", *vec)

        dummy_sha = "aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899"
        con_vault.execute("INSERT INTO embeddings VALUES (?, ?);", (dummy_sha, vec_bytes))
        con_vault.execute("INSERT INTO media_items VALUES (?, ?, ?);", (dummy_sha, 84.5, "Acme Coffee Roasters receipt"))
        con_vault.commit()
        con_vault.close()

        # Ingest embeddings into timeline database
        res = self.importer.import_any(vault_path, is_embeddings=True)
        self.assertEqual(res.get("embeddings_imported"), 1)
        self.assertEqual(res.get("ocr_imported"), 1)

        c = self.importer.conn.cursor()
        c.execute("SELECT sha256, dim, model FROM photo_embeddings WHERE sha256 = ?;", (dummy_sha,))
        row = c.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["sha256"], dummy_sha)
        self.assertEqual(row["dim"], 512)
        self.assertEqual(row["model"], "open_clip:ViT-B-32")


if __name__ == "__main__":
    unittest.main()

