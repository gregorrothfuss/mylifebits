import os, sys, time, subprocess

WORKSPACE_DIR = os.getcwd()
ADB = os.path.join(WORKSPACE_DIR, 'platform-tools', 'adb')
SERIAL = "emulator-5554"

def adb_cmd(args, **kwargs):
    return subprocess.run([ADB, "-s", SERIAL] + args, **kwargs)

OUT_ODLH_DB = os.path.join(WORKSPACE_DIR, 'scratch', 'odlh_master_pure.db')
OUT_AUX_DB = os.path.join(WORKSPACE_DIR, 'scratch', 'aux-odlh-storage.db')
OUT_MYPLACES_DB = os.path.join(WORKSPACE_DIR, 'scratch', 'gmm_myplaces_pure.db')
OUT_SYNC_DB = os.path.join(WORKSPACE_DIR, 'scratch', 'gmm_sync_pure.db')
OUT_PLACES2_PATH = os.path.join(WORKSPACE_DIR, 'scratch', 'places_2_pure')

print(f"[*] Deploying to Android VM Emulator: {SERIAL}...")

# 1. Push files to /sdcard/
print("  [1/4] Pushing files to /sdcard/...")
adb_cmd(["push", OUT_ODLH_DB, "/sdcard/odlh-storage.db"], check=True)
adb_cmd(["push", OUT_AUX_DB, "/sdcard/aux-odlh-storage.db"], check=True)
adb_cmd(["push", OUT_PLACES2_PATH, "/sdcard/places_2"], check=True)
adb_cmd(["push", OUT_SYNC_DB, "/sdcard/gmm_sync.db"], check=True)
adb_cmd(["push", OUT_MYPLACES_DB, "/sdcard/gmm_myplaces.db"], check=True)

# 2. Deploy script inside VM
deploy_cmd = """
am force-stop com.google.android.apps.maps

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
chmod 660 /data/user/0/com.google.android.gms/databases/odlh*

rm -f /data/data/com.google.android.apps.maps/databases/*-wal /data/data/com.google.android.apps.maps/databases/*-shm
rm -f /data/data/com.google.android.gms/databases/*-wal /data/data/com.google.android.gms/databases/*-shm
rm -f /data/user/0/com.google.android.gms/databases/*-wal /data/user/0/com.google.android.gms/databases/*-shm

restorecon -R /data/data/com.google.android.apps.maps/ 2>/dev/null || true
restorecon -R /data/data/com.google.android.gms/ 2>/dev/null || true
restorecon -R /data/user/0/com.google.android.gms/ 2>/dev/null || true
"""

print("  [2/4] Executing deployment commands via adb shell...")
res = subprocess.run([ADB, "-s", "emulator-5554", "shell"], input=deploy_cmd, capture_output=True, text=True)
if res.returncode != 0:
    print(f"  [!] Deployment shell error: {res.stderr}")
    sys.exit(1)

print("  [3/4] Starting Google Maps...")
subprocess.run([ADB, "-s", "emulator-5554", "shell", "am", "start", "-n", "com.google.android.apps.maps/com.google.android.maps.MapsActivity"], check=True)
time.sleep(3)

print("  [4/4] Opening Timeline...")
subprocess.run([ADB, "-s", "emulator-5554", "shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", "https://www.google.com/maps/timeline"], check=True)
time.sleep(2)

print("[✓] Master Database deployed cleanly to Android VM (emulator-5554)!")
