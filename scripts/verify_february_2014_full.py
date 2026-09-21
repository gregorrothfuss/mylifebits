import os, sys, subprocess, time

WORKSPACE_DIR = '/Users/rothfuss/Documents/antigravity/gregor-mylifebits'
ARTIFACT_DIR = '/Users/rothfuss/.gemini/antigravity/brain/af2352af-830e-4cd4-9dfd-8f765759d408'
MEDIA_DIR = os.path.join(ARTIFACT_DIR, 'media_feb2014')
os.makedirs(MEDIA_DIR, exist_ok=True)

ADB = os.path.join(WORKSPACE_DIR, 'platform-tools', 'adb')
SERIAL = '192.168.1.36:5555'

CLEANED_DB = os.path.join(WORKSPACE_DIR, 'scratch', 'odlh_master_pure.db')
AUX_DB = os.path.join(WORKSPACE_DIR, 'scratch', 'aux-odlh-storage.db')
OUT_PLACES2 = os.path.join(WORKSPACE_DIR, 'scratch', 'places_2_pure')
OUT_SYNC_DB = os.path.join(WORKSPACE_DIR, 'scratch', 'gmm_sync_pure.db')
OUT_MYPLACES_DB = os.path.join(WORKSPACE_DIR, 'scratch', 'gmm_myplaces_pure.db')

FEB_DAYS = [f"2014-02-{d:02d}" for d in range(1, 29)]

def adb_shell(cmd_list):
    return subprocess.run([ADB, '-s', SERIAL, 'shell'] + cmd_list, check=True, capture_output=True, text=True)

def deploy_cleaned_dataset():
    print("[*] DEPLOYING CLEANED MASTER DATASET TO PIXEL 8...")
    subprocess.run([ADB, '-s', SERIAL, 'push', CLEANED_DB, '/sdcard/odlh-storage.db'], check=True, capture_output=True)
    subprocess.run([ADB, '-s', SERIAL, 'push', AUX_DB, '/sdcard/aux-odlh-storage.db'], check=True, capture_output=True)
    subprocess.run([ADB, '-s', SERIAL, 'push', OUT_PLACES2, '/sdcard/places_2'], check=True, capture_output=True)
    subprocess.run([ADB, '-s', SERIAL, 'push', OUT_SYNC_DB, '/sdcard/gmm_sync.db'], check=True, capture_output=True)
    subprocess.run([ADB, '-s', SERIAL, 'push', OUT_MYPLACES_DB, '/sdcard/gmm_myplaces.db'], check=True, capture_output=True)

    deploy_cmd = """
am force-stop com.google.android.apps.maps
am force-stop com.google.android.gms

cp /sdcard/places_2 /data/data/com.google.android.apps.maps/files/places/2
cp /sdcard/places_2 /data/data/com.google.android.apps.maps/app_places/places/2
cp /sdcard/places_2 /data/data/com.google.android.apps.maps/app_place_cache/places/2

cp /sdcard/gmm_sync.db /data/data/com.google.android.apps.maps/databases/gmm_sync.db
cp /sdcard/gmm_myplaces.db /data/data/com.google.android.apps.maps/databases/gmm_myplaces.db
cp /sdcard/odlh-storage.db /data/data/com.google.android.apps.maps/databases/odlh-storage.db
cp /sdcard/aux-odlh-storage.db /data/data/com.google.android.apps.maps/databases/aux-odlh-storage.db
cp /sdcard/odlh-storage.db /data/data/com.google.android.gms/databases/odlh-storage.db
cp /sdcard/odlh-storage.db /data/user/0/com.google.android.gms/databases/odlh-storage.db

chown -R u0_a207:u0_a207 /data/data/com.google.android.apps.maps/files/places/
chown -R u0_a207:u0_a207 /data/data/com.google.android.apps.maps/databases/
chown -R u0_a180:u0_a180 /data/data/com.google.android.gms/databases/

chmod 660 /data/data/com.google.android.apps.maps/files/places/2
chmod 660 /data/data/com.google.android.apps.maps/databases/*
chmod 660 /data/data/com.google.android.gms/databases/odlh*

rm -f /data/data/com.google.android.apps.maps/databases/*-wal /data/data/com.google.android.apps.maps/databases/*-shm
rm -f /data/data/com.google.android.gms/databases/*-wal /data/data/com.google.android.gms/databases/*-shm

restorecon -R /data/data/com.google.android.apps.maps/ 2>/dev/null || true
restorecon -R /data/data/com.google.android.gms/ 2>/dev/null || true
"""
    subprocess.run([ADB, '-s', SERIAL, 'shell', f'cat << \"EOF\" > /sdcard/deploy_clean.sh\n{deploy_cmd}\nEOF'], check=True)
    subprocess.run([ADB, '-s', SERIAL, 'shell', 'su', '-c', 'sh /sdcard/deploy_clean.sh'], check=True)
    print("[✓] Deployed Cleaned Master dataset successfully.")

def navigate_to_feb_1_2014():
    print("[*] Launching Maps Timeline and navigating to Feb 1, 2014...")
    subprocess.run([ADB, '-s', SERIAL, 'shell', 'su', '-c', 'am start -a android.intent.action.VIEW -d https://www.google.com/maps/timeline com.google.android.apps.maps'], check=True)
    time.sleep(5.0)

    # Tap date bar to open calendar modal
    adb_shell(['input', 'tap', '480', '1310'])
    time.sleep(1.5)

    # Tap year header at (150, 600)
    adb_shell(['input', 'tap', '150', '600'])
    time.sleep(1.5)

    # Drag year wheel down 3 times to 2014
    for _ in range(3):
        adb_shell(['input', 'swipe', '500', '1200', '500', '1680', '1000'])
        time.sleep(0.5)
    time.sleep(0.5)

    # Tap 2014 at (500, 1270)
    adb_shell(['input', 'tap', '500', '1270'])
    time.sleep(1.2)

    # Step back 7 months (September 2014 -> February 2014)
    for _ in range(7):
        adb_shell(['input', 'tap', '110', '880'])
        time.sleep(0.2)
    time.sleep(1.0)

    # Tap Saturday, Feb 1, 2014 (In Feb 2014, Feb 1 is Saturday, first row last column: ~880, 1050)
    adb_shell(['input', 'tap', '880', '1050'])
    time.sleep(3.0)

    # Pull bottom sheet up slightly
    adb_shell(['input', 'swipe', '500', '2250', '500', '1400', '300'])
    time.sleep(1.0)

def capture_all_feb_days(prefix="cleaned"):
    print(f"[*] Capturing all 28 days of February 2014 ({prefix})...")
    for idx, day_str in enumerate(FEB_DAYS):
        dev_path = f"/sdcard/{prefix}_{day_str}.png"
        local_path = os.path.join(MEDIA_DIR, f"{day_str}_{prefix}.png")
        adb_shell(['screencap', '-p', dev_path])
        subprocess.run([ADB, '-s', SERIAL, 'pull', dev_path, local_path], check=True, capture_output=True)
        print(f"  [{idx+1}/28] Captured {day_str} ({prefix}) -> {local_path}")
        if idx < len(FEB_DAYS) - 1:
            adb_shell(['input', 'swipe', '850', '1600', '250', '1600', '150'])
            time.sleep(2.0)
    print(f"[✓] ALL 28 DAYS OF FEBRUARY 2014 CAPTURED ({prefix})!")

def main():
    deploy_cleaned_dataset()
    navigate_to_feb_1_2014()
    capture_all_feb_days("cleaned")

if __name__ == '__main__':
    main()
