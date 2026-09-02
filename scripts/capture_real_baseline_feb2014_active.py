import os, subprocess, time

WORKSPACE_DIR = '/Users/rothfuss/Documents/antigravity/quick-galileo'
ARTIFACT_DIR = '/Users/rothfuss/.gemini/antigravity/brain/af2352af-830e-4cd4-9dfd-8f765759d408'
MEDIA_DIR = os.path.join(ARTIFACT_DIR, 'media_feb2014')
os.makedirs(MEDIA_DIR, exist_ok=True)

ADB = os.path.join(WORKSPACE_DIR, 'platform-tools', 'adb')
SERIAL = '192.168.1.36:5555'

FEB_DAYS = [f"2014-02-{d:02d}" for d in range(1, 29)]

def adb_shell(cmd):
    subprocess.run([ADB, '-s', SERIAL, 'shell'] + cmd, check=True)

print("[*] Starting sequential capture of REAL AUTHENTIC BASELINE across all 28 days of Feb 2014...")
for idx, day_str in enumerate(FEB_DAYS):
    dev_path = f"/sdcard/real_baseline_{day_str}.png"
    local_path = os.path.join(MEDIA_DIR, f"{day_str}_baseline.png")
    adb_shell(['screencap', '-p', dev_path])
    subprocess.run([ADB, '-s', SERIAL, 'pull', dev_path, local_path], check=True, capture_output=True)
    print(f"  [{idx+1}/28] Captured {day_str} (REAL BASELINE) -> {local_path}")
    if idx < len(FEB_DAYS) - 1:
        # Swipe left on the bottom sheet to step to next day
        adb_shell(['input', 'swipe', '850', '1600', '250', '1600', '150'])
        time.sleep(2.2)

print("[✓] ALL 28 DAYS OF REAL AUTHENTIC BASELINE CAPTURED SUCCESSFULLY!")
