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
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
PHOTOS_DB = Path("/Users/rothfuss/projects/gregor_cos/photos_vault.db")
VIEWER_DB = WORKSPACE_DIR / "timeline_viewer.db"


def normalize_loc(loc: str) -> str:
    if not loc:
        return ""
    loc = loc.replace("ZÜrich", "Zürich").replace("Zuerich", "Zürich")
    if "/" in loc:
        parts = [p.strip() for p in loc.split("/")]
        loc = parts[-1] if len(parts) > 1 else parts[0]
    if loc == "New york":
        loc = "New York"
    return loc.strip()


def simplify_themes(themes: list[str]) -> list[str]:
    has_dinner = "Dinner Gathering" in themes
    has_dining = "Dining & Food" in themes
    has_museum = "Museum Exhibits" in themes
    has_art = "Sculptures & Art" in themes
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

    out = []
    if has_dinner:
        out.append("Dinner")
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


def synthesize_clean_note(date_str, people, themes, locations):
    """
    Quality gate & clean synthesis. Returns (title, text) or None if low quality.
    """
    clean_p = [p for p in people if p != "Gregor J. Rothfuss"]

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

    simplified = simplify_themes(valid_themes)
    loc = normalize_loc(locations[0]) if locations else ""

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

        clean_result = synthesize_clean_note(d_str, people, themes, locations)
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
