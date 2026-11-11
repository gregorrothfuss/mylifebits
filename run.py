#!/usr/bin/env python3
"""
Single-Command Launcher for Google Maps Timeline Studio & Health Engine.
Auto-initializes the database, performs multi-source fusion if needed, and starts the server.
"""

from __future__ import annotations

import os
import threading
import time
import webbrowser

from db import get_db_path, init_db
from diagnostics import TimelineDiagnosticsEngine
from importer import TimelineFusionImporter
from server import ThreadedTimelineServer


def main() -> None:
    print("==================================================================")
    print("      Google Maps Timeline Studio & Health Diagnostics Engine     ")
    print("==================================================================")

    db_path = get_db_path()
    init_db(db_path)

    importer = TimelineFusionImporter(db_path)
    c = importer.conn.cursor()
    c.execute("SELECT COUNT(*) FROM segments;")
    row = c.fetchone()
    count = int(row[0]) if row else 0

    if count == 0:
        print("\n[*] Initializing multi-source fusion database...")
        takeout_zip = os.path.expanduser(
            os.environ.get("TIMELINE_TAKEOUT_ZIP", "~/Downloads/Takeout.zip")
        )
        on_device_json = os.path.expanduser(
            os.environ.get("TIMELINE_ON_DEVICE_JSON", "~/Downloads/Timeline.json")
        )

        paths_map = None
        if os.path.exists(takeout_zip):
            res_takeout = importer.import_takeout_zip(takeout_zip, include_records=False)
            paths_map = res_takeout.get("paths_map")

        if os.path.exists(on_device_json):
            importer.import_on_device_json(on_device_json, paths_map=paths_map)

        print("\n[*] Running diagnostic pipeline...")
        diag = TimelineDiagnosticsEngine(db_path)
        diag.run_full_diagnostics()

    port = int(os.environ.get("TIMELINE_PORT", "8080"))
    public_url = os.environ.get("TIMELINE_PUBLIC_URL", "https://mylifebits.local")
    server = ThreadedTimelineServer(host="127.0.0.1", port=port)

    def open_browser() -> None:
        time.sleep(0.5)
        webbrowser.open(public_url)

    if os.environ.get("TIMELINE_NO_BROWSER", "").strip() not in ("1", "true", "yes"):
        threading.Thread(target=open_browser, daemon=True).start()

    server.start()


if __name__ == "__main__":
    main()
