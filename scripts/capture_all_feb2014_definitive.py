import os, subprocess, time

WORKSPACE_DIR = '/Users/rothfuss/Documents/antigravity/gregor-mylifebits'
ARTIFACT_DIR = '/Users/rothfuss/.gemini/antigravity/brain/af2352af-830e-4cd4-9dfd-8f765759d408'
MEDIA_DIR = os.path.join(ARTIFACT_DIR, 'media_feb2014')
os.makedirs(MEDIA_DIR, exist_ok=True)

ADB = os.path.join(WORKSPACE_DIR, 'platform-tools', 'adb')
SERIAL = '192.168.1.36:5555'

FEB_DAYS = [f"2014-02-{d:02d}" for d in range(1, 29)]

def adb_shell(cmd):
    subprocess.run([ADB, '-s', SERIAL, 'shell'] + cmd, check=True)

def navigate_to_feb_1():
    print("[*] Navigating to Feb 1, 2014 from year picker...")
    # Scroll year wheel up one more time to reach 2014
    adb_shell(['input', 'swipe', '500', '1600', '500', '1200', '500'])
    time.sleep(0.8)

    # Tap 2014 (centered around 500, 1360 or 500, 1250)
    adb_shell(['input', 'tap', '500', '1360'])
    time.sleep(1.2)

    # Step back 8 months to February 2014
    for _ in range(8):
        adb_shell(['input', 'tap', '110', '880'])
        time.sleep(0.2)
    time.sleep(1.0)

    # Tap Saturday, Feb 1, 2014 at (850, 1150)
    adb_shell(['input', 'tap', '850', '1150'])
    time.sleep(2.5)

    # Pull bottom sheet up
    adb_shell(['input', 'swipe', '500', '2250', '500', '1400', '300'])
    time.sleep(1.0)

def capture_all_28_days(prefix="cleaned"):
    print(f"[*] Starting sequential capture for all 28 days of Feb 2014 ({prefix})...")
    for idx, day_str in enumerate(FEB_DAYS):
        dev_path = f"/sdcard/{prefix}_{day_str}.png"
        local_path = os.path.join(MEDIA_DIR, f"{day_str}_{prefix}.png")
        adb_shell(['screencap', '-p', dev_path])
        subprocess.run([ADB, '-s', SERIAL, 'pull', dev_path, local_path], check=True, capture_output=True)
        print(f"  [{idx+1}/28] Captured {day_str} ({prefix}) -> {local_path}")
        if idx < len(FEB_DAYS) - 1:
            # Swipe left on the bottom sheet to step to next day
            adb_shell(['input', 'swipe', '850', '1600', '250', '1600', '150'])
            time.sleep(2.0)
    print(f"[✓] ALL 28 DAYS OF FEBRUARY 2014 ({prefix}) CAPTURED SUCCESSFULLY!")

if __name__ == '__main__':
    navigate_to_feb_1()
    capture_all_28_days("cleaned")
