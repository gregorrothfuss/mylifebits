#!/usr/bin/env python3
"""
scripts/gphotos_incremental_sync.py
Incremental Google Photos Synchronization Engine using Playwright CDP.

Bypasses Google Photos API limitations (GPS EXIF stripping, Picker UI mandates)
by automating an authenticated browser session navigating to 'Recently Added' (_tra_).
Downloads original, uncompressed photo binaries (with 100% intact EXIF GPS) via Shift+D,
stages them into an inbox, ingests them into photos_vault.db, and mirrors to timeline_viewer.db.
"""

import os
import sys
import re
import json
import time
import random
import asyncio
import argparse
import datetime
from pathlib import Path
from typing import Optional, Dict, Any

# Ensure project paths are accessible
WORKSPACE_DIR = Path(__file__).resolve().parent.parent
COS_DIR = Path("/Users/rothfuss/projects/gregor_cos")
DEFAULT_PROFILE_DIR = Path.home() / ".google_photos_session"
DEFAULT_INBOX_DIR = Path.home() / "Downloads" / "photo_inbox"
STATE_FILE = DEFAULT_PROFILE_DIR / "sync_state.json"
GPHOTOS_RECENTLY_ADDED_URL = "https://photos.google.com/search/_tra_"

# Try importing loose file processor from photo_pipeline
if str(COS_DIR) not in sys.path:
    sys.path.insert(0, str(COS_DIR))

try:
    from photo_pipeline import process_loose_files
    HAS_PIPELINE = True
except ImportError:
    HAS_PIPELINE = False


def load_sync_state(state_file: Path) -> Dict[str, Any]:
    if state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[State] Warning reading state file: {e}")
    return {
        "last_synced_photo_id": None,
        "last_sync_timestamp": None,
        "total_synced_count": 0
    }


def save_sync_state(state_file: Path, state: Dict[str, Any]):
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    print(f"[State] Saved sync state (checkpoint: {state.get('last_synced_photo_id')})")


def extract_photo_id(url: str) -> Optional[str]:
    # Match https://photos.google.com/search/_tra_/photo/<photo_id> or /photo/<photo_id>
    m = re.search(r"/photo/([^/?#]+)", url)
    return m.group(1) if m else None


async def run_sync(
    login_mode: bool = False,
    headless: bool = True,
    limit: int = 100,
    inbox_dir: Path = DEFAULT_INBOX_DIR,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    dry_run: bool = False,
    no_ingest: bool = False
):
    from playwright.async_api import async_playwright

    profile_dir.mkdir(parents=True, exist_ok=True)
    inbox_dir.mkdir(parents=True, exist_ok=True)
    state_file = profile_dir / "sync_state.json"
    sync_state = load_sync_state(state_file)
    last_checkpoint_id = sync_state.get("last_synced_photo_id")

    print("=" * 60)
    print(" Google Photos Incremental CDP Sync Engine")
    print("=" * 60)
    print(f"Profile Directory : {profile_dir}")
    print(f"Inbox Directory   : {inbox_dir}")
    print(f"Last Checkpoint   : {last_checkpoint_id or 'None (initial pass)'}")
    print(f"Sync Limit        : {limit} photo(s)")
    print(f"Headless Mode     : {headless and not login_mode}")
    print("=" * 60)

    async with async_playwright() as p:
        browser_context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=headless and not login_mode,
            accept_downloads=True,
            viewport={"width": 1280, "height": 850},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox"
            ]
        )

        page = browser_context.pages[0] if browser_context.pages else await browser_context.new_page()

        if login_mode:
            print("\n[LOGIN MODE] Opening Google Photos in interactive browser...")
            print("Please sign in with your Google Account in the browser window.")
            print("Once you see your photos loaded, close the browser window or press Enter here.\n")
            await page.goto("https://photos.google.com/", wait_until="domcontentloaded")

            # Wait until user reaches photos.google.com (not accounts.google.com)
            while True:
                if "photos.google.com" in page.url and "accounts.google.com" not in page.url:
                    print("[✓] Detected active Google Photos session!")
                    break
                await asyncio.sleep(2)

            print("[✓] Login session preserved. You can now run incremental syncs in headless mode.")
            await browser_context.close()
            return

        # Regular incremental sync pass
        print(f"\n[1/4] Navigating to Recently Added: {GPHOTOS_RECENTLY_ADDED_URL} ...")
        await page.goto(GPHOTOS_RECENTLY_ADDED_URL, wait_until="networkidle")

        # Check if auth required
        if "accounts.google.com" in page.url:
            print("\n[!] Authentication required! Google redirected to login page.")
            print("Run this command once interactively to log in:")
            print("  uv run python scripts/gphotos_incremental_sync.py --login")
            await browser_context.close()
            sys.exit(1)

        print("[2/4] Inspecting photo stream on Recently Added page...")
        # Wait for grid of photos
        try:
            await page.wait_for_selector('a[href*="/photo/"], div[role="grid"]', timeout=15000)
        except Exception:
            print("[!] Timeout waiting for photo grid to load.")
            await browser_context.close()
            sys.exit(1)

        # Find the very first (newest) photo item
        first_item = page.locator('a[href*="/photo/"]').first
        if not await first_item.count():
            # Try finding thumbnail tile in grid
            first_item = page.locator('div[role="grid"] [tabindex="0"]').first

        if not await first_item.count():
            print("[-] No photos detected in Recently Added grid.")
            await browser_context.close()
            return

        # Click the first photo to enter lightbox viewer
        print("[3/4] Entering lightbox viewer to traverse photos...")
        await first_item.click()
        await page.wait_for_timeout(1500)

        current_url = page.url
        current_id = extract_photo_id(current_url)

        if not current_id:
            print(f"[-] Could not extract photo ID from URL: {current_url}")
            await browser_context.close()
            return

        if current_id == last_checkpoint_id:
            print(f"[✓] Already fully synchronized! Top photo ({current_id}) matches checkpoint.")
            await browser_context.close()
            return

        head_photo_id = current_id
        downloaded_files = []
        consecutive_same_url = 0

        print(f"[*] Starting traversal from newest photo: {head_photo_id}")

        while len(downloaded_files) < limit:
            current_id = extract_photo_id(page.url)

            if not current_id:
                print(f"[-] Exited photo viewer at URL: {page.url}")
                break

            if current_id == last_checkpoint_id:
                print(f"[✓] Reached checkpoint ID {last_checkpoint_id}. Sync boundary reached.")
                break

            print(f"  -> [{len(downloaded_files) + 1}/{limit}] Downloading photo: {current_id}")

            if not dry_run:
                try:
                    async with page.expect_download(timeout=20000) as download_info:
                        await page.keyboard.press("Shift+KeyD")
                    download = await download_info.value
                    filename = download.suggested_filename
                    target_path = inbox_dir / filename
                    await download.save_as(str(target_path))
                    downloaded_files.append(target_path)
                    print(f"     Saved: {filename} ({os.path.getsize(target_path):,} bytes)")
                except Exception as e:
                    print(f"     [Download Warning] {e}")
            else:
                downloaded_files.append(Path(f"dry_run_{current_id}.jpg"))
                print(f"     [DRY RUN] Would download {current_id}")

            # Natural jitter delay between downloads
            await asyncio.sleep(random.uniform(0.7, 1.2))

            # Step to next photo (older photo in _tra_)
            prev_url = page.url
            await page.keyboard.press("ArrowRight")
            await page.wait_for_timeout(600)

            if page.url == prev_url:
                consecutive_same_url += 1
                if consecutive_same_url >= 2:
                    print("[✓] Reached end of available stream.")
                    break
            else:
                consecutive_same_url = 0

        await browser_context.close()

    print(f"\n[4/4] Sync complete. Downloaded {len(downloaded_files)} new photo(s).")

    # Update state checkpoint
    if head_photo_id and not dry_run and downloaded_files:
        sync_state["last_synced_photo_id"] = head_photo_id
        sync_state["last_sync_timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        sync_state["total_synced_count"] = sync_state.get("total_synced_count", 0) + len(downloaded_files)
        save_sync_state(state_file, sync_state)

    # Ingest into photos_vault.db and mirror to timeline_viewer.db
    if downloaded_files and not dry_run and not no_ingest:
        if HAS_PIPELINE:
            print("\n=== Ingesting into Photos Vault ===")
            summary = process_loose_files(inbox_dir, source_label="gphotos_cdp", delete_after=True)
            print(f"[Vault Ingest] New items: {summary.get('new')}, Dupes: {summary.get('duplicates')}")

            # Trigger clean reindex to timeline_viewer.db
            reindex_script = WORKSPACE_DIR / "scripts" / "reindex_photos_clean.py"
            if reindex_script.exists():
                print("\n=== Mirroring to timeline_viewer.db ===")
                proc = await asyncio.create_subprocess_exec(
                    sys.executable, str(reindex_script),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()
                if proc.returncode == 0:
                    print("[✓] timeline_viewer.db photos synchronized!")
                else:
                    print(f"[-] Reindex error: {stderr.decode()}")
        else:
            print(f"[!] photo_pipeline not available. Downloaded files remain in {inbox_dir}")


def main():
    parser = argparse.ArgumentParser(
        description="Incremental Google Photos Synchronization via CDP / Playwright"
    )
    parser.add_argument("--login", action="store_true", help="Launch visible browser to perform one-time Google login")
    parser.add_argument("--headless", action="store_true", default=True, help="Run headless (default: True)")
    parser.add_argument("--no-headless", dest="headless", action="store_false", help="Run with visible browser window")
    parser.add_argument("--limit", type=int, default=100, help="Maximum number of photos to download (default: 100)")
    parser.add_argument("--inbox-dir", type=Path, default=DEFAULT_INBOX_DIR, help="Destination directory for downloads")
    parser.add_argument("--profile-dir", type=Path, default=DEFAULT_PROFILE_DIR, help="Persistent browser profile dir")
    parser.add_argument("--dry-run", action="store_true", help="Inspect and report photos without downloading")
    parser.add_argument("--no-ingest", action="store_true", help="Do not trigger photos_vault.db ingestion")

    args = parser.parse_args()

    asyncio.run(run_sync(
        login_mode=args.login,
        headless=args.headless,
        limit=args.limit,
        inbox_dir=args.inbox_dir,
        profile_dir=args.profile_dir,
        dry_run=args.dry_run,
        no_ingest=args.no_ingest
    ))


if __name__ == "__main__":
    main()
