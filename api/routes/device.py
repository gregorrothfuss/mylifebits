"""
Connected Device (Pixel ADB) Control, Screen Capture, and Timeline Sync API.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any, Dict

from api.db import DEFAULT_DB_PATH, get_db
from api.response import Response, error_response, json_response
from api.router import Request, router


@router.get("/api/device/screen")
def get_device_screen(req: Request) -> Response:
    """Captures live screen from connected Android device via ADB."""
    try:
        from gmm_device_bridge import GMMDeviceBridge

        bridge = GMMDeviceBridge()
        img_bytes = bridge.capture_screen_bytes()
        return Response(
            body=img_bytes,
            status_code=200,
            content_type="image/jpeg",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
            },
        )
    except Exception as e:
        return error_response(f"ADB screen capture failed: {e}", status_code=500)


@router.get("/api/device/status")
def get_device_status(req: Request) -> Response:
    """Returns connected status and ADB serial of target device."""
    try:
        from gmm_device_bridge import GMMDeviceBridge

        bridge = GMMDeviceBridge()
        return json_response({
            "status": "SUCCESS",
            "connected": bridge.is_connected(),
            "serial": bridge.serial,
        })
    except Exception as e:
        return json_response({
            "status": "ERROR",
            "connected": False,
            "error": str(e),
        })


@router.get("/api/device/compare-day")
def get_device_compare_day(req: Request) -> Response:
    """Compares database timeline against authentic GMS timeline extracted from device."""
    date_str = req.get_str("date")
    if not date_str:
        return error_response("Missing date parameter", status_code=400)

    try:
        from gmm_device_bridge import GMMDeviceBridge

        bridge = GMMDeviceBridge()
        scratch_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scratch")
        db_candidates = (
            sorted([os.path.join(scratch_dir, f) for f in os.listdir(scratch_dir) if f.startswith("odlh_v") and f.endswith(".db")])
            if os.path.exists(scratch_dir)
            else []
        )
        gms_db = db_candidates[-1] if db_candidates else os.path.join(scratch_dir, "odlh_v39_flawless.db")
        res = bridge.get_day_comparison(date_str, DEFAULT_DB_PATH, gms_db)
        return json_response(res)
    except Exception as e:
        return error_response(f"Error comparing day with device: {e}", status_code=500)


@router.post("/api/device/touch")
def send_device_touch(req: Request) -> Response:
    """Sends tap or swipe event to connected Android device."""
    data = req.json()
    action = data.get("action", "tap")
    x = int(data.get("x", 0))
    y = int(data.get("y", 0))
    x2 = data.get("x2")
    y2 = data.get("y2")
    dur = int(data.get("duration_ms", 200))

    try:
        from gmm_device_bridge import GMMDeviceBridge

        bridge = GMMDeviceBridge()
        success = bridge.send_touch(action, x, y, int(x2) if x2 is not None else None, int(y2) if y2 is not None else None, dur)
        return json_response({"status": "SUCCESS" if success else "ERROR"})
    except Exception as e:
        return error_response(f"Touch command failed: {e}", status_code=500)


@router.post("/api/device/keyboard")
def send_device_keyboard(req: Request) -> Response:
    """Sends text or special key to connected Android device."""
    data = req.json()
    key = data.get("key")
    text = data.get("text")
    key_code = data.get("keyCode")

    try:
        from gmm_device_bridge import GMMDeviceBridge

        bridge = GMMDeviceBridge()
        if key_code is not None:
            success = bridge.send_key(int(key_code))
        elif text:
            success = bridge.send_text(str(text))
        elif key:
            key_map = {
                "Backspace": 67,
                "Enter": 66,
                "Tab": 61,
                "Escape": 4,
                "ArrowUp": 19,
                "ArrowDown": 20,
                "ArrowLeft": 21,
                "ArrowRight": 22,
                "Home": 3,
                "Delete": 112,
                " ": 62,
            }
            if key in key_map:
                success = bridge.send_key(key_map[key])
            elif len(key) == 1:
                success = bridge.send_text(key)
            else:
                success = False
        else:
            success = False
        return json_response({"status": "SUCCESS" if success else "ERROR"})
    except Exception as e:
        return error_response(f"Keyboard command failed: {e}", status_code=500)


@router.post("/api/device/open-timeline")
def send_device_open_timeline(req: Request) -> Response:
    """Directly opens Google Maps Timeline UI."""
    try:
        from gmm_device_bridge import GMMDeviceBridge

        bridge = GMMDeviceBridge()
        res = bridge.open_timeline()
        return json_response(res)
    except Exception as e:
        return error_response(f"Opening timeline failed: {e}", status_code=500)


@router.post("/api/device/intent-day")
def send_device_intent_day(req: Request) -> Response:
    """Navigates connected Google Maps Timeline UI to target date via deep intent."""
    data = req.json()
    date_str = data.get("date")
    if not date_str:
        return error_response("Missing date parameter", status_code=400)

    try:
        from gmm_device_bridge import GMMDeviceBridge

        bridge = GMMDeviceBridge()
        res = bridge.intent_to_day(date_str)
        return json_response(res)
    except Exception as e:
        return error_response(f"Intent navigation failed: {e}", status_code=500)


@router.post("/api/device/resolve-conflict")
def resolve_device_conflict(req: Request) -> Response:
    """Resolves timeline discrepancy by accepting device truth or master truth."""
    data = req.json()
    action = data.get("action")
    date_str = data.get("date")
    seg_id = data.get("segment_id")
    patch = data.get("patch", {})

    with get_db() as conn:
        c = conn.cursor()
        if action == "accept_gmm" and patch and seg_id:
            c.execute(
                """
                UPDATE segments
                SET place_name = COALESCE(?, place_name),
                    segment_type = COALESCE(?, segment_type),
                    start_time = COALESCE(?, start_time),
                    end_time = COALESCE(?, end_time),
                    start_ts = COALESCE(?, start_ts),
                    end_ts = COALESCE(?, end_ts),
                    duration_minutes = COALESCE(?, duration_minutes)
                WHERE id = ?;
                """,
                (
                    patch.get("name"),
                    patch.get("segment_type"),
                    patch.get("start_time"),
                    patch.get("end_time"),
                    patch.get("start_ts"),
                    patch.get("end_ts"),
                    patch.get("duration_minutes"),
                    seg_id,
                ),
            )

    return json_response({"status": "SUCCESS", "action": action, "segment_id": seg_id})


@router.post("/api/sync-device")
def sync_device(req: Request) -> Response:
    """Triggers live extraction of timeline databases from connected device."""
    try:
        res = subprocess.run(
            ["python3", "export_gmm_live.py"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if res.returncode == 0:
            return json_response({"status": "SUCCESS", "message": "Successfully synchronized live database from device!"})
        else:
            return json_response({"status": "WARNING", "message": res.stderr or res.stdout or "Sync completed with warnings."})
    except Exception as e:
        return error_response(f"Sync error: {e}", status_code=500)


@router.post("/api/reinfer-day")
def reinfer_day(req: Request) -> Response:
    """Reinfers day timeline segments from raw sensor telemetry."""
    data = req.json()
    date_str = data.get("date")
    exclude_anomalies = bool(data.get("exclude_anomalies", True))
    if not date_str:
        return error_response("Missing date parameter", status_code=400)

    try:
        from reinference import reinfer_day_timeline

        result = reinfer_day_timeline(DEFAULT_DB_PATH, date_str, exclude_anomalies=exclude_anomalies)
        return json_response({"status": "SUCCESS", "result": result})
    except Exception as e:
        return error_response(f"Re-inference failed: {e}", status_code=500)
