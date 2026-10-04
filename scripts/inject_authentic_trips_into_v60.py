import sqlite3
import shutil
from pathlib import Path

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
BUILD_DIR = WORKSPACE_DIR / "scratch" / "clean_build_v60"
ODLH_DB = BUILD_DIR / "odlh-storage.db"
AUX_DB = BUILD_DIR / "aux-odlh-storage.db"

BASE_BACKUP_DB = (
    WORKSPACE_DIR
    / "scratch"
    / "pixel8_backup_20260908"
    / "data"
    / "data"
    / "com.google.android.gms"
    / "databases"
    / "odlh-storage.db"
)

assert ODLH_DB.exists(), f"Missing {ODLH_DB}"
assert BASE_BACKUP_DB.exists(), f"Missing {BASE_BACKUP_DB}"

print("[1/4] Reading authentic 175 trip/memory segments from backup...")
conn_src = sqlite3.connect(str(BASE_BACKUP_DB))
c_src = conn_src.cursor()

trip_rows = c_src.execute("""
SELECT timestamp_millis, database_id, origin_id, segment_id, semantic_segment,
       obfuscated_gaia_id, shown_in_timeline, is_finalized, start_timestamp_seconds,
       end_timestamp_seconds, segment_type, hierarchy_level, fprint
FROM semantic_segment_table
WHERE segment_type = 4
ORDER BY start_timestamp_seconds ASC;
""").fetchall()

print(f"  Found {len(trip_rows)} authentic segment_type=4 rows.")
conn_src.close()

print("[2/4] Injecting trip segments into clean_build_v60/odlh-storage.db...")
conn_dst = sqlite3.connect(str(ODLH_DB))
c_dst = conn_dst.cursor()

# Get max _id and max origin_id in dst
max_id = c_dst.execute("SELECT MAX(_id) FROM semantic_segment_table;").fetchone()[0] or 0
max_origin = c_dst.execute("SELECT MAX(origin_id) FROM semantic_segment_table;").fetchone()[0] or 100000

print(f"  Current max _id: {max_id:,}, max origin_id: {max_origin:,}")

# Delete any existing type 4
c_dst.execute("DELETE FROM semantic_segment_table WHERE segment_type = 4;")

insert_rows = []
for idx, r in enumerate(trip_rows):
    curr_id = max_id + 1 + idx
    curr_origin = max_origin + 1 + idx
    t_ms, db_id, orig_id, seg_id, blob, gaia, shown, fin, sts, ets, stype, h_level, fp = r
    insert_rows.append((
        curr_id, t_ms, 1787254103124001536, curr_origin, seg_id, blob,
        "104819208193648646391", shown, fin, sts, ets, 4, h_level, fp
    ))

c_dst.executemany("""
INSERT INTO semantic_segment_table
(_id, timestamp_millis, database_id, origin_id, segment_id, semantic_segment, obfuscated_gaia_id,
 shown_in_timeline, is_finalized, start_timestamp_seconds, end_timestamp_seconds, segment_type,
 hierarchy_level, fprint)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
""", insert_rows)

conn_dst.commit()

# Verify integrity
c_dst.execute("PRAGMA integrity_check;")
check_dst = c_dst.fetchone()[0]
assert check_dst == "ok", f"Integrity check failed: {check_dst}"

counts = c_dst.execute("SELECT segment_type, count(*) FROM semantic_segment_table GROUP BY segment_type;").fetchall()
print(f"  [✓] Updated odlh-storage.db counts: {counts}")

print("[3/4] Rebuilding clean_build_v60/aux-odlh-storage.db with synchronized trip entries...")
if AUX_DB.exists():
    AUX_DB.unlink()

BASE_AUX_DB = (
    WORKSPACE_DIR
    / "scratch"
    / "pixel8_backup_20260908"
    / "data"
    / "data"
    / "com.google.android.gms"
    / "databases"
    / "aux-odlh-storage.db"
)
shutil.copy(str(BASE_AUX_DB), str(AUX_DB))

conn_aux = sqlite3.connect(str(AUX_DB))
c_aux = conn_aux.cursor()
c_aux.execute("DELETE FROM aux_semantic_segment_table;")

c_dst.execute("SELECT _id, segment_id, obfuscated_gaia_id, start_timestamp_seconds, end_timestamp_seconds, segment_type FROM semantic_segment_table ORDER BY _id ASC;")
aux_rows = [(r[0], r[1], None, r[2], r[3], r[4], r[5]) for r in c_dst.fetchall()]

c_aux.executemany("INSERT INTO aux_semantic_segment_table VALUES (?, ?, ?, ?, ?, ?, ?);", aux_rows)
c_aux.execute("PRAGMA user_version = 1;")
conn_aux.commit()

c_aux.execute("PRAGMA integrity_check;")
check_aux = c_aux.fetchone()[0]
assert check_aux == "ok", f"Aux integrity failed: {check_aux}"

aux_counts = c_aux.execute("SELECT segment_type, count(*) FROM aux_semantic_segment_table GROUP BY segment_type;").fetchall()
print(f"  [✓] Updated aux-odlh-storage.db counts: {aux_counts}")

conn_aux.close()
conn_dst.close()

print(f"[4/4] Successfully synchronized {len(insert_rows)} trips into clean_build_v60 bundle!")
