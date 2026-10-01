#!/usr/bin/env python3
"""
Imports strictly HIGH-QUALITY, high-signal daily photo notes into timeline_viewer.db.
Filters out:
- All OCR garbage snippets ('Visible signage in the shots included...').
- All boilerplate template filler ('A collection of N photos documented in...').
- All low-quality days lacking verified visual themes or identified companions (~50% of days).
- Redundant taxonomy category concatenation ('Dining & Food and Dinner Gathering').
- Unnecessary photo count noise ('(10 photos)').

Preserves authentic user Takeout notes.
"""

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
PHOTOS_DB = Path("/Users/rothfuss/projects/gregor_cos/photos_vault.db")
VIEWER_DB = WORKSPACE_DIR / "timeline_viewer.db"


KNOWN_GALLERIES = {
    "agora gallery", "pace gallery", "gagosian", "lehmann maupin", "metro pictures",
    "david zwirner", "yossi milo gallery", "betty cuningham gallery", "garth greenan gallery",
    "hauser & wirth", "petzel gallery", "gladstone gallery", "marlborough gallery",
    "skny", "paul kasmin gallery", "sikkema jenkins & co.", "the bushwick collective"
}


def clean_location_candidate(loc: str) -> str | None:
    if not loc:
        return None
    loc = loc.strip()
    # Reject postal codes, zip codes, and state+zip combos (e.g. 'Michigan 48124', 'FL 33149')
    if re.search(r"\b\d{4,5}\b", loc):
        return None
    loc = loc.replace("ZÜrich", "Zürich").replace("Zuerich", "Zürich")
    if "/" in loc:
        parts = [p.strip() for p in loc.split("/")]
        loc = parts[-1] if len(parts) > 1 else parts[0]
    if loc.lower() == "new york":
        loc = "New York"
    if loc == "NY":
        loc = "New York"
    if loc == "MA":
        loc = "Massachusetts"
    if loc == "CA":
        loc = "California"
    return loc.strip() or None


def extract_city_from_visit(s_name, s_addr, s_city, p_name, p_addr, p_city) -> str | None:
    for c in (s_city, p_city):
        if c:
            c = c.strip()
            if "," in c:
                c = c.split(",")[0].strip()
            if c and c.lower() not in ("none", "other", "unknown") and not re.search(r"\b\d{5}\b", c):
                if c.lower() == "new york":
                    return "New York"
                return clean_location_candidate(c)
    for addr in (s_addr, p_addr):
        if addr:
            m = re.search(r",\s*([^,]+),\s*[A-Z]{2}(?:\s+\d{4,5})?,\s*USA", addr)
            if m:
                c = m.group(1).strip()
                if c.lower() == "new york":
                    return "New York"
                return clean_location_candidate(c)
            m2 = re.search(r",\s*(\d{4,5}\s+)?([^,]+),\s*Switzerland", addr, re.IGNORECASE)
            if m2:
                return clean_location_candidate(m2.group(2).strip())
            parts = [p.strip() for p in addr.split(",") if p.strip()]
            if len(parts) >= 2:
                candidate = parts[-3] if len(parts) >= 3 else parts[-2]
                if not re.search(r"\b\d{4,5}\b", candidate):
                    return clean_location_candidate(candidate)
    for name in (s_name, p_name):
        if name:
            if any(h in name for h in ("298 E 2nd St", "189 Ave C", "Google NYC", "Manhattan")):
                return "New York"
            if "800 E 17th St" in name:
                return "Brooklyn"
            if "52 Portsmouth St" in name:
                return "Cambridge"
            if "28 Elm St" in name:
                return "Somerville"
            if any(z in name for z in ("Huttenstrasse", "University of Zurich", "KPMG AG", "Wiedikon")):
                return "Zürich"
    return None


def get_day_visit_grounding(conn_viewer: sqlite3.Connection, date_str: str) -> dict:
    from collections import Counter

    rows = conn_viewer.execute("""
        SELECT s.place_name, s.place_address, s.city, s.category, s.activity_type,
               p.name, p.address, p.city, p.category, p.primary_type, p.types
        FROM segments s
        LEFT JOIN places p ON s.place_id = p.place_id
        WHERE s.date = ?;
    """, (date_str,)).fetchall()

    cities = []
    has_museum = False
    has_art_venue = False
    has_food = False
    has_drinks = False
    has_cafe = False
    has_biking = False
    has_boats = False
    has_hiking = False
    has_books = False
    total_visits = 0

    for r in rows:
        s_name, s_addr, s_city, s_cat, s_act, p_name, p_addr, p_city, p_cat, p_ptype, p_types = r
        if s_act in ("CYCLING", "ON_BICYCLE") or (s_name and "Citi Bike" in s_name):
            has_biking = True
        if s_act in ("FERRY", "IN_FERRY") or (s_name and ("Ferry" in s_name or "Pier" in s_name)):
            has_boats = True
        if s_act == "HIKING":
            has_hiking = True

        if s_name or p_name:
            total_visits += 1
            c = extract_city_from_visit(s_name, s_addr, s_city, p_name, p_addr, p_city)
            if c:
                cities.append(c)

            parts = [s_name or "", p_name or "", p_ptype or "", p_types or "", s_cat or "", p_cat or ""]
            blob = " ".join(parts).lower()

            if "museum" in blob or "musée" in blob or "museo" in blob or "sammlung" in blob:
                has_museum = True

            if "art_gallery" in blob or "art_museum" in blob:
                has_art_venue = True
            elif (p_cat == "Arts & Entertainment" or s_cat == "Arts & Entertainment") and any(
                w in blob for w in ("gallery", "galerie", "kunsthalle", "art center")
            ):
                has_art_venue = True
            elif (s_name and s_name.lower() in KNOWN_GALLERIES) or (p_name and p_name.lower() in KNOWN_GALLERIES):
                has_art_venue = True

            if (s_cat == "Food & Drink" or p_cat == "Food & Drink" or
                any(f in blob for f in ("restaurant", "bakery", "cafe", "diner", "bistro", "ramen", "bar", "pizza", "dining"))):
                has_food = True

            if any(d in blob for d in ("bar", "nightlife", "brewery", "wine_bar", "pub", "cocktail")):
                has_drinks = True

            if any(cf in blob for cf in ("cafe", "coffee", "bakery")):
                has_cafe = True

            if any(b in blob for b in ("book_store", "library", "bookstore", "books")):
                has_books = True

    top_city = Counter(cities).most_common(1)[0][0] if cities else None
    return {
        "total_visits": total_visits,
        "city": top_city,
        "has_museum": has_museum,
        "has_art_venue": has_art_venue,
        "has_food": has_food,
        "has_drinks": has_drinks,
        "has_cafe": has_cafe,
        "has_biking": has_biking,
        "has_boats": has_boats,
        "has_hiking": has_hiking,
        "has_books": has_books,
    }


def pick_best_location(
    locations: list[str],
    conn_viewer: sqlite3.Connection | None = None,
    date_str: str | None = None,
    visit_grounding: dict | None = None
) -> str:
    # 1. Primary spatial ground truth: actual stationary visits on this day
    if visit_grounding and visit_grounding.get("city"):
        return visit_grounding["city"]

    # 2. Secondary check: viewer DB photos and segments
    if conn_viewer and date_str:
        try:
            # Query photos, but filter out false waterfront reverse geocoding (e.g. Weehawken/Hoboken for Manhattan photos)
            photo_rows = conn_viewer.execute("""
                SELECT city, latitude, longitude, COUNT(*) as c
                FROM photos
                WHERE local_date = ? AND city IS NOT NULL AND city != ''
                GROUP BY city
                ORDER BY c DESC;
            """, (date_str,)).fetchall()
            for r in photo_rows:
                raw_city, lat, lng, cnt = r[0], r[1], r[2], r[3]
                # If waterfront photo coordinates in Manhattan, reject Weehawken/Hoboken
                if raw_city in ("Weehawken", "Hoboken"):
                    if lat is not None and lng is not None and lat >= 40.70 and lng >= -74.02:
                        return "New York"
                    continue
                cleaned = clean_location_candidate(raw_city)
                if cleaned:
                    return cleaned
        except Exception:
            pass

    for candidate in locations:
        if candidate in ("Weehawken", "Hoboken"):
            continue
        cleaned = clean_location_candidate(candidate)
        if cleaned:
            return cleaned
    return ""


def simplify_themes(
    themes: list[str],
    max_hour: float | None = None,
    min_hour: float | None = None,
    visit_grounding: dict | None = None
) -> list[str]:
    vg = visit_grounding or {}
    total_visits = vg.get("total_visits", 0)

    has_dinner = ("Dinner Gathering" in themes or "Dinner" in themes)
    has_lunch = ("Lunch Gathering" in themes or "Lunch" in themes)
    has_breakfast = ("Breakfast & Coffee" in themes or "Breakfast" in themes)
    has_dining = ("Dining & Food" in themes or "Dining Gathering" in themes or "Dining" in themes)

    # Cross-validate Museum against actual visits: NEVER claim Museum without a verified museum visit
    has_museum = "Museum Exhibits" in themes
    if total_visits > 0 and not vg.get("has_museum", False):
        has_museum = False
    elif total_visits == 0:
        # Pre-timeline days without visits: do not infer museum from ambiguous indoor photos
        has_museum = False

    # Cross-validate Art against actual art venue visits (galleries, art museums)
    has_art = "Sculptures & Art" in themes
    if total_visits > 0 and not vg.get("has_art_venue", False):
        # If raw themes had Museum Exhibits but visit was an Art Gallery, map to Art
        if "Museum Exhibits" in themes and vg.get("has_art_venue", False):
            has_art = True
        else:
            has_art = False
    elif total_visits == 0:
        has_art = False

    has_murals = "Street Art Murals" in themes
    has_hike = "Mountain Hike" in themes
    has_trails = "Forest Trails" in themes
    has_snow = "Winter Snow" in themes
    has_beach = "Coastal Beach" in themes
    has_drinks = "Drinks & Cocktails" in themes
    has_biking = "Biking" in themes
    has_boats = "Ferry & Boats" in themes
    has_lakes = "Rivers & Lakeshore" in themes
    has_books = "Books & Bookstore" in themes
    has_coffee = "Coffee & Cafes" in themes

    # Validate dining against visit context
    if total_visits > 0 and not vg.get("has_food", False):
        has_dinner = False
        has_lunch = False
        has_breakfast = False
        has_dining = False

    # Temporal sanity bound: If claimed as Dinner, but photos were strictly daytime, correct to Lunch/Breakfast
    if has_dinner and max_hour is not None and max_hour < 16.5:
        has_dinner = False
        if max_hour < 11.0:
            has_breakfast = True
        else:
            has_lunch = True

    out = []
    if has_dinner:
        out.append("Dinner")
    elif has_lunch:
        out.append("Lunch")
    elif has_breakfast:
        out.append("Breakfast")
    elif has_dining:
        out.append("Dining")

    if has_museum and (has_art or has_murals):
        out.append("Museum & Art")
    elif has_art and has_murals:
        out.append("Art & Murals")
    elif has_museum:
        out.append("Museum")
    elif has_art:
        out.append("Art")
    elif has_murals:
        out.append("Street Art")

    if has_drinks and not out:
        out.append("Drinks")
    if has_hike:
        out.append("Hike")
    elif has_trails and not out:
        out.append("Nature walk")
    if has_snow and "Hike" not in out and not out:
        out.append("Snow")
    if has_beach and not out:
        out.append("Beach")
    if has_biking and not out:
        out.append("Biking")
    if has_boats and not out:
        out.append("Boats")
    if has_lakes and not out:
        out.append("Lakeshore")
    if has_books and not out:
        out.append("Bookstore")
    if has_coffee and not out:
        out.append("Coffee")
    return out[:2]


def synthesize_clean_note(date_str, people, themes, locations, conn_viewer: sqlite3.Connection | None = None):
    """
    Quality gate & clean synthesis. Returns (title, text) or None if low quality.
    """
    # Inspect actual photo hours in viewer db to prevent temporal hallucination
    min_hr, max_hr = None, None
    if conn_viewer:
        try:
            rows = conn_viewer.execute("""
                SELECT timestamp_utc, timezone_offset
                FROM photos
                WHERE local_date = ? AND timestamp_utc IS NOT NULL;
            """, (date_str,)).fetchall()
            hours = []
            for r in rows:
                ts, tz = r[0], r[1]
                offset_sec = 0
                if tz:
                    tz_clean = tz.strip('\x00').strip()
                    try:
                        sign = -1 if tz_clean[0] == '-' else 1
                        parts = tz_clean[1:].split(':')
                        offset_sec = sign * (int(parts[0]) * 3600 + int(parts[1]) * 60)
                    except Exception:
                        pass
                dt = datetime.fromtimestamp(ts + offset_sec, timezone.utc)
                hours.append(dt.hour + dt.minute / 60.0)
            if hours:
                min_hr, max_hr = min(hours), max(hours)
        except Exception:
            pass

    clean_p = [p for p in people if p != "Gregor J. Rothfuss"]

    # Verify companions against actual photos in viewer db to eliminate hallucinations from non-colocated partner media
    if conn_viewer and date_str:
        try:
            verified_people_rows = conn_viewer.execute("""
                SELECT people FROM photos WHERE local_date = ? AND people IS NOT NULL;
            """, (date_str,)).fetchall()
            verified_people_set = set()
            for (p_str,) in verified_people_rows:
                for person in p_str.split(","):
                    p_clean = person.strip()
                    if p_clean and p_clean != "Gregor J. Rothfuss":
                        verified_people_set.add(p_clean)
            if verified_people_set:
                clean_p = [p for p in clean_p if p in verified_people_set]
            elif clean_p:
                clean_p = []
        except Exception:
            pass

    # 1. Quality gate: Must have either a valid visual theme or identified companions
    if not themes and not clean_p:
        return None

    # Filter out solo generic themes without companions
    valid_themes = [
        t for t in themes
        if t not in ("Home Interiors", "City Architecture") or len(themes) > 1 or clean_p
    ]
    if not valid_themes and not clean_p:
        return None

    visit_grounding = get_day_visit_grounding(conn_viewer, date_str) if (conn_viewer and date_str) else None
    simplified = simplify_themes(valid_themes, max_hour=max_hr, min_hour=min_hr, visit_grounding=visit_grounding)
    loc = pick_best_location(locations, conn_viewer=conn_viewer, date_str=date_str, visit_grounding=visit_grounding)

    if len(clean_p) == 1:
        p_str = f"with {clean_p[0]}"
    elif len(clean_p) == 2:
        p_str = f"with {clean_p[0]} and {clean_p[1]}"
    elif len(clean_p) > 2:
        n_others = len(clean_p) - 2
        other_word = "other" if n_others == 1 else "others"
        p_str = f"with {clean_p[0]}, {clean_p[1]}, and {n_others} {other_word}"
    else:
        p_str = ""

    t_str = " & ".join(simplified)

    if t_str and loc and p_str:
        text = f"{t_str} in {loc} {p_str}."
    elif t_str and p_str:
        text = f"{t_str} {p_str}."
    elif t_str and loc:
        text = f"{t_str} in {loc}."
    elif loc and p_str:
        text = f"In {loc} {p_str}."
    elif p_str:
        text = f"{p_str[0].upper() + p_str[1:]}."
    elif t_str:
        text = f"{t_str}."
    else:
        return None

    title = text.rstrip(".")
    return title, text


def run_import():
    if not PHOTOS_DB.exists():
        print(f"[!] Error: {PHOTOS_DB} not found.")
        return

    print(f"[*] Reading daily summaries from {PHOTOS_DB}...")
    conn_photos = sqlite3.connect(PHOTOS_DB)
    conn_photos.row_factory = sqlite3.Row
    rows = conn_photos.execute("""
        SELECT date, title, summary, photo_count, locations, people, themes
        FROM daily_summaries
        ORDER BY date ASC;
    """).fetchall()
    conn_photos.close()
    print(f"[*] Loaded {len(rows)} raw daily summaries.")

    conn_viewer = sqlite3.connect(VIEWER_DB)
    # Check existing authentic user notes to protect them
    authentic_dates = {
        r[0] for r in conn_viewer.execute(
            "SELECT date FROM memories WHERE memory_id IN ('mem0:f0f86f52', 'mem2:f0f86f52', 'mem3:f0f86f52')"
        ).fetchall()
    }
    print(f"[*] Protecting {len(authentic_dates)} authentic Takeout user notes.")

    # Remove any existing photo_mem records to guarantee clean state
    conn_viewer.execute("DELETE FROM memories WHERE memory_id LIKE 'photo_mem_%';")

    accepted = 0
    rejected = 0

    for r in rows:
        d_str = r["date"]
        if d_str in authentic_dates:
            continue

        try:
            dt = datetime.strptime(d_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            start_s = float(dt.timestamp())
            end_s = start_s + 86400.0
        except ValueError:
            rejected += 1
            continue

        themes = json.loads(r["themes"] or "[]")
        people = json.loads(r["people"] or "[]")
        locations = json.loads(r["locations"] or "[]")

        clean_result = synthesize_clean_note(d_str, people, themes, locations, conn_viewer=conn_viewer)
        if not clean_result:
            rejected += 1
            continue

        title, text = clean_result
        mem_id = f"photo_mem_{d_str}"

        conn_viewer.execute("""
            INSERT INTO memories (memory_id, date, start_ts, end_ts, title, raw_text, raw_proto_hex)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(memory_id) DO UPDATE SET
                title = excluded.title,
                raw_text = excluded.raw_text;
        """, (mem_id, d_str, start_s, end_s, title, text, ""))

        accepted += 1

    conn_viewer.commit()
    total_after = conn_viewer.execute("SELECT count(*) FROM memories;").fetchone()[0]
    conn_viewer.close()

    print(f"[✓] Clean High-Signal Notes Ingestion Complete:")
    print(f"    - Accepted notes: {accepted:,}")
    print(f"    - Rejected low-quality / boilerplate: {rejected:,}")
    print(f"    - Total memories in timeline_viewer.db: {total_after:,}")


if __name__ == "__main__":
    run_import()
