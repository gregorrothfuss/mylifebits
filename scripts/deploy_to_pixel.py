import os, sys, time, subprocess
from pathlib import Path

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
ADB = WORKSPACE_DIR / "platform-tools" / "adb"

OUT_ODLH_DB = WORKSPACE_DIR / "scratch" / "clean_build_v60" / "odlh-storage.db"
OUT_AUX_DB = WORKSPACE_DIR / "scratch" / "clean_build_v60" / "aux-odlh-storage.db"
OUT_MYPLACES_DB = WORKSPACE_DIR / "scratch" / "clean_build_v60" / "gmm_myplaces.db"
OUT_SYNC_DB = WORKSPACE_DIR / "scratch" / "clean_build_v60" / "gmm_sync.db"
OUT_PLACES2_PATH = WORKSPACE_DIR / "scratch" / "clean_build_v60" / "places_2"

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
    assert OUT_ODLH_DB.exists(), f"Missing {OUT_ODLH_DB}"
    assert OUT_AUX_DB.exists(), f"Missing {OUT_AUX_DB}"
    assert OUT_MYPLACES_DB.exists(), f"Missing {OUT_MYPLACES_DB}"
    assert OUT_SYNC_DB.exists(), f"Missing {OUT_SYNC_DB}"
    assert OUT_PLACES2_PATH.exists(), f"Missing {OUT_PLACES2_PATH}"

    serial = get_pixel_serial()
    print(f"[*] Target Pixel 8a serial: {serial}")

    print(f"[*] Pushing files to /sdcard/ on {serial}...")
    subprocess.run([str(ADB), "-s", serial, "push", str(OUT_ODLH_DB), "/sdcard/odlh-storage.db"], check=True)
    subprocess.run([str(ADB), "-s", serial, "push", str(OUT_AUX_DB), "/sdcard/aux-odlh-storage.db"], check=True)
    subprocess.run([str(ADB), "-s", serial, "push", str(OUT_PLACES2_PATH), "/sdcard/places_2"], check=True)
    subprocess.run([str(ADB), "-s", serial, "push", str(OUT_SYNC_DB), "/sdcard/gmm_sync.db"], check=True)
    subprocess.run([str(ADB), "-s", serial, "push", str(OUT_MYPLACES_DB), "/sdcard/gmm_myplaces.db"], check=True)

    deploy_cmd = """
am force-stop com.google.android.apps.maps
am force-stop com.google.android.gms
sleep 1

MAPS_UID=$(stat -c '%u:%g' /data/data/com.google.android.apps.maps/databases 2>/dev/null || echo '10207:10207')
GMS_UID=$(stat -c '%u:%g' /data/data/com.google.android.gms/databases 2>/dev/null || echo '10180:10180')

echo "Installing with MAPS_UID=$MAPS_UID, GMS_UID=$GMS_UID"

mkdir -p /data/data/com.google.android.apps.maps/app_place_cache/places
mkdir -p /data/data/com.google.android.apps.maps/files/places

cp /sdcard/places_2 /data/data/com.google.android.apps.maps/app_place_cache/places/2
cp /sdcard/places_2 /data/data/com.google.android.apps.maps/files/places/2

cp /sdcard/gmm_sync.db /data/data/com.google.android.apps.maps/databases/gmm_sync.db
cp /sdcard/gmm_myplaces.db /data/data/com.google.android.apps.maps/databases/gmm_myplaces.db

cp /sdcard/odlh-storage.db /data/data/com.google.android.apps.maps/databases/odlh-storage.db
cp /sdcard/aux-odlh-storage.db /data/data/com.google.android.apps.maps/databases/aux-odlh-storage.db

cp /sdcard/odlh-storage.db /data/data/com.google.android.gms/databases/odlh-storage.db
cp /sdcard/aux-odlh-storage.db /data/data/com.google.android.gms/databases/aux-odlh-storage.db

if [ -d /data/user_de/0/com.google.android.gms/databases ]; then
    cp /sdcard/odlh-storage.db /data/user_de/0/com.google.android.gms/databases/odlh-storage.db
    cp /sdcard/aux-odlh-storage.db /data/user_de/0/com.google.android.gms/databases/aux-odlh-storage.db
    chown -R $GMS_UID /data/user_de/0/com.google.android.gms/databases/odlh*
fi

rm -f /data/data/com.google.android.apps.maps/databases/gmm_storage.db*
rm -f /data/data/com.google.android.apps.maps/databases/da_storage.db*
rm -f /data/data/com.google.android.apps.maps/databases/*-wal /data/data/com.google.android.apps.maps/databases/*-shm
rm -f /data/data/com.google.android.gms/databases/*-wal /data/data/com.google.android.gms/databases/*-shm

chown -R $MAPS_UID /data/data/com.google.android.apps.maps/databases/
chown -R $MAPS_UID /data/data/com.google.android.apps.maps/files/
chown -R $MAPS_UID /data/data/com.google.android.apps.maps/app_place_cache/
chown -R $GMS_UID /data/data/com.google.android.gms/databases/

chmod 660 /data/data/com.google.android.gms/databases/*
chmod 660 /data/data/com.google.android.apps.maps/databases/*
chmod 600 /data/data/com.google.android.apps.maps/app_place_cache/places/2

restorecon -R /data/data/com.google.android.apps.maps
restorecon -R /data/data/com.google.android.gms/databases

rm -f /sdcard/odlh-storage.db /sdcard/aux-odlh-storage.db /sdcard/places_2 /sdcard/gmm_sync.db /sdcard/gmm_myplaces.db
echo "Clean deployment finished!"
"""

    print(f"[*] Executing su deployment on {serial}...")
    subprocess.run([str(ADB), "-s", serial, "shell", f"su -c '{deploy_cmd}'"], check=True)
    print("[✓] Deployed cleanly to Pixel 8a!")

if __name__ == "__main__":
    main()
