#!/usr/bin/env python3
"""
deploy_master_v55.py - Deploy v55 flawless master timeline & places catalogs to Android emulator/device.
"""

import os
import sys
import time
import subprocess
from pathlib import Path

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
ADB = WORKSPACE_DIR / "platform-tools" / "adb"

OUT_ODLH_DB = WORKSPACE_DIR / "scratch" / "odlh_v55_flawless.db"
OUT_AUX_DB = WORKSPACE_DIR / "scratch" / "aux-odlh-storage.db"
OUT_MYPLACES_DB = WORKSPACE_DIR / "scratch" / "gmm_myplaces_v55.db"
OUT_SYNC_DB = WORKSPACE_DIR / "scratch" / "gmm_sync_v55.db"
OUT_PLACES2_PATH = WORKSPACE_DIR / "scratch" / "places_2_v55"

def get_devices():
    res = subprocess.run([str(ADB), "devices"], capture_output=True, text=True, check=True)
    devices = []
    for line in res.stdout.strip().split("\n")[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices

def deploy_to_device(serial: str):
    print(f"\n[*] Deploying v55 Master to target: {serial}")

    # 1. Push files to /sdcard/
    print("  [1/4] Pushing compiled databases and catalogs to /sdcard/...")
    subprocess.run([str(ADB), "-s", serial, "push", str(OUT_ODLH_DB), "/sdcard/odlh-storage.db"], check=True)
    subprocess.run([str(ADB), "-s", serial, "push", str(OUT_AUX_DB), "/sdcard/aux-odlh-storage.db"], check=True)
    subprocess.run([str(ADB), "-s", serial, "push", str(OUT_PLACES2_PATH), "/sdcard/places_2"], check=True)
    subprocess.run([str(ADB), "-s", serial, "push", str(OUT_SYNC_DB), "/sdcard/gmm_sync.db"], check=True)
    subprocess.run([str(ADB), "-s", serial, "push", str(OUT_MYPLACES_DB), "/sdcard/gmm_myplaces.db"], check=True)

    # 2. Deploy script inside device/VM
    deploy_cmd = """
am force-stop com.google.android.apps.maps
am force-stop com.google.android.gms

mkdir -p /data/data/com.google.android.apps.maps/databases
mkdir -p /data/data/com.google.android.apps.maps/files/places
mkdir -p /data/data/com.google.android.apps.maps/app_places/places
mkdir -p /data/data/com.google.android.apps.maps/app_place_cache/places
mkdir -p /data/data/com.google.android.gms/databases
mkdir -p /data/user/0/com.google.android.gms/databases

cp /sdcard/places_2 /data/data/com.google.android.apps.maps/files/places/2
cp /sdcard/places_2 /data/data/com.google.android.apps.maps/app_places/places/2
cp /sdcard/places_2 /data/data/com.google.android.apps.maps/app_place_cache/places/2

cp /sdcard/gmm_sync.db /data/data/com.google.android.apps.maps/databases/gmm_sync.db
cp /sdcard/gmm_myplaces.db /data/data/com.google.android.apps.maps/databases/gmm_myplaces.db
cp /sdcard/odlh-storage.db /data/data/com.google.android.apps.maps/databases/odlh-storage.db
cp /sdcard/aux-odlh-storage.db /data/data/com.google.android.apps.maps/databases/aux-odlh-storage.db
cp /sdcard/odlh-storage.db /data/data/com.google.android.gms/databases/odlh-storage.db
cp /sdcard/odlh-storage.db /data/user/0/com.google.android.gms/databases/odlh-storage.db
cp /sdcard/aux-odlh-storage.db /data/data/com.google.android.gms/databases/aux-odlh-storage.db
cp /sdcard/aux-odlh-storage.db /data/user/0/com.google.android.gms/databases/aux-odlh-storage.db

GMM_UID=$(pm list packages -U | grep "com.google.android.apps.maps " | cut -d: -f3)
GMS_UID=$(pm list packages -U | grep "package:com.google.android.gms " | cut -d: -f3)
[ -z "$GMM_UID" ] && GMM_UID=10144
[ -z "$GMS_UID" ] && GMS_UID=10128

chown -R ${GMM_UID}:${GMM_UID} /data/data/com.google.android.apps.maps/files/
chown -R ${GMM_UID}:${GMM_UID} /data/data/com.google.android.apps.maps/app_places/
chown -R ${GMM_UID}:${GMM_UID} /data/data/com.google.android.apps.maps/app_place_cache/
chown -R ${GMM_UID}:${GMM_UID} /data/data/com.google.android.apps.maps/databases/
chown -R ${GMS_UID}:${GMS_UID} /data/data/com.google.android.gms/databases/
chown -R ${GMS_UID}:${GMS_UID} /data/user/0/com.google.android.gms/databases/

chmod 660 /data/data/com.google.android.apps.maps/files/places/2
chmod 660 /data/data/com.google.android.apps.maps/databases/*
chmod 660 /data/data/com.google.android.gms/databases/odlh*
chmod 660 /data/data/com.google.android.gms/databases/aux*
chmod 660 /data/user/0/com.google.android.gms/databases/odlh*
chmod 660 /data/user/0/com.google.android.gms/databases/aux*

rm -f /data/data/com.google.android.apps.maps/databases/*-wal /data/data/com.google.android.apps.maps/databases/*-shm
rm -f /data/data/com.google.android.gms/databases/*-wal /data/data/com.google.android.gms/databases/*-shm
rm -f /data/user/0/com.google.android.gms/databases/*-wal /data/user/0/com.google.android.gms/databases/*-shm

restorecon -R /data/data/com.google.android.apps.maps/ 2>/dev/null || true
restorecon -R /data/data/com.google.android.gms/ 2>/dev/null || true
restorecon -R /data/user/0/com.google.android.gms/ 2>/dev/null || true
"""

    print("  [2/4] Executing deployment commands...")
    # On rootable/emulator shell, run as root if possible
    res = subprocess.run([str(ADB), "-s", serial, "shell", "su 0 sh -c '" + deploy_cmd + "'"], capture_output=True, text=True)
    if res.returncode != 0:
        res = subprocess.run([str(ADB), "-s", serial, "shell"], input=deploy_cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"  [!] Deployment shell error: {res.stderr}")
        return False

    print("  [3/4] Launching Google Maps Activity...")
    subprocess.run([str(ADB), "-s", serial, "shell", "am", "start", "-n", "com.google.android.apps.maps/com.google.android.maps.MapsActivity"], check=True)
    time.sleep(3)

    print("  [4/4] Launching Timeline Intent...")
    subprocess.run([str(ADB), "-s", serial, "shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", "https://www.google.com/maps/timeline"], check=True)
    time.sleep(3)

    print(f"  [✓] v55 successfully deployed to {serial}!")
    return True

def main():
    devices = get_devices()
    if not devices:
        print("[!] No ADB devices found!")
        sys.exit(1)

    print(f"[*] Found {len(devices)} device(s): {devices}")
    # Target emulator-5554 (or first device)
    target = "emulator-5554" if "emulator-5554" in devices else devices[0]
    success = deploy_to_device(target)
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()
