#!/usr/bin/env python3
import os
import sys
import time
import subprocess
from pathlib import Path

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
ADB = WORKSPACE_DIR / "platform-tools" / "adb"
SERIAL = "emulator-5554"

BUNDLE_DIR = WORKSPACE_DIR / "scratch" / "pixel8a_working_bundle"
OUT_ODLH_DB = BUNDLE_DIR / "odlh-storage.db"
OUT_AUX_DB = BUNDLE_DIR / "aux-odlh-storage.db"
OUT_MYPLACES_DB = BUNDLE_DIR / "gmm_myplaces.db"
OUT_SYNC_DB = BUNDLE_DIR / "gmm_sync.db"
OUT_PLACES2_PATH = BUNDLE_DIR / "places_2"
OUT_GELLER_DB = BUNDLE_DIR / "portable_geller_rothfuss@gmail.com.db"
CACHES_TAR = WORKSPACE_DIR / ".agent" / "scratch" / "semanticlocation_caches.tar.gz"

ENV = {
    "ADB_USB": "0",
    "ADB_MDNS": "0",
    "ADB_MDNS_AUTO_CONNECT": "0",
    **os.environ
}

def adb_cmd(args, **kwargs):
    return subprocess.run([str(ADB), "-s", SERIAL] + args, env=ENV, **kwargs)

def main():
    assert OUT_ODLH_DB.exists(), f"Missing {OUT_ODLH_DB}"
    assert CACHES_TAR.exists(), f"Missing {CACHES_TAR}"
    print(f"[*] Deploying Pixel 8a working bundle (8,547 visited places) to {SERIAL}...")

    adb_cmd(["push", str(OUT_ODLH_DB), "/sdcard/odlh-storage.db"], check=True)
    adb_cmd(["push", str(OUT_AUX_DB), "/sdcard/aux-odlh-storage.db"], check=True)
    adb_cmd(["push", str(OUT_PLACES2_PATH), "/sdcard/places_2"], check=True)
    adb_cmd(["push", str(OUT_SYNC_DB), "/sdcard/gmm_sync.db"], check=True)
    adb_cmd(["push", str(OUT_MYPLACES_DB), "/sdcard/gmm_myplaces.db"], check=True)
    adb_cmd(["push", str(OUT_GELLER_DB), "/sdcard/portable_geller_rothfuss@gmail.com.db"], check=True)
    adb_cmd(["push", str(CACHES_TAR), "/sdcard/semanticlocation_caches.tar.gz"], check=True)

    deploy_cmd = """
am force-stop com.google.android.apps.maps
am force-stop com.google.android.gms

MAPS_UID=$(pm list packages -U | grep "package:com.google.android.apps.maps " | cut -d: -f3)
GMS_UID=$(pm list packages -U | grep "package:com.google.android.gms " | cut -d: -f3)
[ -z "$MAPS_UID" ] && MAPS_UID=10192
[ -z "$GMS_UID" ] && GMS_UID=10128

echo "Installing with MAPS_UID=$MAPS_UID, GMS_UID=$GMS_UID"

# 1. Places Cache
mkdir -p /data/data/com.google.android.apps.maps/files/places
mkdir -p /data/data/com.google.android.apps.maps/app_place_cache/places
cp /sdcard/places_2 /data/data/com.google.android.apps.maps/files/places/2
cp /sdcard/places_2 /data/data/com.google.android.apps.maps/app_place_cache/places/2

# 2. Maps Databases
mkdir -p /data/data/com.google.android.apps.maps/databases
cp /sdcard/odlh-storage.db /data/data/com.google.android.apps.maps/databases/odlh-storage.db
cp /sdcard/aux-odlh-storage.db /data/data/com.google.android.apps.maps/databases/aux-odlh-storage.db
cp /sdcard/gmm_myplaces.db /data/data/com.google.android.apps.maps/databases/gmm_myplaces.db
cp /sdcard/gmm_sync.db /data/data/com.google.android.apps.maps/databases/gmm_sync.db
cp /sdcard/portable_geller_rothfuss@gmail.com.db /data/data/com.google.android.apps.maps/databases/portable_geller_rothfuss@gmail.com.db

# 3. GMS Databases
mkdir -p /data/data/com.google.android.gms/databases
mkdir -p /data/user_de/0/com.google.android.gms/databases
cp /sdcard/odlh-storage.db /data/data/com.google.android.gms/databases/odlh-storage.db
cp /sdcard/aux-odlh-storage.db /data/data/com.google.android.gms/databases/aux-odlh-storage.db
cp /sdcard/odlh-storage.db /data/user_de/0/com.google.android.gms/databases/odlh-storage.db
cp /sdcard/aux-odlh-storage.db /data/user_de/0/com.google.android.gms/databases/aux-odlh-storage.db

# 4. GMS SemanticLocation Caches
tar -xzf /sdcard/semanticlocation_caches.tar.gz -C /data/data/com.google.android.gms/

# 5. Clean out ephemeral WAL logs and corrupted storage
rm -f /data/data/com.google.android.apps.maps/databases/*-wal /data/data/com.google.android.apps.maps/databases/*-shm
rm -f /data/data/com.google.android.gms/databases/*-wal /data/data/com.google.android.gms/databases/*-shm
rm -f /data/user_de/0/com.google.android.gms/databases/*-wal /data/user_de/0/com.google.android.gms/databases/*-shm
rm -f /data/data/com.google.android.apps.maps/databases/gmm_storage.db*
rm -f /data/data/com.google.android.apps.maps/databases/da_storage.db*

# 6. Permissions and Ownership
chown -R ${MAPS_UID}:${MAPS_UID} /data/data/com.google.android.apps.maps/files/places/
chown -R ${MAPS_UID}:${MAPS_UID} /data/data/com.google.android.apps.maps/app_place_cache/
chown -R ${MAPS_UID}:${MAPS_UID} /data/data/com.google.android.apps.maps/databases/
chown -R ${GMS_UID}:${GMS_UID} /data/data/com.google.android.gms/databases/odlh*
chown -R ${GMS_UID}:${GMS_UID} /data/user_de/0/com.google.android.gms/databases/odlh*
chown -R ${GMS_UID}:${GMS_UID} /data/data/com.google.android.gms/app_semanticlocation*

chmod 660 /data/data/com.google.android.apps.maps/files/places/2
chmod 660 /data/data/com.google.android.apps.maps/app_place_cache/places/2
chmod 660 /data/data/com.google.android.apps.maps/databases/*
chmod 660 /data/data/com.google.android.gms/databases/odlh*
chmod 660 /data/user_de/0/com.google.android.gms/databases/odlh*
chmod -R 770 /data/data/com.google.android.gms/app_semanticlocation*

restorecon -R /data/data/com.google.android.apps.maps/ 2>/dev/null || true
restorecon -R /data/data/com.google.android.gms/ 2>/dev/null || true
restorecon -R /data/user_de/0/com.google.android.gms/ 2>/dev/null || true

rm -f /sdcard/odlh-storage.db /sdcard/aux-odlh-storage.db /sdcard/places_2 /sdcard/gmm_sync.db /sdcard/gmm_myplaces.db /sdcard/portable_geller* /sdcard/semanticlocation_caches.tar.gz
echo "Deployment finished!"
"""

    print("[*] Executing deployment shell commands inside VM...")
    res = subprocess.run([str(ADB), "-s", SERIAL, "shell"], input=deploy_cmd, capture_output=True, text=True, env=ENV)
    print("  [Output]:", res.stdout.strip())
    if res.returncode != 0:
        print(f"  [!] Error: {res.stderr}")
        sys.exit(1)

    print("[*] Starting Google Maps Timeline...")
    adb_cmd(["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", "https://www.google.com/maps/timeline", "-p", "com.google.android.apps.maps"], check=True)
    time.sleep(3)

    print("[✓] Deployed Pixel 8a working bundle to emulator!")

if __name__ == "__main__":
    main()
