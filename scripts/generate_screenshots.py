#!/usr/bin/env python3
"""
Automated Screenshot Generator for Documentation & GitHub README.
Uses Playwright to capture pixel-perfect, privacy-compliant screenshots:
1. Daily Timeline View (Arches & Capitol Reef National Parks, Utah)
2. Transcontinental Flight & Excursion (Yucatan, Mexico to Newark)
3. Universal Global Search (Searching National Parks across the world)
All screenshots strictly exclude personal homes and people.
"""

import os
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT_DIR / "docs" / "screenshots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = os.environ.get("BASE_URL", "https://mylifebits.local")


def optimize_image(src_path: Path, max_width: int = 1440) -> None:
    """Resizes and compresses PNG image for high fidelity and small file size."""
    with Image.open(src_path) as img:
        img = img.convert("RGB")
        if img.width > max_width:
            ratio = max_width / float(img.width)
            new_height = int(float(img.height) * ratio)
            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
        img.save(src_path, format="PNG", optimize=True)


def main() -> None:
    print("[*] Launching headless browser for documentation screenshots...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            headless=True,
            args=["--ignore-certificate-errors", "--disable-gpu"],
        )

        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        # 1. Timeline Day View: Arches National Park (2010-11-22)
        print("    [1/3] Capturing Timeline Day View (Arches & Capitol Reef)...")
        page.goto(f"{BASE_URL}/?date=2010-11-22")
        page.wait_for_timeout(3500)
        shot1 = OUTPUT_DIR / "timeline_day_view.png"
        page.screenshot(path=str(shot1))
        optimize_image(shot1)

        # 2. Transcontinental Flight & Trip (2017-01-14)
        print("    [2/3] Capturing Transcontinental Flight & Travel Day (Yucatan to Newark)...")
        page.goto(f"{BASE_URL}/?date=2017-01-14")
        page.wait_for_timeout(3500)
        shot2 = OUTPUT_DIR / "timeline_flight_trip.png"
        page.screenshot(path=str(shot2))
        optimize_image(shot2)

        # 3. Universal Global Search Dropdown
        print("    [3/3] Capturing Universal Global Search (National Park query)...")
        page.goto(f"{BASE_URL}/?date=2010-11-22")
        page.wait_for_timeout(2500)
        page.click("#global-search-input")
        page.fill("#global-search-input", "National Park")
        page.wait_for_selector("#global-search-dropdown .search-result-item", timeout=6000)
        page.wait_for_timeout(1000)
        shot3 = OUTPUT_DIR / "universal_search.png"
        page.screenshot(path=str(shot3))
        optimize_image(shot3)

        browser.close()

    print("[✓] All screenshots generated successfully in docs/screenshots/:")
    for f in [shot1, shot2, shot3]:
        size_kb = f.stat().st_size / 1024.0
        print(f"    - {f.name} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
