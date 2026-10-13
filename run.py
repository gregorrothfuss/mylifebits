#!/usr/bin/env python3
"""
Single-Command Launcher for Google Maps Timeline Studio & Health Engine.
Auto-initializes the database, performs multi-source fusion if needed, and starts the server.
"""

import os
import sys
import webbrowser
import threading
import time

from db import init_db, DEFAULT_DB_PATH
from importer import TimelineFusionImporter
from diagnostics import TimelineDiagnosticsEngine
from server import ThreadedTimelineServer


def main():
    print("==================================================================")
    print("      Google Maps Timeline Studio & Health Diagnostics Engine     ")
    print("==================================================================")

    db_path = DEFAULT_DB_PATH
    first_run = not os.path.exists(db_path)

    init_db(db_path)

    # Check if database has segments
    importer = TimelineFusionImporter(db_path)
    c = importer.conn.cursor()
    c.execute("SELECT COUNT(*) FROM segments;")
    count = c.fetchone()[0]

    if count == 0:
        print("\n[*] Initializing multi-source fusion database...")
        takeout_zip = os.path.expanduser("~/Downloads/lh-20241129T224901Z-001.zip")
        on_device_json = os.path.expanduser("~/Downloads/Timeline-20260707.json")

        paths_map = None
        if os.path.exists(takeout_zip):
            res_takeout = importer.import_takeout_zip(takeout_zip, include_records=False)
            paths_map = res_takeout.get("paths_map")

        if os.path.exists(on_device_json):
            importer.import_on_device_json(on_device_json, paths_map=paths_map)

        print("\n[*] Running diagnostic pipeline...")
        diag = TimelineDiagnosticsEngine(db_path)
        diag.run_full_diagnostics()

    port = 8080
    server = ThreadedTimelineServer(host="127.0.0.1", port=port)

    # Auto-open browser after 0.5s
    def open_browser():
        time.sleep(0.5)
        webbrowser.open(f"http://localhost:{port}")

    threading.Thread(target=open_browser, daemon=True).start()

    server.start()


if __name__ == "__main__":
    main()
