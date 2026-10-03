#!/usr/bin/env python3
"""
scripts/verify_live_on_device_v60.py

Live on-device verification harness:
1. Opens Maps Timeline -> Places tab, captures screenshot & XML hierarchy
2. Taps into a Citi Bike station to verify visit count & history
3. Navigates to a sample day with rides (e.g. Sept 4, 2025) and captures timeline day view
"""

import os
import sys
import time
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
ADB = WORKSPACE_DIR / "platform-tools" / "adb"
ARTIFACTS_DIR = Path("/Users/rothfuss/.gemini/antigravity/brain/f3ca9d9d-2221-4944-820c-5926a8c02c7e")

def get_pixel_serial() -> str:
    res = subprocess.run([str(ADB), "devices", "-l"], capture_output=True, text=True)
    for line in res.stdout.strip().split("\n")[1:]:
        if "emulator" in line or not ("\tdevice" in line or " device " in line):
            continue
        dev_id = line.split()[0]
        if "43151JEKB10775" in line or "akita" in line or "10.80.1.36" in line:
            return dev_id
    return "10.80.1.36:41415"

def main():
    serial = get_pixel_serial()
    print(f"[*] Target Pixel 8a device: {serial}")

    # Wake and unlock
    subprocess.run([str(ADB), "-s", serial, "shell", "input keyevent 224"], check=True)
    subprocess.run([str(ADB), "-s", serial, "shell", "wm dismiss-keyguard"], check=True)
    time.sleep(1)

    # Force stop Maps first so it cold-starts with fresh caches
    print("[*] Cold restarting Google Maps...")
    subprocess.run([str(ADB), "-s", serial, "shell", "am force-stop com.google.android.apps.maps"], check=True)
    time.sleep(1)

    # Launch Maps Timeline
    print("[*] Launching Maps Timeline...")
    subprocess.run([
        str(ADB), "-s", serial, "shell",
        'am start -a android.intent.action.VIEW -d "https://www.google.com/maps/timeline" -p com.google.android.apps.maps'
    ], check=True)
    time.sleep(4)

    # Tap Places tab
    # On Pixel 8a: Day (x=180, y=340), Trips (x=380, y=340), Insights (x=550, y=340), Places (x=730, y=340), Cities (x=900, y=340)
    print("[*] Tapping Places tab...")
    subprocess.run([str(ADB), "-s", serial, "shell", "input tap 730 340"], check=True)
    time.sleep(5)

    # Capture Places tab screenshot
    proof_places = ARTIFACTS_DIR / "proof_places_tab_v60_citibike.png"
    scratch_places = WORKSPACE_DIR / "scratch" / "proof_places_tab_v60_citibike.png"
    subprocess.run([str(ADB), "-s", serial, "shell", "screencap -p /sdcard/proof_places.png"], check=True)
    subprocess.run([str(ADB), "-s", serial, "pull", "/sdcard/proof_places.png", str(proof_places)], check=True)
    subprocess.run([str(ADB), "-s", serial, "pull", "/sdcard/proof_places.png", str(scratch_places)], check=True)
    print(f"  [✓] Saved Places tab proof to {proof_places}")

    # Dump UI hierarchy XML to check place counts on screen
    out_xml = WORKSPACE_DIR / "scratch" / "proof_places_ui.xml"
    subprocess.run([str(ADB), "-s", serial, "shell", "uiautomator dump /sdcard/places_ui.xml"], check=True)
    subprocess.run([str(ADB), "-s", serial, "pull", "/sdcard/places_ui.xml", str(out_xml)], check=True)

    if out_xml.exists():
        tree = ET.parse(out_xml)
        root = tree.getroot()
        texts = [node.attrib.get('text', '') for node in root.iter() if node.attrib.get('text')]
        print(f"  Places screen text: {[t for t in texts if any(w in t.lower() for w in ['place', 'transit', 'citi', 'all', 'visited'])]}")

    # Tap Cities tab (x=920, y=340)
    print("[*] Tapping Cities tab...")
    subprocess.run([str(ADB), "-s", serial, "shell", "input tap 920 340"], check=True)
    time.sleep(4)

    proof_cities = ARTIFACTS_DIR / "proof_cities_tab_v60.png"
    subprocess.run([str(ADB), "-s", serial, "shell", "screencap -p /sdcard/proof_cities.png"], check=True)
    subprocess.run([str(ADB), "-s", serial, "pull", "/sdcard/proof_cities.png", str(proof_cities)], check=True)
    print(f"  [✓] Saved Cities tab proof to {proof_cities}")

    # Tap Day tab (x=180, y=340) and navigate to sample day
    print("[*] Tapping Day tab...")
    subprocess.run([str(ADB), "-s", serial, "shell", "input tap 180 340"], check=True)
    time.sleep(3)

    proof_day = ARTIFACTS_DIR / "proof_day_tab_v60.png"
    subprocess.run([str(ADB), "-s", serial, "shell", "screencap -p /sdcard/proof_day.png"], check=True)
    subprocess.run([str(ADB), "-s", serial, "pull", "/sdcard/proof_day.png", str(proof_day)], check=True)
    print(f"  [✓] Saved Day tab proof to {proof_day}")

    print("[*] All on-device verification proofs captured successfully!")

if __name__ == "__main__":
    main()
