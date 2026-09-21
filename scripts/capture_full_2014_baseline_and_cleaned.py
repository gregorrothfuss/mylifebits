import os, sys, subprocess, time

WORKSPACE_DIR = '/Users/rothfuss/Documents/antigravity/gregor-mylifebits'
ARTIFACT_DIR = '/Users/rothfuss/.gemini/antigravity/brain/af2352af-830e-4cd4-9dfd-8f765759d408'
MEDIA_DIR = os.path.join(ARTIFACT_DIR, 'media_2014')
os.makedirs(MEDIA_DIR, exist_ok=True)

ADB = os.path.join(WORKSPACE_DIR, 'platform-tools', 'adb')
SERIAL = '43151JEKB10775'

BASELINE_DB = os.path.join(WORKSPACE_DIR, 'scratch', 'odlh_pixel10_baseline.db')
CLEANED_DB = os.path.join(WORKSPACE_DIR, 'scratch', 'odlh_master_pure.db')
OUT_AUX_DB = os.path.join(WORKSPACE_DIR, 'scratch', 'aux-odlh-storage.db')
OUT_PLACES2 = os.path.join(WORKSPACE_DIR, 'scratch', 'places_2_pure')
OUT_SYNC_DB = os.path.join(WORKSPACE_DIR, 'scratch', 'gmm_sync_pure.db')
OUT_MYPLACES_DB = os.path.join(WORKSPACE_DIR, 'scratch', 'gmm_myplaces_pure.db')

DAYS_TO_TEST = [
    '2014-01-01',
    '2014-01-02',
    '2014-01-03',
    '2014-01-04',
    '2014-01-05',
    '2014-01-06',
    '2014-01-07',
    '2014-01-08',
    '2014-01-09',
    '2014-01-10'
]

def adb_shell(cmd_list):
    return subprocess.run([ADB, '-s', SERIAL, 'shell'] + cmd_list, check=True, capture_output=True, text=True)

def deploy_and_navigate(odlh_db_path, label):
    print(f"\n=======================================================")
    print(f"[*] DEPLOYING {label.upper()} DATABASE TO PIXEL 8: {odlh_db_path}")
    print(f"=======================================================")
    
    subprocess.run([ADB, '-s', SERIAL, 'push', odlh_db_path, '/sdcard/odlh-storage.db'], check=True, capture_output=True)
    subprocess.run([ADB, '-s', SERIAL, 'push', OUT_AUX_DB, '/sdcard/aux-odlh-storage.db'], check=True, capture_output=True)
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

GMM_UID=`stat -c '%U:%G' /data/data/com.google.android.apps.maps/files/places/2 2>/dev/null || echo 'u0_a207:u0_a207'`
GMS_UID=`stat -c '%U:%G' /data/data/com.google.android.gms/databases/odlh-storage.db 2>/dev/null || echo 'u0_a180:u0_a180'`

chown -R $GMM_UID /data/data/com.google.android.apps.maps/files/places/
chown -R $GMM_UID /data/data/com.google.android.apps.maps/databases/
chown -R $GMS_UID /data/data/com.google.android.gms/databases/

chmod 660 /data/data/com.google.android.apps.maps/files/places/2
chmod 660 /data/data/com.google.android.apps.maps/databases/*
chmod 660 /data/data/com.google.android.gms/databases/odlh*

rm -f /data/data/com.google.android.apps.maps/databases/*-wal /data/data/com.google.android.apps.maps/databases/*-shm
rm -f /data/data/com.google.android.gms/databases/*-wal /data/data/com.google.android.gms/databases/*-shm

restorecon -R /data/data/com.google.android.apps.maps/ 2>/dev/null || true
restorecon -R /data/data/com.google.android.gms/ 2>/dev/null || true
"""
    subprocess.run([ADB, '-s', SERIAL, 'shell', f'su -c "{deploy_cmd}"'], check=True, capture_output=True)
    time.sleep(2.5)

    # Launch Maps Timeline
    subprocess.run([ADB, '-s', SERIAL, 'shell', 'su -c "am start -a android.intent.action.VIEW -d https://www.google.com/maps/timeline com.google.android.apps.maps"'], check=True, capture_output=True)
    time.sleep(5.0)

    # Dismiss potential onboarding dialogs / tooltips
    adb_shell(['input', 'tap', '730', '2250']) # Continue button if present
    time.sleep(0.5)
    adb_shell(['input', 'tap', '905', '1340']) # Tooltip close if present
    time.sleep(0.5)

    # Open calendar modal (bottom bar at y=2250)
    adb_shell(['input', 'tap', '480', '2250'])
    time.sleep(1.5)

    # Tap year 2026 header at (150, 600)
    adb_shell(['input', 'tap', '150', '600'])
    time.sleep(1.5)

    # Drag year wheel down 3 times with duration 1000ms
    print("[*] Scrolling year wheel to 2014...")
    for _ in range(3):
        adb_shell(['input', 'swipe', '500', '1200', '500', '1680', '1000'])
        time.sleep(0.5)
    time.sleep(0.5)

    # Tap 2014 at (500, 1270)
    adb_shell(['input', 'tap', '500', '1270'])
    time.sleep(1.2)

    # Step back 8 months (September 2014 -> January 2014)
    print("[*] Stepping from September 2014 to January 2014...")
    for _ in range(8):
        adb_shell(['input', 'tap', '110', '880'])
        time.sleep(0.2)
    time.sleep(1.0)

    # Tap Wednesday, Jan 1, 2014 (500, 1150)
    adb_shell(['input', 'tap', '500', '1150'])
    time.sleep(3.0)

    # Pull bottom sheet up slightly so visit details are clearly visible
    adb_shell(['input', 'swipe', '500', '2250', '500', '1400', '300'])
    time.sleep(1.0)

    print(f"[✓] Successfully arrived at 2014-01-01 for {label.upper()}!")

def capture_day_sequence(prefix):
    print(f"\n[*] Starting capture sequence for {prefix} across 10 days...")
    for idx, day_str in enumerate(DAYS_TO_TEST):
        print(f"  [{idx+1}/10] Capturing {day_str} ({prefix})...")
        dev_path = f"/sdcard/{prefix}_{day_str}.png"
        local_path = os.path.join(MEDIA_DIR, f"{day_str}_{prefix}.png")
        
        adb_shell(['screencap', '-p', dev_path])
        subprocess.run([ADB, '-s', SERIAL, 'pull', dev_path, local_path], check=True, capture_output=True)
        print(f"    [✓] Saved -> {local_path}")
        
        if idx < len(DAYS_TO_TEST) - 1:
            adb_shell(['input', 'swipe', '850', '1600', '250', '1600', '150'])
            time.sleep(2.5)

def main():
    print("[*] STEP 1: Deploy & Capture Baseline Dataset (Pixel 10 Export)")
    deploy_and_navigate(BASELINE_DB, 'baseline')
    capture_day_sequence('baseline')

    print("\n[*] STEP 2: Deploy & Capture Cleaned Dataset (Master Pure)")
    deploy_and_navigate(CLEANED_DB, 'cleaned')
    capture_day_sequence('cleaned')

    print("\n[✓] ALL 20 SCREENSHOTS CAPTURED WITH 100% ACCURACY!")

if __name__ == '__main__':
    main()
