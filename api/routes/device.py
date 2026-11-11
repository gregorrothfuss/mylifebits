"""
Connected Device (Pixel ADB) Control, Screen Capture, and Timeline Sync API.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any, Dict

from api.db import get_db, get_db_path
from api.response import Response, error_response, json_response
from api.router import Request, router


@router.get("/api/device/screen")
def get_device_screen(req: Request) -> Response:
    """Captures live screen from connected Android device via ADB."""
    try:
        from gmm_device_bridge import get_bridge

        bridge = get_bridge()
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
        from gmm_device_bridge import get_bridge

        bridge = get_bridge()
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
        from gmm_device_bridge import get_bridge

        bridge = get_bridge()
        scratch_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scratch")
        db_candidates = (
            sorted([os.path.join(scratch_dir, f) for f in os.listdir(scratch_dir) if f.startswith("odlh_v") and f.endswith(".db")])
            if os.path.exists(scratch_dir)
            else []
        )
        gms_db = db_candidates[-1] if db_candidates else os.path.join(scratch_dir, "odlh_v39_flawless.db")
        res = bridge.get_day_comparison(date_str, get_db_path(), gms_db)
        return json_response(res)
    except Exception as e:
        return error_response(f"Error comparing day with device: {e}", status_code=500)


@router.post("/api/device/touch")
def send_device_touch(req: Request) -> Response:
    """Sends tap or swipe event to connected Android device."""
    data = req.json()
    action = str(data.get("action", "tap")).lower()
    if action not in ("tap", "swipe", "key"):
        return error_response("Invalid touch action", status_code=400)

    x = int(data.get("x", 0))
    y = int(data.get("y", 0))
    x2 = int(data["x2"]) if data.get("x2") is not None else None
    y2 = int(data["y2"]) if data.get("y2") is not None else None
    dur = int(data.get("duration_ms", 200))

    for coord in (x, y, x2, y2):
        if coord is not None and (coord < 0 or coord > 10000):
            return error_response("Touch coordinates out of bounds", status_code=400)
    if dur < 10 or dur > 10000:
        return error_response("Touch duration out of bounds", status_code=400)

    try:
        from gmm_device_bridge import get_bridge

        bridge = get_bridge()
        success = bridge.send_touch(action, x, y, x2, y2, dur)
        return json_response({"status": "SUCCESS" if success else "ERROR"})
    except ValueError as ve:
        return error_response(str(ve), status_code=400)
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
        from gmm_device_bridge import get_bridge

        bridge = get_bridge()
        if key_code is not None:
            kc = int(key_code)
            if kc < 0 or kc > 500:
                return error_response("Keycode out of bounds", status_code=400)
            success = bridge.send_key(kc)
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
            elif isinstance(key, str) and len(key) == 1:
                success = bridge.send_text(key)
            else:
                success = False
        else:
            success = False
        return json_response({"status": "SUCCESS" if success else "ERROR"})
    except ValueError as ve:
        return error_response(str(ve), status_code=400)
    except Exception as e:
        return error_response(f"Keyboard command failed: {e}", status_code=500)


@router.post("/api/device/open-timeline")
def send_device_open_timeline(req: Request) -> Response:
    """Directly opens Google Maps Timeline UI."""
    try:
        from gmm_device_bridge import get_bridge

        bridge = get_bridge()
        res = bridge.open_timeline()
        return json_response(res)
    except Exception as e:
        return error_response(f"Opening timeline failed: {e}", status_code=500)


@router.post("/api/device/intent-day")
def send_device_intent_day(req: Request) -> Response:
    """Navigates connected Google Maps Timeline UI to target date via deep intent."""
    data = req.json()
    date_str = str(data.get("date") or "").strip()
    if not date_str:
        return error_response("Missing date parameter", status_code=400)

    try:
        from gmm_device_bridge import get_bridge

        bridge = get_bridge()
        res = bridge.intent_to_day(date_str)
        return json_response(res)
    except ValueError as ve:
        return error_response(str(ve), status_code=400)
    except Exception as e:
        return error_response(f"Intent navigation failed: {e}", status_code=500)


@router.post("/api/device/resolve-conflict")
def resolve_device_conflict(req: Request) -> Response:
    """Resolves timeline discrepancy by accepting device truth or master truth."""
    data = req.json()
    action = data.get("action")
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
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent.parent
    sync_script = repo_root / "scripts" / "sync_from_prod_via_pixel8.py"
    if not sync_script.is_file():
        return error_response("Device sync script not installed", status_code=404)

    try:
        res = subprocess.run(
            [sys.executable, str(sync_script)],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if res.returncode == 0:
            return json_response({"status": "SUCCESS", "message": "Successfully synchronized live database from device!"})
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

        result = reinfer_day_timeline(get_db_path(), date_str, exclude_anomalies=exclude_anomalies)
        return json_response({"status": "SUCCESS", "result": result})
    except Exception as e:
        return error_response(f"Re-inference failed: {e}", status_code=500)
