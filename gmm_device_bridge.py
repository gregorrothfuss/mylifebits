"""
Android GMM Device Bridge & Timeline Comparator Engine.
Provides high-speed screen streaming, touch input forwarding,
timeline intent navigation (including pre-1990 access),
and side-by-side Studio vs GMM comparison.
"""

import os
os.environ["ADB_USB"] = "0"
os.environ["ADB_MDNS"] = "0"
os.environ["ADB_MDNS_AUTO_CONNECT"] = "0"
import time
import json
import sqlite3
import datetime
import subprocess
from typing import Dict, Any, List, Optional, Tuple

import io
import threading
from PIL import Image

ADB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "platform-tools", "adb")
DEFAULT_SERIAL = "emulator-5554"
_EMPTY_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
)


ADB_ENV = {
    **os.environ,
    "ADB_USB": "0",
    "ADB_MDNS": "0",
    "ADB_MDNS_AUTO_CONNECT": "0",
    "ADB_MDNS_OPENSCREEN": "0",
}


class GMMDeviceBridge:
    _cached_jpeg: bytes = b""
    _last_capture: float = 0.0
    _last_request_time: float = 0.0
    _last_serial_check: float = 0.0
    _cached_serial: str = DEFAULT_SERIAL
    _native_size: Tuple[int, int] = (1080, 2400)
    _rendered_size: Tuple[int, int] = (540, 1200)
    _thread_running: bool = False
    _worker_thread = None
    _lock = threading.Lock()

    def __init__(self, serial: Optional[str] = None):
        self.adb = ADB_PATH if os.path.exists(ADB_PATH) else "adb"
        self.serial = serial or self._detect_best_serial(DEFAULT_SERIAL)
        self._ensure_worker_running()

    def _ensure_worker_running(self) -> None:
        with GMMDeviceBridge._lock:
            if not GMMDeviceBridge._thread_running:
                GMMDeviceBridge._thread_running = True
                GMMDeviceBridge._last_request_time = time.time()
                GMMDeviceBridge._worker_thread = threading.Thread(
                    target=self._capture_worker_loop,
                    daemon=True
                )
                GMMDeviceBridge._worker_thread.start()

    def _capture_worker_loop(self) -> None:
        while GMMDeviceBridge._thread_running:
            try:
                now = time.time()
                # Idle backoff if no HTTP screen request received in last 8 seconds
                if now - GMMDeviceBridge._last_request_time > 8.0:
                    time.sleep(0.4)
                    continue

                active_serial = self._detect_best_serial(self.serial)
                self.serial = active_serial

                res = subprocess.run(
                    [self.adb, "-s", self.serial, "exec-out", "screencap", "-p"],
                    capture_output=True,
                    timeout=1.2,
                    env=ADB_ENV
                )
                if res.stdout and res.stdout[:4] == b"\x89PNG":
                    img = Image.open(io.BytesIO(res.stdout)).convert("RGB")
                    w, h = img.size
                    target_w = 540
                    target_h = int(h * (target_w / w))
                    img_small = img.resize((target_w, target_h), Image.Resampling.BILINEAR)
                    buf = io.BytesIO()
                    img_small.save(buf, format="JPEG", quality=68, optimize=True)
                    data = buf.getvalue()
                    with GMMDeviceBridge._lock:
                        GMMDeviceBridge._cached_jpeg = data
                        GMMDeviceBridge._native_size = (w, h)
                        GMMDeviceBridge._rendered_size = (target_w, target_h)
                        GMMDeviceBridge._last_capture = time.time()
                time.sleep(0.06)
            except Exception:
                GMMDeviceBridge._last_serial_check = 0.0
                time.sleep(0.2)

    def _detect_best_serial(self, fallback: str) -> str:
        now = time.time()
        if GMMDeviceBridge._cached_serial and (now - GMMDeviceBridge._last_serial_check < 4.0):
            return GMMDeviceBridge._cached_serial

        try:
            res = subprocess.run(
                [self.adb, "devices"],
                capture_output=True,
                text=True,
                timeout=1.5,
                env=ADB_ENV
            )
            lines = [l.split("\t")[0] for l in res.stdout.strip().split("\n")[1:] if "\tdevice" in l]
            # Prioritize live physical Pixel 8a if online
            chosen = None
            for dev in lines:
                if "10.80.1.36" in dev or "43151JEKB10775" in dev:
                    chosen = dev
                    break
            if not chosen:
                for dev in lines:
                    if "emulator" in dev or dev.startswith("127.0.0.1:"):
                        chosen = dev
                        break
            if not chosen and fallback in lines:
                chosen = fallback
            if not chosen and lines:
                chosen = lines[0]
            if chosen:
                GMMDeviceBridge._cached_serial = chosen
                GMMDeviceBridge._last_serial_check = now
                return chosen
        except Exception:
            pass

        return fallback

    def is_connected(self) -> bool:
        try:
            res = subprocess.run(
                [self.adb, "-s", self.serial, "get-state"],
                capture_output=True,
                text=True,
                timeout=1.5,
                env=ADB_ENV
            )
            return res.stdout.strip() == "device"
        except Exception:
            return False

    def capture_screen_bytes(self) -> bytes:
        """Captures live screen bytes in JPEG format directly from in-memory cache."""
        GMMDeviceBridge._last_request_time = time.time()
        with GMMDeviceBridge._lock:
            if GMMDeviceBridge._cached_jpeg:
                return GMMDeviceBridge._cached_jpeg
        return _EMPTY_JPEG

    def send_touch(self, action: str, x: int, y: Optional[int] = None, x2: Optional[int] = None, y2: Optional[int] = None, duration_ms: int = 200) -> bool:
        """Sends tap or swipe event to Android device with automatic coordinate scaling."""
        try:
            with GMMDeviceBridge._lock:
                nw, nh = GMMDeviceBridge._native_size
                rw, rh = GMMDeviceBridge._rendered_size

            scale_x = (nw / rw) if rw else 1.0
            scale_y = (nh / rh) if rh else 1.0

            sx = int(round(x * scale_x))
            sy = int(round(y * scale_y)) if y is not None else None
            sx2 = int(round(x2 * scale_x)) if x2 is not None else None
            sy2 = int(round(y2 * scale_y)) if y2 is not None else None

            if action == "tap" and sy is not None:
                subprocess.run([self.adb, "-s", self.serial, "shell", "input", "tap", str(sx), str(sy)], check=True, timeout=1.5, env=ADB_ENV)
            elif action == "swipe" and sy is not None and sx2 is not None and sy2 is not None:
                subprocess.run([self.adb, "-s", self.serial, "shell", "input", "swipe", str(sx), str(sy), str(sx2), str(sy2), str(duration_ms)], check=True, timeout=1.5, env=ADB_ENV)
            elif action == "key":
                subprocess.run([self.adb, "-s", self.serial, "shell", "input", "keyevent", str(x)], check=True, timeout=1.5, env=ADB_ENV)
            return True
        except Exception as e:
            print(f"[!] Touch error: {e}")
            GMMDeviceBridge._last_serial_check = 0.0
            return False

    def send_text(self, text: str) -> bool:
        """Sends typed text string to Android device."""
        try:
            escaped = text.replace(" ", "%s").replace("&", "\\&").replace("<", "\\<").replace(">", "\\>").replace("\"", "\\\"").replace("'", "\\'")
            subprocess.run([self.adb, "-s", self.serial, "shell", "input", "text", escaped], check=True, timeout=1.5, env=ADB_ENV)
            return True
        except Exception as e:
            print(f"[!] Text error: {e}")
            return False

    def send_key(self, keycode: int) -> bool:
        """Sends Android keyevent by keycode."""
        return self.send_touch("key", keycode)

    def open_timeline(self) -> Dict[str, Any]:
        """
        Reliably brings Google Maps Timeline to foreground without triggering AR/Google Lens.
        """
        try:
            # Ensure Maps is in foreground
            subprocess.run([
                self.adb, "-s", self.serial, "shell", "am", "start",
                "-n", "com.google.android.apps.maps/com.google.android.maps.MapsActivity"
            ], check=True, timeout=5)
            time.sleep(0.5)
            # Tap profile avatar at top-right (505, 65)
            subprocess.run([self.adb, "-s", self.serial, "shell", "input", "tap", "505", "65"], check=True, timeout=3)
            time.sleep(0.6)
            # Tap 'Your Timeline' button at (270, 524)
            subprocess.run([self.adb, "-s", self.serial, "shell", "input", "tap", "270", "524"], check=True, timeout=3)
            return {"status": "SUCCESS"}
        except Exception as e:
            return {"status": "ERROR", "error": str(e)}

    def intent_to_day(self, date_str: str) -> Dict[str, Any]:
        """
        Navigates Google Maps on device to a specific date via instant deep link intent.
        """
        print(f"[*] Navigating device {self.serial} to date: {date_str}...")
        try:
            intent_url = f"https://www.google.com/maps/timeline/@{date_str}"
            subprocess.run([
                self.adb, "-s", self.serial, "shell", "am", "start",
                "-a", "android.intent.action.VIEW",
                "-d", intent_url,
                "com.google.android.apps.maps"
            ], check=True, timeout=5)
            return {"status": "SUCCESS", "date": date_str}
        except Exception as e:
            return {"status": "ERROR", "error": str(e)}

    def get_day_comparison(self, date_str: str, studio_db_path: str, gms_db_path: str) -> Dict[str, Any]:
        """
        Extracts segments for the given date from both Studio SQLite and GMS SQLite,
        and computes side-by-side alignment with discrepancy detection.
        """
        # 1. Studio segments
        studio_segs = []
        try:
            dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            st_epoch = int(datetime.datetime(dt.year, dt.month, dt.day, 0, 0, 0, tzinfo=datetime.timezone.utc).timestamp()) - 86400
            et_epoch = st_epoch + (86400 * 2)

            s_conn = sqlite3.connect(studio_db_path)
            s_conn.row_factory = sqlite3.Row
            sc = s_conn.cursor()
            sc.execute("""
            SELECT s.id, s.segment_type, s.activity_type, p.name as place_name, p.address as place_address, p.category,
                   s.start_time, s.end_time, s.start_ts, s.end_ts,
                   ROUND((s.end_ts - s.start_ts)/60.0, 1) as duration_minutes,
                   s.distance_meters, s.latitude, s.longitude
            FROM segments s
            LEFT JOIN places p ON s.place_id = p.place_id
            WHERE s.start_time LIKE ? OR (s.start_ts >= ? AND s.start_ts <= ?)
            ORDER BY s.start_ts ASC;
            """, (f"{date_str}%", st_epoch, et_epoch))
            studio_segs = [dict(r) for r in sc.fetchall()]
            s_conn.close()
        except Exception as e:
            print(f"[!] Studio query error: {e}")


        # 2. GMS ODLH segments
        gms_segs = []
        try:
            dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            st_epoch = int(datetime.datetime(dt.year, dt.month, dt.day, 0, 0, 0, tzinfo=datetime.timezone.utc).timestamp()) - 86400
            et_epoch = st_epoch + (86400 * 2)

            g_conn = sqlite3.connect(gms_db_path)
            g_conn.row_factory = sqlite3.Row
            gc = g_conn.cursor()
            gc.execute("""
            SELECT segment_id, segment_type, start_timestamp_seconds, end_timestamp_seconds, fprint, semantic_segment
            FROM semantic_segment_table
            WHERE start_timestamp_seconds >= ? AND start_timestamp_seconds <= ? AND segment_type IN (1, 2)
            ORDER BY start_timestamp_seconds ASC;
            """, (st_epoch, et_epoch))
            rows = gc.fetchall()
            g_conn.close()

            for r in rows:
                sid = r["segment_id"]
                stype = "visit" if r["segment_type"] == 1 else "activity"
                sts = r["start_timestamp_seconds"]
                ets = r["end_timestamp_seconds"]
                dur_m = round((ets - sts) / 60.0, 1)
                
                # Check date match in UTC
                dt_sts = datetime.datetime.fromtimestamp(sts, tz=datetime.timezone.utc)
                d_str_utc = dt_sts.strftime("%Y-%m-%d")

                gms_segs.append({
                    "segment_id": sid,
                    "segment_type": stype,
                    "start_ts": sts,
                    "end_ts": ets,
                    "start_time": dt_sts.strftime("%H:%M:%S"),
                    "end_time": datetime.datetime.fromtimestamp(ets, tz=datetime.timezone.utc).strftime("%H:%M:%S"),
                    "duration_minutes": dur_m,
                    "fprint": r["fprint"],
                    "date": d_str_utc
                })
        except Exception as e:
            print(f"[!] GMS query error: {e}")

        # 3. Compute Side-by-Side Comparison
        comparisons = []
        all_time_slots = sorted(list(set([s["start_ts"] for s in studio_segs] + [g["start_ts"] for g in gms_segs])))
        
        discrepancies = 0
        for s in studio_segs:
            # Find best overlapping GMS segment
            matched_g = None
            best_overlap = -1
            for g in gms_segs:
                overlap = min(s["end_ts"], g["end_ts"]) - max(s["start_ts"], g["start_ts"])
                if overlap > best_overlap and overlap > 0:
                    best_overlap = overlap
                    matched_g = g

            comp = {
                "start_time": s.get("start_time", "")[11:16] if len(s.get("start_time", "")) >= 16 else str(s.get("start_ts")),
                "end_time": s.get("end_time", "")[11:16] if len(s.get("end_time", "")) >= 16 else str(s.get("end_ts")),
                "studio": s,
                "gms": matched_g,
                "status": "MATCH",
                "diff_details": []
            }

            if not matched_g:
                comp["status"] = "STUDIO_ONLY"
                comp["diff_details"].append("Segment exists in Studio but missing in GMS on-device database.")
                discrepancies += 1
            else:
                if s["segment_type"] != matched_g["segment_type"]:
                    comp["status"] = "DIFF_TYPE"
                    comp["diff_details"].append(f"Type mismatch: Studio is {s['segment_type']} vs GMS is {matched_g['segment_type']}")
                    discrepancies += 1
                elif abs(s["duration_minutes"] - matched_g["duration_minutes"]) > 5.0:
                    comp["status"] = "DIFF_DURATION"
                    comp["diff_details"].append(f"Duration difference: Studio has {s['duration_minutes']}m vs GMS has {matched_g['duration_minutes']}m")
                    discrepancies += 1

            comparisons.append(comp)

        # Check for GMS segments not matched
        matched_g_ids = set([c["gms"]["segment_id"] for c in comparisons if c.get("gms")])
        for g in gms_segs:
            if g["segment_id"] not in matched_g_ids:
                comparisons.append({
                    "start_time": g["start_time"],
                    "end_time": g["end_time"],
                    "studio": None,
                    "gms": g,
                    "status": "GMM_ONLY",
                    "diff_details": ["Segment exists on GMM device but missing in Studio."],
                })
                discrepancies += 1

        return {
            "status": "SUCCESS",
            "date": date_str,
            "studio_count": len(studio_segs),
            "gms_count": len(gms_segs),
            "discrepancy_count": discrepancies,
            "comparisons": comparisons
        }


_GLOBAL_BRIDGE: Optional[GMMDeviceBridge] = None
_GLOBAL_BRIDGE_LOCK = threading.Lock()


def get_bridge() -> GMMDeviceBridge:
    global _GLOBAL_BRIDGE
    with _GLOBAL_BRIDGE_LOCK:
        if _GLOBAL_BRIDGE is None:
            _GLOBAL_BRIDGE = GMMDeviceBridge()
        return _GLOBAL_BRIDGE

