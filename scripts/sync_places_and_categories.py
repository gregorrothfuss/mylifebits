#!/usr/bin/env python3
"""
Synchronize places table visit counts and visit timestamps against segments,
normalize category labels, and merge duplicate Miami International Airport records.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path("timeline_viewer.db")

CATEGORY_MAPPINGS = {
    "airport": "Travel & Transit",
    "Transit": "Travel & Transit",
    "Leisure & Park": "Arts & Entertainment",
}


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    print("=== Step 1: Merge Duplicate Miami International Airport ===")
    duplicate_airport_pids = ["ChIJ4fiiy-Dan5gRwUq5Tk232Yg", "ChIJwUq5Tk232YgR4fiiy-Dan5g"]
    can_airport_pid = "ChIJ2-pYhL122YgRz5k_c4b9r3I"

    for dup_pid in duplicate_airport_pids:
        c.execute("UPDATE segments SET place_id = ? WHERE place_id = ?;", (can_airport_pid, dup_pid))
        print(f"Updated {c.rowcount} segments from {dup_pid} to canonical airport ID.")
        c.execute("DELETE FROM places WHERE place_id = ?;", (dup_pid,))
        print(f"Deleted {c.rowcount} duplicate place row for {dup_pid}.")

    print("\n=== Step 2: Normalize Categories ===")
    for old_cat, new_cat in CATEGORY_MAPPINGS.items():
        c.execute("UPDATE places SET category = ? WHERE category = ?;", (new_cat, old_cat))
        print(f"Places: mapped '{old_cat}' -> '{new_cat}' ({c.rowcount} rows)")
        c.execute("UPDATE segments SET category = ? WHERE category = ?;", (new_cat, old_cat))
        print(f"Segments: mapped '{old_cat}' -> '{new_cat}' ({c.rowcount} rows)")

    print("\n=== Step 3: Recompute visit_count and Timestamps for All Places ===")
    c.execute("""
        UPDATE places
        SET visit_count = (SELECT COUNT(*) FROM segments WHERE place_id = places.place_id),
            first_visit_time = (SELECT MIN(start_time) FROM segments WHERE place_id = places.place_id),
            last_visit_time = (SELECT MAX(end_time) FROM segments WHERE place_id = places.place_id);
    """)
    print(f"Recalculated visit counts and timestamps for {c.rowcount} places.")

    print("\n=== Step 4: Verification ===")
    c.execute("SELECT category, COUNT(*), SUM(visit_count) FROM places GROUP BY category ORDER BY 3 DESC;")
    for row in c.fetchall():
        print(f"  {row[0]:25} | Places: {row[1]:5} | Total Visits: {row[2] or 0}")

    c.execute("SELECT place_id, name, category, visit_count FROM places WHERE place_id = ?;", (can_airport_pid,))
    airport_row = c.fetchone()
    print("  Canonical Airport:", airport_row)
    assert airport_row[2] == "Travel & Transit", f"Expected Travel & Transit, got {airport_row[2]}"
    assert airport_row[3] == 14, f"Expected 14 visits, got {airport_row[3]}"

    c.execute("SELECT count(*) FROM places WHERE category IN ('airport', 'Leisure & Park', 'Transit');")
    bad_cats = c.fetchone()[0]
    assert bad_cats == 0, f"Found {bad_cats} places with unnormalized categories!"

    # Verify zero visit count desync
    c.execute("SELECT count(*) FROM places WHERE visit_count != (SELECT count(*) FROM segments WHERE place_id = places.place_id);")
    desync = c.fetchone()[0]
    assert desync == 0, f"Found {desync} places with desynchronized visit_count!"

    conn.commit()
    conn.close()
    print("\n[SUCCESS] Places and categories fully synchronized and verified.")


if __name__ == "__main__":
    main()
