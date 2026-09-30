#!/usr/bin/env python3
"""
E2E Integration Verification Script for Photo Enrichment in Day and Places Views.
Validates:
1. Day View itinerary photo matching against gregor_cos photo index.
2. Places View photo enrichment across catalog and visit history.
3. Binary image serving via /api/photo and /previews/ endpoints.
"""

import json
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import ThreadedTimelineServer


def main():
    print("Starting temporary test server on port 8998...")
    server = ThreadedTimelineServer(port=8998)
    t = threading.Thread(target=server.start, daemon=True)
    t.start()
    time.sleep(0.5)

    base = "http://127.0.0.1:8998"

    # Test 1: Day View Photo Enrichment
    print("\n[Test 1] Day View /api/day?date=2019-12-30...")
    with urllib.request.urlopen(f"{base}/api/day?date=2019-12-30") as resp:
        assert resp.status == 200, f"Expected 200, got {resp.status}"
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "SUCCESS"
        assert "photos" in data and len(data["photos"]) > 0, "No day photos attached"
        assert data["photo_count"] == len(data["photos"]), "photo_count mismatch"
        print(f"  Passed: {data['photo_count']} photos loaded for day 2019-12-30.")

        # Check segment photo matching
        visits_with_photos = [s for s in data["segments"] if s.get("photo_count", 0) > 0]
        assert len(visits_with_photos) >= 5, f"Expected at least 5 segments with photos, got {len(visits_with_photos)}"
        print(f"  Passed: {len(visits_with_photos)} segments successfully matched with photos.")

    # Test 2: Places Catalog Photo Enrichment
    print("\n[Test 2] Places Catalog /api/places...")
    with urllib.request.urlopen(f"{base}/api/places?q=Kings%20County%20Brewers") as resp:
        assert resp.status == 200
        pdata = json.loads(resp.read().decode("utf-8"))
        places = pdata.get("places", [])
        assert len(places) > 0, "Place not found"
        kcbc = places[0]
        assert len(kcbc.get("review_photos", [])) > 0, "No review_photos in KCBC place"
        print(f"  Passed: KCBC place has {len(kcbc['review_photos'])} photos.")

    # Test 3: Place Visits Modal Photo Enrichment
    print("\n[Test 3] Place Visits History /api/places/visits...")
    with urllib.request.urlopen(f"{base}/api/places/visits?place_id=ChIJb6ZVSB1cwokRES6FZ2WAMAA") as resp:
        assert resp.status == 200
        vdata = json.loads(resp.read().decode("utf-8"))
        assert vdata["status"] == "SUCCESS"
        assert "photos" in vdata and len(vdata["photos"]) > 0, "No photos in place visits"
        assert vdata["photo_count"] == len(vdata["photos"]), "photo_count mismatch"
        print(f"  Passed: Place visits modal returned {vdata['photo_count']} photos.")

    # Test 4: Photo Proxy and Static Preview Serving
    print("\n[Test 4] Image Wire Serving via /api/photo and /previews/...")
    sample_sha = data["photos"][0]["sha256"]
    with urllib.request.urlopen(f"{base}/api/photo?sha256={sample_sha}") as resp:
        assert resp.status == 200
        assert "image/" in resp.headers.get("Content-Type", "")
        img_bytes = resp.read()
        assert len(img_bytes) > 1000
        print(f"  Passed: /api/photo?sha256= returned {len(img_bytes)} bytes of {resp.headers.get('Content-Type')}.")

    with urllib.request.urlopen(f"{base}/previews/{sample_sha}.webp") as resp:
        assert resp.status == 200
        assert resp.headers.get("Content-Type") == "image/webp"
        img_bytes2 = resp.read()
        assert len(img_bytes2) == len(img_bytes)
        print(f"  Passed: /previews/{sample_sha}.webp returned {len(img_bytes2)} bytes of image/webp.")

    print("\n=======================================================")
    print("ALL E2E INTEGRATION VERIFICATION CHECKS PASSED (EXIT 0)")
    print("=======================================================")


if __name__ == "__main__":
    main()
