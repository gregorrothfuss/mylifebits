#!/usr/bin/env python3
"""
Import daily summaries from photos_vault.db into timeline_viewer.db (memories)
for web UI display. ODLH export of notes is omitted because Google Maps
Timeline no longer contains viewholders or layout code to render note cards.
"""

import sys
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
PHOTOS_DB = Path("/Users/rothfuss/projects/gregor_cos/photos_vault.db")
VIEWER_DB = WORKSPACE_DIR / "timeline_viewer.db"

def encode_varint(val: int) -> bytes:
    res = bytearray()
    while val > 0x7f:
        res.append((val & 0x7f) | 0x80)
        val >>= 7
    res.append(val & 0x7f)
    return bytes(res)

def encode_len_delim(tag: int, payload: bytes) -> bytes:
    header = encode_varint((tag << 3) | 2)
    length = encode_varint(len(payload))
    return header + length + payload

def build_note_proto(start_s: int, end_s: int, note_text: str, seg_id: str) -> bytes:
    """
    Constructs a LocationHistorySegment proto for a Note memory (segment_type=4).
    Wire structure verified bit-for-bit against authentic baseline row 57493:
      field 1: startTime (Timestamp { seconds })
      field 2: endTime   (Timestamp { seconds })
      field 3: payload   (iqay { field 4: TimelineMemory { field 2: Note { field 1: noteText } } })
      field 6: segmentId (string)
      field 10: isFinalized (varint 1)
    """
    t_start = encode_varint((1 << 3) | 0) + encode_varint(start_s)
    f1 = encode_len_delim(1, t_start)

    t_end = encode_varint((1 << 3) | 0) + encode_varint(end_s)
    f2 = encode_len_delim(2, t_end)

    note_msg = encode_len_delim(1, note_text.encode("utf-8"))
    mem_msg = encode_len_delim(2, note_msg)
    payload_msg = encode_len_delim(4, mem_msg)
    f3 = encode_len_delim(3, payload_msg)

    f6 = encode_len_delim(6, seg_id.encode("utf-8"))
    f10 = encode_varint((10 << 3) | 0) + encode_varint(1)

    return f1 + f2 + f3 + f6 + f10

def run_import():
    if not PHOTOS_DB.exists():
        print(f"[!] Error: {PHOTOS_DB} not found.")
        sys.exit(1)

    print(f"[*] Reading daily summaries from {PHOTOS_DB}...")
    conn_photos = sqlite3.connect(PHOTOS_DB)
    conn_photos.row_factory = sqlite3.Row
    rows = conn_photos.execute("""
        SELECT date, title, summary, photo_count
        FROM daily_summaries
        WHERE summary IS NOT NULL AND length(trim(summary)) > 0
        ORDER BY date ASC;
    """).fetchall()
    conn_photos.close()
    print(f"[*] Found {len(rows)} daily summaries in photos_vault.db.")

    print(f"[*] Connecting to {VIEWER_DB}...")
    conn_viewer = sqlite3.connect(VIEWER_DB)
    conn_viewer.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id TEXT UNIQUE,
            date TEXT,
            start_ts REAL,
            end_ts REAL,
            title TEXT,
            raw_text TEXT,
            raw_proto_hex TEXT
        );
    """)

    existing_mem_dates = {
        r[0] for r in conn_viewer.execute("SELECT date FROM memories WHERE memory_id LIKE 'mem%:f0f86f52'").fetchall()
    }
    print(f"[*] Preserving {len(existing_mem_dates)} authentic native Google Timeline memory dates.")

    imported_count = 0
    records = []

    for r in rows:
        d_str = r["date"]
        # Skip if already has an authentic Google takeout note
        if d_str in existing_mem_dates:
            continue

        try:
            dt = datetime.strptime(d_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            start_s = int(dt.timestamp())
            end_s = start_s + 86400
        except ValueError:
            continue

        title = (r["title"] or "").strip()
        summary = (r["summary"] or "").strip()
        if not summary:
            continue

        if title and not summary.startswith(title):
            full_note = f"{title}: {summary}"
        else:
            full_note = summary

        mem_id = f"photo_mem_{d_str}"
        proto_bytes = build_note_proto(start_s, end_s, full_note, mem_id)

        conn_viewer.execute("""
            INSERT INTO memories (memory_id, date, start_ts, end_ts, title, raw_text, raw_proto_hex)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(memory_id) DO UPDATE SET
                title = excluded.title,
                raw_text = excluded.raw_text,
                raw_proto_hex = excluded.raw_proto_hex;
        """, (mem_id, d_str, float(start_s), float(end_s), title or "Photo Day Summary", full_note, proto_bytes.hex()))

        records.append((start_s, end_s, d_str, mem_id, proto_bytes))
        imported_count += 1

    conn_viewer.commit()
    conn_viewer.close()
    print(f"[✓] Successfully upserted {imported_count} photo day notes into {VIEWER_DB}!")
    print("[*] ODLH export omitted: notes are preserved exclusively in timeline_viewer.db for the local UI, as Google Maps Timeline no longer contains viewholders to render note cards.")

if __name__ == "__main__":
    run_import()

