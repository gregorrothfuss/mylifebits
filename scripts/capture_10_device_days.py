#!/usr/bin/env python3
"""
Captures on-device screenshots of 10 sequential days with photo summaries/notes
from Google Maps Timeline on the physical Pixel 8 via ADB.
"""

import os
import sys
import time
import subprocess
from pathlib import Path

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
ADB_BIN = str(WORKSPACE_DIR / "platform-tools" / "adb")
TARGET_DEVICE = "10.80.1.36:46219"
OUT_DIR = WORKSPACE_DIR / "scratch" / "device_proofs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

env = os.environ.copy()
env["ADB_MDNS"] = "0"
env["ADB_MDNS_OPENSCREEN"] = "0"

def adb_shell(cmd_args: list[str]):
    full_cmd = [ADB_BIN, "-s", TARGET_DEVICE, "shell"] + cmd_args
    subprocess.run(full_cmd, env=env, check=True)

def screencap(remote_path: str, local_path: Path):
    adb_shell(["screencap", "-p", remote_path])
    pull_cmd = [ADB_BIN, "-s", TARGET_DEVICE, "pull", remote_path, str(local_path)]
    subprocess.run(pull_cmd, env=env, check=True)

def step_forward():
    # Tap > chevron at x=925, y=1310
    adb_shell(["input", "tap", "925", "1310"])
    time.sleep(1.2)

def step_backward():
    # Tap < chevron at x=75, y=1310
    adb_shell(["input", "tap", "75", "1310"])
    time.sleep(1.2)

def main():
    print(f"[*] Starting on-device screenshot capture sequence on {TARGET_DEVICE}...")
    
    # We are currently on Sep 13, 2026.
    # First, navigate forward to Sep 15 (2 forward steps)
    print("[*] Navigating forward to Sep 15, 2026...")
    step_forward() # Sep 14
    step_forward() # Sep 15

    days = [
        "2026-09-15",
        "2026-09-14",
        "2026-09-13",
        "2026-09-12",
        "2026-09-11",
        "2026-09-10",
        "2026-09-09",
        "2026-09-08",
        "2026-09-07",
        "2026-09-06"
    ]

    for idx, d_str in enumerate(days):
        print(f"[*] Capturing day {idx+1}/10: {d_str}...")
        local_png = OUT_DIR / f"p8_day_{d_str.replace('-', '_')}.png"
        screencap(f"/sdcard/day_{d_str}.png", local_png)
        print(f"    Saved: {local_png}")
        if idx < len(days) - 1:
            step_backward()

    print("[✓] All 10 on-device screenshots captured successfully!")

if __name__ == "__main__":
    main()
