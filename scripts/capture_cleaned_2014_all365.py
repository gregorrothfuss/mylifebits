import os, subprocess, time, datetime

WORKSPACE_DIR = '/Users/rothfuss/Documents/antigravity/gregor-mylifebits'
ARTIFACT_DIR = '/Users/rothfuss/.gemini/antigravity/brain/af2352af-830e-4cd4-9dfd-8f765759d408'
MEDIA_DIR = os.path.join(ARTIFACT_DIR, 'media_2014_full')
os.makedirs(MEDIA_DIR, exist_ok=True)

ADB = os.path.join(WORKSPACE_DIR, 'platform-tools', 'adb')
SERIAL = '192.168.1.36:5555'

def adb_shell(cmd):
    subprocess.run([ADB, '-s', SERIAL, 'shell'] + cmd, check=True)

start_date = datetime.date(2014, 1, 1)
all_days = [start_date + datetime.timedelta(days=i) for i in range(365)]

print(f"[*] Starting full 365-day capture of CLEANED DATASET for Year 2014 (from {all_days[0]} to {all_days[-1]})...")

for idx, dt in enumerate(all_days):
    day_str = dt.strftime("%Y-%m-%d")
    dev_path = f"/sdcard/clean_{day_str}.png"
    local_path = os.path.join(MEDIA_DIR, f"{day_str}_cleaned.png")
    
    adb_shell(['screencap', '-p', dev_path])
    subprocess.run([ADB, '-s', SERIAL, 'pull', dev_path, local_path], check=True, capture_output=True)
    
    if (idx + 1) % 10 == 0 or idx == 0 or idx == 364:
        print(f"  [{idx+1:3d}/365] Captured {day_str} Cleaned -> {os.path.basename(local_path)} ({os.path.getsize(local_path)} bytes)")
        
    if idx < 364:
        adb_shell(['input', 'swipe', '850', '1600', '250', '1600', '150'])
        time.sleep(1.8)

print("[✓] ALL 365 DAYS OF CLEANED DATASET CAPTURED SUCCESSFULLY!")
