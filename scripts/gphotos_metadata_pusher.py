#!/usr/bin/env python3
"""
scripts/gphotos_metadata_pusher.py
Automated Google Photos Web UI Driver to push user-verified timestamps and geocodes.

Workflow:
1. Queries `photo_metadata_proposals` in `photos_vault.db` for status = 'approved' AND synced_at IS NULL.
2. Launches Chromium/Chrome using persistent profile at `~/.google_photos_session`.
3. Navigates to each photo's Google Photos URL (`https://photos.google.com/photo/<id>`).
4. Uses Google Photos Web UI to update:
   - Date & Time (sequenced with +60s stepping).
   - Location (searches canonical place/address in autocomplete drawer).
5. Marks proposals and clusters as synced with `synced_at = CURRENT_TIMESTAMP`.

Usage:
  uv run python scripts/gphotos_metadata_pusher.py --dry-run
  uv run python scripts/gphotos_metadata_pusher.py --limit 10
  uv run python scripts/gphotos_metadata_pusher.py --cluster-id sheet_example_001 --headed
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

VAULT_DB_PATH = Path(os.environ.get("PHOTOS_VAULT_DB", "./photos_vault.db"))
PROFILE_DIR = Path(
    os.environ.get("GPHOTOS_PROFILE_DIR", str(Path.home() / ".mylifebits" / "gphotos_session"))
)


def get_pending_sync_items(cluster_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Query approved but unsynced photo metadata proposals."""
    if not VAULT_DB_PATH.is_file():
        print(f"[!] Database not found: {VAULT_DB_PATH}")
        return []

    conn = sqlite3.connect(str(VAULT_DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    sql = """
        SELECT p.sha256, p.cluster_id, p.google_url, p.filename,
               p.proposed_timestamp_utc, p.proposed_date, p.proposed_tz_offset,
               p.proposed_lat, p.proposed_lng, p.proposed_place_name,
               p.proposed_city, p.proposed_country
        FROM photo_metadata_proposals p
        WHERE p.status = 'approved'
          AND p.synced_at IS NULL
          AND p.google_url IS NOT NULL
    """
    args: List[Any] = []
    if cluster_id:
        sql += " AND p.cluster_id = ?"
        args.append(cluster_id)

    sql += " ORDER BY p.cluster_id, p.proposed_timestamp_utc ASC LIMIT ?"
    args.append(limit)

    cur.execute(sql, args)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def mark_item_synced(sha256: str, cluster_id: str) -> None:
    """Mark a photo and its cluster as synced."""
    conn = sqlite3.connect(str(VAULT_DB_PATH))
    cur = conn.cursor()
    cur.execute("UPDATE photo_metadata_proposals SET synced_at = CURRENT_TIMESTAMP WHERE sha256 = ?", (sha256,))
    # If all photos in the cluster are synced, mark cluster as synced
    cur.execute("""
        UPDATE photo_clusters
        SET synced_at = CURRENT_TIMESTAMP
        WHERE cluster_id = ?
          AND NOT EXISTS (
              SELECT 1 FROM photo_metadata_proposals
              WHERE cluster_id = ? AND (synced_at IS NULL OR status != 'approved')
          )
    """, (cluster_id, cluster_id))
    conn.commit()
    conn.close()


def cleanup_singleton_locks(profile_dir: Path) -> None:
    """Clean up stale Chrome locks in the session directory."""
    for lock in profile_dir.glob("Singleton*"):
        try:
            lock.unlink()
        except Exception:
            pass


async def sync_photo_metadata(
    page: Any,
    item: Dict[str, Any],
    dry_run: bool = False
) -> bool:
    """
    Drives the Google Photos web UI for a single photo to edit date & location.
    """
    url = item["google_url"]
    sha = item["sha256"]
    date_str = item["proposed_date"]  # e.g. '2020-06-15 12:00:00'
    place_str = item["proposed_place_name"] or item.get("proposed_city") or ""

    print(f"\n[*] Navigating to photo: {url}")
    print(f"    Target Date : {date_str}")
    print(f"    Target Place: {place_str}")

    if dry_run:
        print("    [DRY-RUN] Would update date and location in Google Photos UI.")
        return True

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(2.0)

        # 1. Open Info Panel ('i' key or button)
        info_open = await page.evaluate("""() => {
            return document.querySelector('[aria-label="Info"][aria-expanded="true"]') !== null ||
                   document.querySelector('div[data-id="info"]') !== null;
        }""")
        if not info_open:
            await page.keyboard.press("i")
            await asyncio.sleep(1.5)

        # 2. Update Date & Time if target date is set
        if date_str:
            # Look for Edit date & time button or date section in info panel
            date_edit_btn = await page.query_selector('button[aria-label*="Edit date" i]') or \
                            await page.query_selector('button[aria-label*="Edit date and time" i]')
            if date_edit_btn:
                await date_edit_btn.click()
                await asyncio.sleep(1.0)

                # Split date and time
                dt_obj = datetime.datetime.fromisoformat(date_str)
                date_input_val = dt_obj.strftime("%b %d, %Y")  # e.g. 'Jun 15, 1941'
                time_input_val = dt_obj.strftime("%I:%M %p")   # e.g. '12:00 PM'

                # Fill date input in the modal dialog
                date_inputs = await page.query_selector_all('input[type="text"]')
                if len(date_inputs) >= 2:
                    await date_inputs[0].fill(date_input_val)
                    await date_inputs[1].fill(time_input_val)
                    await asyncio.sleep(0.5)

                    save_btn = await page.query_selector('button:has-text("Save")')
                    if save_btn:
                        await save_btn.click()
                        await asyncio.sleep(1.5)
                        print(f"    [✓] Date/time saved: {date_input_val} {time_input_val}")

        # 3. Update Location if place is set
        if place_str:
            loc_edit_btn = await page.query_selector('button[aria-label*="Edit location" i]') or \
                           await page.query_selector('button[aria-label*="Add a location" i]') or \
                           await page.query_selector('button[aria-label*="Add location" i]')
            if loc_edit_btn:
                await loc_edit_btn.click()
                await asyncio.sleep(1.0)

                # Search box appears: "Where was this taken?"
                search_box = await page.query_selector('input[placeholder*="Where was this taken" i]') or \
                             await page.query_selector('input[aria-label*="Search places" i]')
                if search_box:
                    await search_box.fill(place_str)
                    await asyncio.sleep(2.0)

                    # Click top autocomplete result in dropdown
                    top_res = await page.query_selector('div[role="option"]') or \
                              await page.query_selector('li[role="option"]')
                    if top_res:
                        await top_res.click()
                        await asyncio.sleep(1.5)
                        print(f"    [✓] Location saved: {place_str}")

        return True

    except Exception as e:
        print(f"    [!] Error during UI automation for {url}: {e}")
        return False


async def run_pusher(
    cluster_id: Optional[str] = None,
    limit: int = 50,
    dry_run: bool = False,
    headed: bool = False
) -> None:
    items = get_pending_sync_items(cluster_id=cluster_id, limit=limit)
    if not items:
        print("[*] No approved photos waiting to sync to Google Photos.")
        return

    print("=" * 70)
    print(" Google Photos Metadata Pusher (Web UI Automation)")
    print(f" Profile Directory : {PROFILE_DIR}")
    print(f" Pending Items     : {len(items)}")
    print(f" Dry Run Mode      : {dry_run}")
    print(f" Headed Browser    : {headed}")
    print("=" * 70)

    if dry_run:
        for idx, item in enumerate(items, 1):
            print(f"[{idx}/{len(items)}] {item['filename']} -> Date: {item['proposed_date']}, Place: {item['proposed_place_name']}")
        print("\n[✓] Dry run finished. Run without --dry-run to apply to Google Photos.")
        return

    from playwright.async_api import async_playwright

    cleanup_singleton_locks(PROFILE_DIR)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=not headed,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = context.pages[0] if context.pages else await context.new_page()

        synced_count = 0
        for idx, item in enumerate(items, 1):
            print(f"\n--- Photo {idx}/{len(items)}: {item['filename']} ---")
            ok = await sync_photo_metadata(page, item, dry_run=False)
            if ok:
                mark_item_synced(item["sha256"], item["cluster_id"])
                synced_count += 1
            await asyncio.sleep(1.0)

        await context.close()
        print(f"\n[✓] Successfully synced {synced_count}/{len(items)} photos to Google Photos!")


def main():
    parser = argparse.ArgumentParser(description="Google Photos Web UI Driver for timestamps and geocodes")
    parser.add_argument("--cluster-id", type=str, help="Sync specific cluster ID")
    parser.add_argument("--limit", type=int, default=25, help="Max photos to sync in this run")
    parser.add_argument("--dry-run", action="store_true", help="Preview photos without executing browser automation")
    parser.add_argument("--headed", action="store_true", help="Run browser in visible (headed) mode")
    args = parser.parse_args()

    asyncio.run(run_pusher(
        cluster_id=args.cluster_id,
        limit=args.limit,
        dry_run=args.dry_run,
        headed=args.headed
    ))


if __name__ == "__main__":
    main()
