#!/system/bin/sh
set -e
am force-stop com.google.android.apps.maps
am force-stop com.google.android.gms

MAPS_OWNER=$(stat -c '%u:%g' /data/data/com.google.android.apps.maps/databases 2>/dev/null || echo 'u0_a207:u0_a207')
ODLH_OWNER=$(stat -c '%u:%g' /data/data/com.google.android.gms/databases 2>/dev/null || echo 'u0_a180:u0_a180')

echo "MAPS_OWNER: $MAPS_OWNER, ODLH_OWNER: $ODLH_OWNER"

for d in /data/data/com.google.android.gms/databases /data/user_de/0/com.google.android.gms/databases; do
    if [ -d "$d" ]; then
        cp /sdcard/odlh_new.db "$d/odlh-storage.db"
        rm -f "$d/odlh-storage.db-wal" "$d/odlh-storage.db-shm" "$d/odlh-storage.db-journal"
        chown $ODLH_OWNER "$d/odlh-storage.db"
        chmod 660 "$d/odlh-storage.db"
        echo "Copied to $d"
    fi
done

if [ -d /data/data/com.google.android.apps.maps/databases ]; then
    cp /sdcard/odlh_new.db /data/data/com.google.android.apps.maps/databases/odlh-storage.db
    rm -f /data/data/com.google.android.apps.maps/databases/odlh-storage.db-wal
    rm -f /data/data/com.google.android.apps.maps/databases/odlh-storage.db-shm
    rm -f /data/data/com.google.android.apps.maps/databases/odlh-storage.db-journal
    chown $MAPS_OWNER /data/data/com.google.android.apps.maps/databases/odlh-storage.db
    chmod 660 /data/data/com.google.android.apps.maps/databases/odlh-storage.db
    echo "Copied to Maps databases"
fi

rm -f /data/data/com.google.android.apps.maps/databases/gmm_storage.db*
rm -f /data/data/com.google.android.apps.maps/databases/da_storage.db*

mkdir -p /data/data/com.google.android.apps.maps/app_place_cache/places
cp /sdcard/places_2_new /data/data/com.google.android.apps.maps/app_place_cache/places/2
chown -R $MAPS_OWNER /data/data/com.google.android.apps.maps/app_place_cache
chmod 755 /data/data/com.google.android.apps.maps/app_place_cache /data/data/com.google.android.apps.maps/app_place_cache/places
chmod 600 /data/data/com.google.android.apps.maps/app_place_cache/places/2

restorecon -R /data/data/com.google.android.apps.maps
restorecon -R /data/data/com.google.android.gms/databases

echo "Deployment finished successfully!"
