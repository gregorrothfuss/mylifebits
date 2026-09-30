#!/usr/bin/env python3
"""
Imports strictly HIGH-QUALITY, high-signal daily photo notes into timeline_viewer.db.
Filters out:
- All OCR garbage snippets ('Visible signage in the shots included...').
- All boilerplate template filler ('A collection of N photos documented in...').
- All low-quality days lacking verified visual themes or identified companions (~50% of days).

Preserves authentic user Takeout notes.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
PHOTOS_DB = Path("/Users/rothfuss/projects/gregor_cos/photos_vault.db")
VIEWER_DB = WORKSPACE_DIR / "timeline_viewer.db"


def synthesize_clean_note(date_str, count, people, themes, locations):
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

    # People phrasing
    if len(clean_p) == 1:
        p_str = f"with {clean_p[0]}"
    elif len(clean_p) == 2:
        p_str = f"with {clean_p[0]} and {clean_p[1]}"
    elif len(clean_p) > 2:
        p_str = f"with {clean_p[0]}, {clean_p[1]}, and {len(clean_p)-2} others"
    else:
        p_str = ""

    # Theme phrasing
    if len(valid_themes) == 1:
        t_str = valid_themes[0]
    elif len(valid_themes) == 2:
        t_str = f"{valid_themes[0]} and {valid_themes[1]}"
    elif len(valid_themes) > 2:
        t_str = f"{valid_themes[0]}, {valid_themes[1]}, and {valid_themes[2]}"
    else:
        t_str = ""

    # Clean location
    loc_str = locations[0] if locations else ""

    parts = []
    if t_str and loc_str:
        parts.append(f"{t_str} in {loc_str}")
    elif t_str:
        parts.append(t_str)
    elif loc_str:
        parts.append(f"Photos in {loc_str}")
    else:
        parts.append("Day moments")

    if p_str:
        parts.append(p_str)

    text = " ".join(parts).strip()
    text = text[0].upper() + text[1:] + f" ({count} photos)."
    title = t_str or (f"With {clean_p[0]}" if clean_p else loc_str or "Photo Highlights")
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
        count = r["photo_count"] or 1

        clean_result = synthesize_clean_note(d_str, count, people, themes, locations)
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

    print(f"[✓] Quality Gate Filter Complete:")
    print(f"    - Accepted high-quality notes: {accepted:,}")
    print(f"    - Rejected low-quality boilerplate days: {rejected:,}")
    print(f"    - Total memories in timeline_viewer.db: {total_after:,}")


if __name__ == "__main__":
    run_import()
