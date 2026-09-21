import os, subprocess, time

WORKSPACE_DIR = '/Users/rothfuss/Documents/antigravity/gregor-mylifebits'
ARTIFACT_DIR = '/Users/rothfuss/.gemini/antigravity/brain/af2352af-830e-4cd4-9dfd-8f765759d408'
MEDIA_DIR = os.path.join(ARTIFACT_DIR, 'media_feb2014')
os.makedirs(MEDIA_DIR, exist_ok=True)

ADB = os.path.join(WORKSPACE_DIR, 'platform-tools', 'adb')
SERIAL = '192.168.1.36:5555'

BASELINE_DB = os.path.join(WORKSPACE_DIR, 'scratch', 'odlh_pixel10_baseline.db')
BASELINE_AUX = os.path.join(WORKSPACE_DIR, 'scratch', 'aux_pixel10_baseline.db')
OUT_PLACES2 = os.path.join(WORKSPACE_DIR, 'scratch', 'places_2_pure')

FEB_DAYS = [f"2014-02-{d:02d}" for d in range(1, 29)]

def adb_shell(cmd):
    subprocess.run([ADB, '-s', SERIAL, 'shell'] + cmd, check=True)

def deploy_baseline():
    print("[*] Deploying Authentic Baseline DB to Pixel 8...")
    subprocess.run([ADB, '-s', SERIAL, 'push', BASELINE_DB, '/sdcard/odlh-storage.db'], check=True, capture_output=True)
    subprocess.run([ADB, '-s', SERIAL, 'push', BASELINE_AUX, '/sdcard/aux-odlh-storage.db'], check=True, capture_output=True)
    subprocess.run([ADB, '-s', SERIAL, 'push', OUT_PLACES2, '/sdcard/places_2'], check=True, capture_output=True)

    deploy_cmd = """
am force-stop com.google.android.apps.maps
am force-stop com.google.android.gms

cp /sdcard/places_2 /data/data/com.google.android.apps.maps/files/places/2
cp /sdcard/places_2 /data/data/com.google.android.apps.maps/app_places/places/2
cp /sdcard/places_2 /data/data/com.google.android.apps.maps/app_place_cache/places/2

cp /sdcard/odlh-storage.db /data/data/com.google.android.apps.maps/databases/odlh-storage.db
cp /sdcard/aux-odlh-storage.db /data/data/com.google.android.apps.maps/databases/aux-odlh-storage.db
cp /sdcard/odlh-storage.db /data/data/com.google.android.gms/databases/odlh-storage.db

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
    subprocess.run([ADB, '-s', SERIAL, 'shell', f'cat << \"EOF\" > /sdcard/deploy_base.sh\n{deploy_cmd}\nEOF'], check=True)
    subprocess.run([ADB, '-s', SERIAL, 'shell', 'su', '-c', 'sh /sdcard/deploy_base.sh'], check=True)
    print("[✓] Baseline deployed!")

def navigate_to_feb_1():
    print("[*] Launching Maps Timeline and navigating to Feb 1, 2014...")
    subprocess.run([ADB, '-s', SERIAL, 'shell', 'su', '-c', 'am start -a android.intent.action.VIEW -d https://www.google.com/maps/timeline com.google.android.apps.maps'], check=True)
    time.sleep(5.0)

    # 1. Pull bottom sheet down to mid-height
    adb_shell(['input', 'swipe', '500', '600', '500', '1400', '300'])
    time.sleep(1.0)

    # 2. Tap date bar at (480, 1350)
    adb_shell(['input', 'tap', '480', '1350'])
    time.sleep(1.2)

    # 3. Tap year header
    adb_shell(['input', 'tap', '150', '600'])
    time.sleep(1.2)

    # 4. Scroll year list to reveal 2014
    for _ in range(2):
        adb_shell(['input', 'swipe', '500', '1100', '500', '1700', '500'])
        time.sleep(0.4)
    time.sleep(0.5)

    # 5. Tap 2014
    adb_shell(['input', 'tap', '500', '1250'])
    time.sleep(1.2)

    # 6. Step back 7 months to February 2014
    for _ in range(7):
        adb_shell(['input', 'tap', '110', '880'])
        time.sleep(0.2)
    time.sleep(1.0)

    # 7. Tap Saturday, Feb 1, 2014 at (850, 1150)
    adb_shell(['input', 'tap', '850', '1150'])
    time.sleep(2.5)

    # 8. Pull bottom sheet up
    adb_shell(['input', 'swipe', '500', '2250', '500', '1400', '300'])
    time.sleep(1.0)

def capture_all_baseline_days():
    print("[*] Capturing all 28 days of February 2014 (Baseline)...")
    for idx, day_str in enumerate(FEB_DAYS):
        dev_path = f"/sdcard/baseline_{day_str}.png"
        local_path = os.path.join(MEDIA_DIR, f"{day_str}_baseline.png")
        adb_shell(['screencap', '-p', dev_path])
        subprocess.run([ADB, '-s', SERIAL, 'pull', dev_path, local_path], check=True, capture_output=True)
        print(f"  [{idx+1}/28] Captured {day_str} (baseline) -> {local_path}")
        if idx < len(FEB_DAYS) - 1:
            adb_shell(['input', 'swipe', '850', '1600', '250', '1600', '150'])
            time.sleep(2.0)
    print("[✓] ALL 28 DAYS OF FEBRUARY 2014 (BASELINE) CAPTURED SUCCESSFULLY!")

if __name__ == '__main__':
    deploy_baseline()
    navigate_to_feb_1()
    capture_all_baseline_days()
