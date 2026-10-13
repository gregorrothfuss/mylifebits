"""
Device Backup Places Indexer.

Extracts authentic user-saved, starred, and labeled places directly from Google Maps
device sync databases (scratch/device_sync_pulled.db, gmm_sync.db, and Pixel 8 backups).
Decodes the 20-byte (cell_id, feature_id) protobuf wire format into canonical ChIJ... Place IDs.
Provides zero-hardcode ground truth resolution.
"""

import sqlite3
import base64
import struct
import os
from typing import Dict, Any, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_CANDIDATES = [
    os.path.join(WORKSPACE_DIR, "scratch", "device_sync_pulled.db"),
    os.path.join(WORKSPACE_DIR, "gmm_device_databases", "gmm_sync.db"),
    os.path.join(
        WORKSPACE_DIR, "scratch", "pixel8_backup_20260908",
        "data", "data", "com.google.android.apps.maps", "databases", "gmm_sync.db"
    ),
]

_CACHE: Optional[Dict[str, Dict[str, Any]]] = None

def _extract_proper(b: bytes) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Parses Google Maps Mobile sync_item_data protobuf.
    Parent message field 3 = POI display name.
    Sub-message field 3 = formatted address.
    Sub-message field 6 = cell_id:feature_id hex string.
    """
    name = None
    address = None
    hex_id = None
    i = 0
    while i < len(b):
        tag = b[i]
        wire = tag & 0x07
        field = tag >> 3
        i += 1
        if wire == 2:
            length, shift = 0, 0
            while i < len(b):
                byte = b[i]
                i += 1
                length |= (byte & 0x7f) << shift
                if not (byte & 0x80):
                    break
                shift += 7
            val = b[i:i + length]
            i += length
            if field == 3:
                try:
                    s = val.decode('utf-8')
                    if len(s) > 1 and not s.startswith('0x'):
                        name = s
                except UnicodeDecodeError:
                    pass
            # check sub-message for hex_id and address
            j = 0
            while j < len(val):
                try:
                    sub_tag = val[j]
                    sub_wire = sub_tag & 0x07
                    sub_field = sub_tag >> 3
                    j += 1
                    if sub_wire == 2:
                        sub_len, sub_shift = 0, 0
                        while j < len(val):
                            sub_byte = val[j]
                            j += 1
                            sub_len |= (sub_byte & 0x7f) << sub_shift
                            if not (sub_byte & 0x80):
                                break
                            sub_shift += 7
                        sub_val = val[j:j + sub_len]
                        j += sub_len
                        if sub_field == 6:
                            try:
                                s = sub_val.decode('utf-8')
                                if s.startswith('0x') and ':' in s:
                                    hex_id = s
                            except UnicodeDecodeError:
                                pass
                        elif sub_field == 3:
                            try:
                                s = sub_val.decode('utf-8')
                                if ',' in s:
                                    address = s
                            except UnicodeDecodeError:
                                pass
                    elif sub_wire == 0:
                        while j < len(val) and (val[j] & 0x80):
                            j += 1
                        j += 1
                    elif sub_wire == 1:
                        j += 8
                    elif sub_wire == 5:
                        j += 4
                    else:
                        break
                except Exception:
                    break
        elif wire == 0:
            while i < len(b) and (b[i] & 0x80):
                i += 1
            i += 1
        elif wire == 1:
            i += 8
        elif wire == 5:
            i += 4
        else:
            break
    return name, address, hex_id


def _to_place_id(hex_str: str) -> Optional[str]:
    try:
        parts = hex_str.split(':')
        c_id = int(parts[0], 16)
        f_id = int(parts[1], 16)
        b = struct.pack('<BBBQBQ', 0x0a, 0x12, 0x09, c_id, 0x11, f_id)
        return base64.urlsafe_b64encode(b).decode('ascii').rstrip('=')
    except Exception:
        return None


def get_device_backup_places() -> Dict[str, Dict[str, Any]]:
    """Loads all authentic places from device backup SQLite databases."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    places: Dict[str, Dict[str, Any]] = {}

    for db_path in DB_CANDIDATES:
        if not os.path.exists(db_path):
            continue
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("""
                SELECT feature_fprint, latitude_e6, longitude_e6, item_proto
                FROM sync_item_data
                WHERE corpus IN (11, 14) AND item_proto IS NOT NULL;
            """)
            for fid, lat_e6, lng_e6, blob in cur.fetchall():
                name, address, hex_id = _extract_proper(blob)
                if not name or not hex_id:
                    continue
                pid = _to_place_id(hex_id)
                if not pid or pid in places:
                    continue

                lat = (lat_e6 / 1e6) if lat_e6 else None
                lng = (lng_e6 / 1e6) if lng_e6 else None

                places[pid] = {
                    "place_id": pid,
                    "name": name,
                    "address": address,
                    "latitude": lat,
                    "longitude": lng,
                    "feature_fprint": fid,
                    "source": "DEVICE_BACKUP_GMM_SYNC"
                }
            conn.close()
        except Exception:
            pass

    _CACHE = places
    return _CACHE


def lookup_backup_place(place_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Look up a place by Place ID from authentic device backups."""
    if not place_id:
        return None
    catalog = get_device_backup_places()
    return catalog.get(place_id)
