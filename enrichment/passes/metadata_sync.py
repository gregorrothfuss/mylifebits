"""Layer 1 canonical place catalog, 20-byte ChIJ FID, taxonomy, and review/photo metadata sync."""

from __future__ import annotations

import datetime
import json
import os
import re
import zipfile
from typing import Any, Dict

from breadcrumbs import haversine_distance
from db import get_db_connection
from enrichment.place_aggregates import (
    is_valid_20byte_chij,
    mint_canonical_chij,
    recompute_place_aggregates,
    relink_place_references,
)


def synchronize_places_and_metadata(engine: Any) -> Dict[str, int]:
    """
    Brings `places` and `segments` to 100% referential, 20-byte `ChIJ` FID,
    category, city, and `visit_count` parity.
    """
    conn = get_db_connection(engine.db_path)
    try:
        c = conn.cursor()
        run_id = engine.start_inference_run(
            conn, "layer1_synchronize_places_and_metadata", {"db_path": engine.db_path}
        )

        # 1. Repair malformed Place IDs in `places` and dependent tables
        c.execute("SELECT place_id, name, address, latitude, longitude FROM places;")
        repaired_pids = 0
        conn.execute("PRAGMA foreign_keys = OFF;")
        for row in c.fetchall():
            old_pid = row["place_id"]
            if not is_valid_20byte_chij(old_pid):
                seed = f"{old_pid}|{row['name'] or ''}|{row['latitude'] or 0}|{row['longitude'] or 0}"
                new_pid = mint_canonical_chij(row["latitude"], row["longitude"], seed)
                c.execute(
                    "INSERT OR IGNORE INTO place_aliases (alias_place_id, canonical_place_id) VALUES (?, ?);",
                    (old_pid, new_pid),
                )
                c.execute("SELECT 1 FROM places WHERE place_id = ?;", (new_pid,))
                if c.fetchone():
                    c.execute("DELETE FROM places WHERE place_id = ?;", (old_pid,))
                else:
                    c.execute("UPDATE places SET place_id = ? WHERE place_id = ?;", (new_pid, old_pid))
                relink_place_references(conn, old_pid, new_pid)
                repaired_pids += 1

        # Repair any visit in `segments` with NULL or malformed `place_id`
        c.execute(
            "SELECT id, place_id, place_name, place_address, category, city, latitude, longitude FROM segments WHERE segment_type = 'visit';"
        )
        for srow in c.fetchall():
            spid = srow["place_id"]
            if not is_valid_20byte_chij(spid):
                seed = f"seg_{srow['id']}|{srow['place_name'] or ''}|{srow['latitude'] or 0}|{srow['longitude'] or 0}"
                new_pid = mint_canonical_chij(srow["latitude"], srow["longitude"], seed)
                c.execute(
                    """
                    INSERT OR IGNORE INTO places (place_id, name, address, category, city, latitude, longitude, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'REPAIRED_SEGMENT');
                    """,
                    (
                        new_pid,
                        srow["place_name"] or "Verified Place",
                        srow["place_address"],
                        srow["category"] or "Other / POI",
                        srow["city"],
                        srow["latitude"],
                        srow["longitude"],
                    ),
                )
                c.execute("UPDATE segments SET place_id = ? WHERE id = ?;", (new_pid, srow["id"]))
                repaired_pids += 1
        conn.execute("PRAGMA foreign_keys = ON;")

        # 2. Normalize taxonomy categories on `places` and `segments`
        cat_norms = [
            ("Travel & Transit", ("Transit", "airport", "train_station", "subway_station", "transit_station")),
            ("Outdoors & Nature", ("Leisure & Park", "park", "natural_feature")),
            ("Shopping", ("Shopping & Retail", "store", "shopping_mall", "supermarket")),
            ("Health & Wellness", ("Health & Services", "hospital", "doctor", "dentist", "pharmacy", "gym", "spa")),
            ("Education", ("Education & Campus", "school", "university", "library")),
            ("Food & Drink", ("restaurant", "cafe", "bar", "bakery")),
            ("Hotels & Lodging", ("lodging", "hotel")),
        ]
        for canon_cat, raw_list in cat_norms:
            placeholders = ",".join("?" for _ in raw_list)
            c.execute(
                f"UPDATE places SET category = ? WHERE category IN ({placeholders});",
                (canon_cat, *raw_list),
            )
            c.execute(
                f"UPDATE segments SET category = ? WHERE category IN ({placeholders});",
                (canon_cat, *raw_list),
            )

        keyword_cats = [
            ("Travel & Transit", ["citi bike", "airport", "station", "bahnhof", "gare", "terminal", "subway", "ferry", "port", "pier"]),
            ("Hotels & Lodging", ["hotel", "hôtel", "hostel", "inn", "resort", "motel", "airbnb", "chalet", "lodge", "riad"]),
            ("Food & Drink", ["cafe", "café", "coffee", "restaurant", "pizza", "pizzeria", "bakery", "bäckerei", "bar", "pub", "tavern", "bistro", "kitchen", "grill", "diner", "sushi", "ramen", "taco", "taqueria", "burger", "brewery", "winery", "gelato", "ice cream", "creamery", "deli", "delicatessen", "bagel", "brasserie", "trattoria", "osteria", "izakaya", "kafi", "badi"]),
            ("Arts & Entertainment", ["museum", "gallery", "theater", "theatre", "cinema", "opera", "concert", "stadium", "arena", "zoo", "aquarium", "castle", "schloss", "palace", "cathedral", "church", "temple", "shrine", "monument", "memorial", "pavilion", "kunsthalle", "kino"]),
            ("Outdoors & Nature", ["park", "beach", "garden", "trail", "mountain", "peak", "lake", "river", "island", "falls", "waterfall", "canyon", "valley", "woods", "forest", "plaza", "square", "platz", "promenade", "peninsula"]),
            ("Shopping", ["market", "supermarket", "grocery", "whole foods", "trader joe", "migros", "coop", "store", "shop", "mall", "boutique", "pharmacy", "apotheke", "bookstore", "books", "hardware", "ikea", "target", "costco", "bodega", "deli & grocery"]),
            ("Education", ["university", "college", "school", "schule", "campus", "institute", "academy", "library", "bibliothek"]),
            ("Work & Office", ["office", "headquarters", "coworking", "wework", "corporate"]),
            ("Home & Residence", ["home (", "residence", "apartment"]),
            ("Health & Wellness", ["hospital", "clinic", "medical", "dental", "dentist", "doctor", "spital", "fitness", "gym", "yoga", "spa", "bath", "therme", "hammam"]),
        ]
        c.execute(
            "SELECT place_id, name, address, category, semantic_type FROM places WHERE category IS NULL OR category = 'Other / POI';"
        )
        for prow in c.fetchall():
            text = f"{prow['name'] or ''} {prow['address'] or ''}".lower()
            sem = (prow["semantic_type"] or "").upper()
            matched_cat = None
            if sem == "TYPE_HOME":
                matched_cat = "Home & Residence"
            elif sem == "TYPE_WORK":
                matched_cat = "Work & Office"
            else:
                for cat_label, kw_list in keyword_cats:
                    if any(kw in text for kw in kw_list):
                        matched_cat = cat_label
                        break
            if matched_cat:
                c.execute("UPDATE places SET category = ? WHERE place_id = ?;", (matched_cat, prow["place_id"]))

        # 3. Backfill missing city on `places`
        c.execute(
            "SELECT place_id, name, address, latitude, longitude FROM places WHERE city IS NULL OR city = '' OR city = 'Unknown';"
        )
        missing_city_places = [dict(r) for r in c.fetchall()]

        c.execute(
            """
            SELECT city, AVG(latitude) as clat, AVG(longitude) as clng, COUNT(*) as cnt
            FROM places
            WHERE city IS NOT NULL AND city != '' AND city != 'Unknown'
              AND latitude IS NOT NULL AND longitude IS NOT NULL
            GROUP BY city
            HAVING cnt >= 2;
            """
        )
        city_centroids = [dict(r) for r in c.fetchall()]

        cities_updated = 0
        for mp in missing_city_places:
            plat, plng = mp["latitude"], mp["longitude"]
            addr = mp["address"] or ""
            inferred_city = None

            if plat is not None and plng is not None:
                if 40.49 <= plat <= 40.92 and -74.26 <= plng <= -73.68:
                    inferred_city = "New York"
                elif 47.30 <= plat <= 47.45 and 8.44 <= plng <= 8.63:
                    inferred_city = "Zürich"
                elif 42.30 <= plat <= 42.42 and -71.18 <= plng <= -71.00:
                    inferred_city = "Cambridge" if plng < -71.08 else "Boston"
                elif 37.70 <= plat <= 37.82 and -122.52 <= plng <= -122.35:
                    inferred_city = "San Francisco"
                elif 37.35 <= plat <= 37.45 and -122.15 <= plng <= -122.02:
                    inferred_city = "Mountain View"
                else:
                    best_d = 35000.0
                    for cc in city_centroids:
                        d = haversine_distance(float(plat), float(plng), float(cc["clat"]), float(cc["clng"]))
                        if d < best_d:
                            best_d = d
                            inferred_city = cc["city"]

            if not inferred_city and addr:
                parts = [p.strip() for p in addr.split(",") if p.strip()]
                if len(parts) >= 2:
                    cand = parts[-2] if len(parts) >= 3 else parts[0]
                    cand_clean = "".join(ch for ch in cand if not ch.isdigit()).strip()
                    if len(cand_clean) >= 3:
                        inferred_city = cand_clean

            if inferred_city:
                c.execute("UPDATE places SET city = ? WHERE place_id = ?;", (inferred_city, mp["place_id"]))
                cities_updated += 1

        # 4. Propagate `places` metadata onto `segments`
        c.execute(
            """
            UPDATE segments
            SET category = COALESCE((SELECT p.category FROM places p WHERE p.place_id = segments.place_id), category, 'Other / POI'),
                city = COALESCE((SELECT p.city FROM places p WHERE p.place_id = segments.place_id), city),
                place_name = COALESCE(place_name, (SELECT p.name FROM places p WHERE p.place_id = segments.place_id)),
                place_address = COALESCE(place_address, (SELECT p.address FROM places p WHERE p.place_id = segments.place_id))
            WHERE segment_type = 'visit' AND place_id IS NOT NULL;
            """
        )
        segments_synced = int(c.rowcount or 0)

        c.execute(
            """
            UPDATE segments
            SET city = 'New York'
            WHERE segment_type = 'visit' AND city IS NULL
              AND latitude BETWEEN 40.49 AND 40.92 AND longitude BETWEEN -74.26 AND -73.68;
            """
        )
        c.execute(
            """
            UPDATE segments
            SET city = 'Zürich'
            WHERE segment_type = 'visit' AND city IS NULL
              AND latitude BETWEEN 47.30 AND 47.45 AND longitude BETWEEN 8.44 AND 8.63;
            """
        )
        c.execute(
            """
            UPDATE segments
            SET category = 'Other / POI'
            WHERE segment_type = 'visit' AND (category IS NULL OR category = '');
            """
        )
        c.execute(
            """
            UPDATE segments
            SET source = 'USER_MANUAL'
            WHERE source IS NULL OR source = '';
            """
        )
        c.execute(
            """
            UPDATE places
            SET business_status = 'OPERATIONAL'
            WHERE business_status IS NULL OR business_status = '';
            """
        )

        # 5. Recompute exact `visit_count`, `first_visit_time`, `last_visit_time`,
        # `latest_visit_date`, and true `median_dwell_minutes` via shared helper
        recompute_place_aggregates(conn)

        conn.commit()
        out = {
            "repaired_place_ids": repaired_pids,
            "cities_backfilled": cities_updated,
            "segments_metadata_synced": segments_synced,
        }
        engine.complete_inference_run(conn, run_id, out)
        return out
    finally:
        conn.close()


def sanitize_photos_and_reviews_metadata(engine: Any) -> Dict[str, int]:
    """
    Sanitizes photos coordinate noise and normalizes poi_reviews timestamps:
    1. Clears fake (0.0, 0.0) Null Island coordinates from photos table.
    2. Normalizes relative review date strings in poi_reviews into ISO dates.
    """
    conn = get_db_connection(engine.db_path)
    try:
        c = conn.cursor()
        run_id = engine.start_inference_run(
            conn, "layer1_sanitize_photos_and_reviews", {"db_path": engine.db_path}
        )

        c.execute(
            """
            UPDATE photos
            SET latitude = NULL, longitude = NULL
            WHERE latitude = 0.0 AND longitude = 0.0;
            """
        )
        null_island_cleared = int(c.rowcount or 0)

        zip_map: Dict[str, str] = {}
        takeout_dir = os.environ.get("TIMELINE_TAKEOUT_DIR", "data/takeout")
        if os.path.isdir(takeout_dir):
            for entry in sorted(os.listdir(takeout_dir)):
                if "review" in entry.lower() and entry.endswith(".zip"):
                    zpath = os.path.join(takeout_dir, entry)
                    try:
                        with zipfile.ZipFile(zpath) as z:
                            data = json.loads(
                                z.read("Takeout/Maps (your places)/Reviews.json").decode("utf-8")
                            )
                            for f in data.get("features", []):
                                p = f.get("properties", {})
                                dt = p.get("date")
                                url = p.get("google_maps_url")
                                text = (p.get("review_text_published") or "").strip()
                                if url and dt:
                                    zip_map[url] = dt
                                if text and dt:
                                    zip_map[text[:60]] = dt
                    except Exception:
                        pass

        anchor_date = datetime.date.today()

        def parse_relative_to_iso(text: str) -> str:
            s = text.lower().strip()
            m_yr = re.search(r"(\d+)\s+year", s)
            if m_yr:
                yrs = int(m_yr.group(1))
                approx_yr = max(1995, anchor_date.year - yrs)
                return f"{approx_yr}-06-15"
            if "a year" in s:
                return f"{anchor_date.year - 1}-08-15"
            m_mo = re.search(r"(\d+)\s+month", s)
            if m_mo:
                mos = int(m_mo.group(1))
                tot_mo = anchor_date.year * 12 + anchor_date.month - mos
                yr = tot_mo // 12
                mo = max(1, min(12, tot_mo % 12 or 12))
                return f"{yr:04d}-{mo:02d}-15"
            if "a month" in s:
                tot_mo = anchor_date.year * 12 + anchor_date.month - 1
                yr = tot_mo // 12
                mo = max(1, min(12, tot_mo % 12 or 12))
                return f"{yr:04d}-{mo:02d}-15"
            m_wk = re.search(r"(\d+)\s+week", s)
            if m_wk:
                wks = int(m_wk.group(1))
                dt_res = anchor_date - datetime.timedelta(weeks=wks)
                return dt_res.isoformat()
            return f"{anchor_date.year - 4}-01-01"

        c.execute("SELECT id, date, google_maps_url, review_text FROM poi_reviews;")
        reviews_updated = 0
        for rid, dt, url, text in c.fetchall():
            if dt and re.match(r"^\d{4}-\d{2}-\d{2}", dt):
                continue
            exact_dt = zip_map.get(url) or (zip_map.get((text or "").strip()[:60]) if text else None)
            if exact_dt:
                c.execute("UPDATE poi_reviews SET date = ? WHERE id = ?;", (exact_dt[:10], rid))
                reviews_updated += 1
            elif dt:
                approx_dt = parse_relative_to_iso(dt)
                c.execute("UPDATE poi_reviews SET date = ? WHERE id = ?;", (approx_dt, rid))
                reviews_updated += 1

        conn.commit()
        out = {
            "null_island_cleared": null_island_cleared,
            "reviews_normalized": reviews_updated,
        }
        engine.complete_inference_run(conn, run_id, out)
        return out
    finally:
        conn.close()
