"""
Batch Database Healer for Unconfirmed and Nameless Visits.

Reconciles all visits with placeholder names or raw coordinate strings against:
1. Canonical places catalog (places)
2. Life periods (residences & workplaces)
3. Custom labeled places
4. OpenStreetMap reverse geocoding
And cleans up orphaned dummy places.
"""

import os
import sqlite3
import sys
from typing import Any, Dict

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from enrichment.place_reconciler import is_nameless_place, resolve_visit_place

DEFAULT_DB_PATH = "timeline_viewer.db"


def heal_unconfirmed_visits(db_path: str = DEFAULT_DB_PATH) -> int:
    conn = sqlite3.connect(db_path, timeout=60.0)
    c = conn.cursor()

    c.execute(
        """
        SELECT id, date, start_time, end_time, place_id, place_name, place_address, latitude, longitude
        FROM segments
        WHERE segment_type = 'visit'
        ORDER BY date, start_time;
        """
    )
    all_visits = c.fetchall()
    nameless = [v for v in all_visits if is_nameless_place(v[5])]
    print(f"[*] Found {len(nameless)} nameless visits to heal in {db_path}...")

    healed_count = 0
    for v in nameless:
        sid, dt, st, et, pid, pname, paddr, lat, lng = v
        resolved = resolve_visit_place(
            db_path,
            lat,
            lng,
            current_name=pname,
            current_address=paddr,
            date_str=dt,
            allow_reverse_geocode=True,
            conn=conn,
        )
        if resolved and resolved.get("name") and not is_nameless_place(resolved["name"]):
            new_pid = resolved.get("place_id") or pid
            new_name = resolved["name"]
            new_addr = resolved.get("address") or paddr
            new_cat = resolved.get("category") or "Other / POI"
            new_city = resolved.get("city")

            # If resolved place not in places, insert it
            if new_pid:
                c.execute(
                    """
                    INSERT OR IGNORE INTO places (
                        place_id, name, address, category, city, latitude, longitude,
                        visit_count, source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (new_pid, new_name, new_addr, new_cat, new_city, lat, lng, 1, "RESOLVED_HEALER"),
                )

            # Update segment
            c.execute(
                """
                UPDATE segments
                SET place_id = ?,
                    place_name = ?,
                    place_address = ?,
                    category = ?,
                    city = coalesce(?, city),
                    is_unconfirmed = 0
                WHERE id = ?;
                """,
                (new_pid, new_name, new_addr, new_cat, new_city, sid),
            )
            healed_count += 1
            print(f"   [+] Healed segment {sid} ({dt}): '{pname}' -> '{new_name}' ({resolved.get('matched_by')})")

    # Clean up orphan 'Unconfirmed Location' places that have 0 remaining segment references
    c.execute(
        """
        DELETE FROM places
        WHERE name = 'Unconfirmed Location'
          AND place_id NOT IN (SELECT DISTINCT place_id FROM segments WHERE place_id IS NOT NULL);
        """
    )
    deleted_zombies = c.rowcount
    print(f"[*] Cleaned up {deleted_zombies} orphaned 'Unconfirmed Location' place records.")

    # Re-calculate visit counts for all places
    c.execute(
        """
        UPDATE places
        SET visit_count = (
            SELECT count(*)
            FROM segments s
            WHERE s.place_id = places.place_id
              AND s.segment_type = 'visit'
        );
        """
    )

    conn.commit()
    conn.close()
    print(f"[SUCCESS] Healed {healed_count} visits successfully.")
    return healed_count


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB_PATH
    heal_unconfirmed_visits(db)
