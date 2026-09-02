import os, subprocess, time

WORKSPACE_DIR = '/Users/rothfuss/Documents/antigravity/quick-galileo'
ADB = os.path.join(WORKSPACE_DIR, 'platform-tools', 'adb')
SERIAL = '192.168.1.36:5555'

GMS_ODLH = os.path.join(WORKSPACE_DIR, 'scratch/original_gms_backup/data/data/com.google.android.gms/databases/odlh-storage.db')
GMS_GELLER = os.path.join(WORKSPACE_DIR, 'scratch/original_gms_backup/data/data/com.google.android.gms/databases/portable_geller_rothfuss@gmail.com.db')

print("[*] Deploying REAL AUTHENTIC Pixel 10 GMS Backup to Pixel 8...")
subprocess.run([ADB, '-s', SERIAL, 'push', GMS_ODLH, '/sdcard/real_odlh.db'], check=True)
subprocess.run([ADB, '-s', SERIAL, 'push', GMS_GELLER, '/sdcard/real_geller.db'], check=True)

deploy_cmd = """
am force-stop com.google.android.apps.maps
am force-stop com.google.android.gms

cp /sdcard/real_odlh.db /data/data/com.google.android.apps.maps/databases/odlh-storage.db
cp /sdcard/real_odlh.db /data/data/com.google.android.gms/databases/odlh-storage.db
cp /sdcard/real_geller.db /data/data/com.google.android.gms/databases/portable_geller_rothfuss@gmail.com.db

chown -R u0_a207:u0_a207 /data/data/com.google.android.apps.maps/databases/
chown -R u0_a180:u0_a180 /data/data/com.google.android.gms/databases/

chmod 660 /data/data/com.google.android.apps.maps/databases/*
chmod 660 /data/data/com.google.android.gms/databases/*

rm -f /data/data/com.google.android.apps.maps/databases/*-wal /data/data/com.google.android.apps.maps/databases/*-shm
rm -f /data/data/com.google.android.gms/databases/*-wal /data/data/com.google.android.gms/databases/*-shm

restorecon -R /data/data/com.google.android.apps.maps/ 2>/dev/null || true
restorecon -R /data/data/com.google.android.gms/ 2>/dev/null || true
"""

subprocess.run([ADB, '-s', SERIAL, 'shell', f'cat << \"EOF\" > /sdcard/deploy_real_base.sh\n{deploy_cmd}\nEOF'], check=True)
subprocess.run([ADB, '-s', SERIAL, 'shell', 'su', '-c', 'sh /sdcard/deploy_real_base.sh'], check=True)
print("[✓] Real Authentic Pixel 10 GMS Backup deployed successfully!")
