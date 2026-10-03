import os, sys, time, subprocess

WORKSPACE_DIR = os.getcwd()
ADB = os.path.join(WORKSPACE_DIR, 'platform-tools', 'adb')
SERIAL = os.environ.get("TARGET_SERIAL", "43151JEKB10775")

OUT_ODLH_DB = os.path.join(WORKSPACE_DIR, 'scratch', 'clean_build_v60', 'odlh-storage.db')
OUT_AUX_DB = os.path.join(WORKSPACE_DIR, 'scratch', 'clean_build_v60', 'aux-odlh-storage.db')
OUT_MYPLACES_DB = os.path.join(WORKSPACE_DIR, 'scratch', 'clean_build_v60', 'gmm_myplaces.db')
OUT_SYNC_DB = os.path.join(WORKSPACE_DIR, 'scratch', 'clean_build_v60', 'gmm_sync.db')
OUT_PLACES2_PATH = os.path.join(WORKSPACE_DIR, 'scratch', 'clean_build_v60', 'places_2')

def get_pixel_serial():
    res = subprocess.run([ADB, "devices", "-l"], capture_output=True, text=True)
    for line in res.stdout.strip().split("\n")[1:]:
        if "emulator" in line or not ("\tdevice" in line or " device " in line):
            continue
        dev_id = line.split()[0]
        if "43151JEKB10775" in line or "akita" in line or "10.80.1.36" in line:
            return dev_id
    # Default to SERIAL
    return SERIAL

SERIAL = get_pixel_serial()
print(f"[*] Target Pixel 8a serial: {SERIAL}")

def ensure_adb():
    res = subprocess.run([ADB, "devices"], capture_output=True, text=True)
    if "device" not in res.stdout:
        subprocess.run([ADB, "start-server"], capture_output=True)
        time.sleep(1)

ensure_adb()

print(f"[*] Pushing files to /sdcard/ on {SERIAL}...")
subprocess.run([ADB, "-s", SERIAL, "push", OUT_ODLH_DB, "/sdcard/odlh-storage.db"], check=True)
subprocess.run([ADB, "-s", SERIAL, "push", OUT_AUX_DB, "/sdcard/aux-odlh-storage.db"], check=True)
subprocess.run([ADB, "-s", SERIAL, "push", OUT_PLACES2_PATH, "/sdcard/places_2"], check=True)
subprocess.run([ADB, "-s", SERIAL, "push", OUT_SYNC_DB, "/sdcard/gmm_sync.db"], check=True)
subprocess.run([ADB, "-s", SERIAL, "push", OUT_MYPLACES_DB, "/sdcard/gmm_myplaces.db"], check=True)

deploy_cmd = """
am force-stop com.google.android.apps.maps
am force-stop com.google.android.gms
kill -9 $(pidof com.google.android.apps.maps com.google.android.gms com.google.android.gms.persistent) 2>/dev/null || true
sleep 1

cp /sdcard/places_2 /data/data/com.google.android.apps.maps/files/places/2
cp /sdcard/places_2 /data/data/com.google.android.apps.maps/app_places/places/2
cp /sdcard/places_2 /data/data/com.google.android.apps.maps/app_place_cache/places/2
mkdir -p /data/data/com.google.android.apps.maps/files/users/search/104819208193648646391/places/
cp /sdcard/places_2 /data/data/com.google.android.apps.maps/files/users/search/104819208193648646391/places/1
cp /sdcard/places_2 /data/data/com.google.android.apps.maps/files/users/search/104819208193648646391/places/2

cp /sdcard/gmm_sync.db /data/data/com.google.android.apps.maps/databases/gmm_sync.db
cp /sdcard/gmm_myplaces.db /data/data/com.google.android.apps.maps/databases/gmm_myplaces.db

rm -f /data/data/com.google.android.gms/databases/odlh* /data/data/com.google.android.gms/databases/aux*
rm -f /data/user/0/com.google.android.gms/databases/odlh* /data/user/0/com.google.android.gms/databases/aux*
rm -f /data/data/com.google.android.apps.maps/databases/odlh* /data/data/com.google.android.apps.maps/databases/aux*

cp /sdcard/odlh-storage.db /data/data/com.google.android.gms/databases/odlh-storage.db
cp /sdcard/odlh-storage.db /data/user/0/com.google.android.gms/databases/odlh-storage.db
cp /sdcard/aux-odlh-storage.db /data/data/com.google.android.gms/databases/aux-odlh-storage.db
cp /sdcard/aux-odlh-storage.db /data/user/0/com.google.android.gms/databases/aux-odlh-storage.db

cp /sdcard/odlh-storage.db /data/data/com.google.android.apps.maps/databases/odlh-storage.db
cp /sdcard/aux-odlh-storage.db /data/data/com.google.android.apps.maps/databases/aux-odlh-storage.db

GMM_UID=`stat -c '%U:%G' /data/data/com.google.android.apps.maps/files/places/2 2>/dev/null || echo 'u0_a207:u0_a207'`
GMS_UID=`stat -c '%U:%G' /data/data/com.google.android.gms/databases/odlh-storage.db 2>/dev/null || echo 'u0_a180:u0_a180'`

chown -R $GMM_UID /data/data/com.google.android.apps.maps/files/
chown -R $GMM_UID /data/data/com.google.android.apps.maps/databases/
chown -R $GMS_UID /data/data/com.google.android.gms/databases/

chmod 660 /data/data/com.google.android.apps.maps/files/places/* 2>/dev/null || true
chmod 660 /data/data/com.google.android.apps.maps/files/users/search/104819208193648646391/places/* 2>/dev/null || true
chmod 660 /data/data/com.google.android.apps.maps/databases/* 2>/dev/null || true
chmod 660 /data/data/com.google.android.gms/databases/odlh* 2>/dev/null || true
chmod 660 /data/data/com.google.android.gms/databases/aux* 2>/dev/null || true

rm -f /data/data/com.google.android.apps.maps/databases/gmm_storage.db*
rm -rf /data/data/com.google.android.apps.maps/cache/*
rm -rf /data/data/com.google.android.apps.maps/code_cache/*
rm -f /data/data/com.google.android.apps.maps/databases/*-wal /data/data/com.google.android.apps.maps/databases/*-shm
rm -f /data/data/com.google.android.gms/databases/*-wal /data/data/com.google.android.gms/databases/*-shm

restorecon -R /data/data/com.google.android.apps.maps/ 2>/dev/null || true
restorecon -R /data/data/com.google.android.gms/ 2>/dev/null || true
"""

print(f"[*] Executing su deployment on {SERIAL}...")
subprocess.run([ADB, "-s", SERIAL, "shell", f"su -c '{deploy_cmd}'"], check=True)
print("[✓] Deployed cleanly to Pixel 8a!")
