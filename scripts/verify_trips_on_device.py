#!/usr/bin/env python3
"""
scripts/verify_trips_on_device.py

Verifies the Trips tab rendering on the physical Pixel 8a:
1. Wakes device, cold-starts Google Maps Timeline
2. Taps Trips tab (x=380, y=340)
3. Captures screenshot & UI XML hierarchy
4. Scrolls down and captures a second screenshot proving trips unroll
"""

import sys
import time
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
ADB = Path("/Users/rothfuss/Library/Android/sdk/platform-tools/adb")
if not ADB.exists():
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
    return "10.80.1.36:44739"

def main():
    serial = get_pixel_serial()
    print(f"[*] Target Pixel 8a serial: {serial}")

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
    time.sleep(5)

    # Tap Trips tab (x=380, y=340 on Pixel 8a)
    print("[*] Tapping Trips tab at (380, 340)...")
    subprocess.run([str(ADB), "-s", serial, "shell", "input tap 380 340"], check=True)
    time.sleep(5)

    # Capture initial Trips tab screenshot
    proof_trips = ARTIFACTS_DIR / "proof_trips_tab_verified.png"
    scratch_trips = WORKSPACE_DIR / "scratch" / "proof_trips_tab_verified.png"
    subprocess.run([str(ADB), "-s", serial, "shell", "screencap -p /sdcard/proof_trips.png"], check=True)
    subprocess.run([str(ADB), "-s", serial, "pull", "/sdcard/proof_trips.png", str(proof_trips)], check=True)
    subprocess.run([str(ADB), "-s", serial, "pull", "/sdcard/proof_trips.png", str(scratch_trips)], check=True)
    print(f"  [✓] Saved Trips tab proof to {proof_trips}")

    # Dump UI hierarchy XML to check trip elements on screen
    out_xml = WORKSPACE_DIR / "scratch" / "proof_trips_ui.xml"
    subprocess.run([str(ADB), "-s", serial, "shell", "uiautomator dump /sdcard/trips_ui.xml"], check=True)
    subprocess.run([str(ADB), "-s", serial, "pull", "/sdcard/trips_ui.xml", str(out_xml)], check=True)

    if out_xml.exists():
        tree = ET.parse(out_xml)
        root = tree.getroot()
        texts = [node.attrib.get('text', '') for node in root.iter() if node.attrib.get('text')]
        print(f"  Trips screen text: {[t for t in texts if t.strip()]}")

    # Scroll down on the trips list to show historical trips
    print("[*] Scrolling down on Trips list...")
    subprocess.run([str(ADB), "-s", serial, "shell", "input swipe 500 1500 500 500 300"], check=True)
    time.sleep(3)

    proof_trips_scrolled = ARTIFACTS_DIR / "proof_trips_tab_scrolled.png"
    subprocess.run([str(ADB), "-s", serial, "shell", "screencap -p /sdcard/proof_trips_scrolled.png"], check=True)
    subprocess.run([str(ADB), "-s", serial, "pull", "/sdcard/proof_trips_scrolled.png", str(proof_trips_scrolled)], check=True)
    print(f"  [✓] Saved scrolled Trips tab proof to {proof_trips_scrolled}")

    print("[*] Trips on-device verification finished successfully!")

if __name__ == "__main__":
    main()
