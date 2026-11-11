"""
Canonical Google Play Services (GMS) ODLH Activity Enums & Protobuf Wire Helpers.

Empirically verified against authentic Google `odlh-storage.db` (`semantic_segment_table`),
`gmm_myplaces.db` (Corpus 8), and `gmm_sync.db` (Corpus 11) binary records.
"""

from __future__ import annotations

import base64
import hashlib
import os
import sqlite3
import struct
import time
import urllib.parse
import zlib
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Authoritative GMS ODLH ActivityCandidate.activity_type enum mapping
GMS_ACTIVITY_TO_CODE: Dict[str, int] = {
    "WALKING": 2,
    "ON_FOOT": 2,
    "STILL": 2,
    "CYCLING": 3,
    "ON_BICYCLE": 3,
    "SCOOTER": 3,
    "FLYING": 5,
    "RUNNING": 6,
    "IN_BUS": 7,
    "TRANSIT": 7,
    "IN_TRAIN": 8,
    "IN_SUBWAY": 9,
    "IN_TRAM": 10,
    "IN_FERRY": 11,
    "IN_FUNICULAR": 13,
    "HIKING": 14,
    "KAYAKING": 15,
    "KITESURFING": 16,
    "SAILING": 18,
    "UNKNOWN": 20,
    "MOVING": 20,
    "SLEDDING": 22,
    "SNOWSHOEING": 25,
    "SWIMMING": 27,
    "IN_PASSENGER_VEHICLE": 29,
    "DRIVING": 29,
    "MOTORCYCLING": 29,
    "BOATING": 31,
    "IN_GONDOLA_LIFT": 34,
    "IN_TAXI": 36,
    "PARAGLIDING": 37,
}

# Canonical inverse mapping (GMS integer enum -> canonical viewer activity_type)
GMS_CODE_TO_ACTIVITY: Dict[int, str] = {
    0: "UNKNOWN",
    1: "IN_PASSENGER_VEHICLE",
    2: "WALKING",
    3: "CYCLING",
    5: "FLYING",
    6: "RUNNING",
    7: "IN_BUS",
    8: "IN_TRAIN",
    9: "IN_SUBWAY",
    10: "IN_TRAM",
    11: "IN_FERRY",
    13: "IN_FUNICULAR",
    14: "HIKING",
    15: "KAYAKING",
    16: "KITESURFING",
    18: "SAILING",
    20: "UNKNOWN",
    22: "SLEDDING",
    25: "SNOWSHOEING",
    27: "SWIMMING",
    29: "IN_PASSENGER_VEHICLE",
    31: "BOATING",
    34: "IN_GONDOLA_LIFT",
    36: "IN_TAXI",
    37: "PARAGLIDING",
}


def activity_name_to_gms_code(activity_type: Optional[str], default: int = 2) -> int:
    """Maps a viewer activity_type string to its canonical GMS ODLH integer enum."""
    if not activity_type:
        return default
    return GMS_ACTIVITY_TO_CODE.get(activity_type.strip().upper(), default)


def gms_code_to_activity_name(code: int, default: str = "UNKNOWN") -> str:
    """Maps a GMS ODLH integer enum to its canonical viewer activity_type string."""
    return GMS_CODE_TO_ACTIVITY.get(int(code), default)


def encode_varint_64(val: int) -> bytes:
    """Encodes a signed/unsigned 64-bit integer as protobuf base-128 varint."""
    if val < 0:
        val = (1 << 64) + val
    out = bytearray()
    while True:
        byte = val & 0x7F
        val >>= 7
        if val:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            break
    return bytes(out)


encode_varint = encode_varint_64


def encode_tag(field_num: int, wire_type: int) -> bytes:
    """Encodes a protobuf (field_number, wire_type) tag."""
    return encode_varint_64((field_num << 3) | wire_type)


def encode_int(field_num: int, val: int) -> bytes:
    """Encodes a varint field (wire_type = 0)."""
    return encode_tag(field_num, 0) + encode_varint_64(val)


def encode_fixed64_int(field_num: int, val: int) -> bytes:
    """Encodes a 64-bit little-endian fixed integer field (wire_type = 1)."""
    return encode_tag(field_num, 1) + struct.pack("<Q", val & 0xFFFFFFFFFFFFFFFF)


def encode_length_delimited(field_num: int, data: bytes) -> bytes:
    """Encodes a length-delimited bytes/submessage field (wire_type = 2)."""
    return encode_tag(field_num, 2) + encode_varint_64(len(data)) + data


def encode_fixed32_float(field_num: int, val: float) -> bytes:
    """Encodes a 32-bit IEEE-754 float field (wire_type = 5)."""
    return encode_tag(field_num, 5) + struct.pack("<f", float(val))


def encode_sfixed32_int(field_num: int, val: int) -> bytes:
    """Encodes a 32-bit signed fixed integer field (wire_type = 5)."""
    return encode_tag(field_num, 5) + struct.pack("<i", int(val))


def encode_lat_lng_proto(lat: float, lng: float) -> bytes:
    """Encodes PointProto (Tag 1 sfixed32 lat_e7, Tag 2 sfixed32 lng_e7)."""
    return encode_sfixed32_int(1, int(round(lat * 1e7))) + encode_sfixed32_int(
        2, int(round(lng * 1e7))
    )


def encode_waypoint_list_proto(waypoints: Iterable[Dict[str, Any]]) -> bytes:
    """Encodes WaypointListProto (repeated Tag 1 WaypointProto) for simplified_raw_path."""
    out = bytearray()
    for wp in waypoints:
        lat_e7 = int(round(float(wp["lat"]) * 1e7))
        lng_e7 = int(round(float(wp["lng"]) * 1e7))
        wp_buf = bytearray()
        wp_buf += encode_sfixed32_int(1, lat_e7)
        wp_buf += encode_sfixed32_int(2, lng_e7)
        if wp.get("ts") is not None:
            wp_buf += encode_int(3, int(wp["ts"]))
        if wp.get("accuracy") is not None:
            wp_buf += encode_fixed32_float(4, float(wp["accuracy"]))
        out += encode_length_delimited(1, bytes(wp_buf))
    return bytes(out)


def place_id_to_cell_and_fprint(
    place_id: Optional[str], lat: float, lng: float, name: str = ""
) -> Tuple[int, int, str]:
    """
    Extracts `(s2_cell_id, feature_fprint, ftid_hex)` from a 20-byte `ChIJ` Place ID,
    or deterministically synthesizes nonzero 64-bit identifiers when absent.
    """
    cid, fp = 0, 0
    if place_id and place_id.startswith("ChIJ"):
        pad = place_id + "=" * ((4 - len(place_id) % 4) % 4)
        try:
            raw = base64.urlsafe_b64decode(pad.encode("ascii"))
            if (
                len(raw) >= 20
                and raw[0] == 0x0A
                and raw[1] == 0x12
                and raw[2] == 0x09
                and raw[11] == 0x11
            ):
                cid = struct.unpack("<Q", raw[3:11])[0]
                fp = struct.unpack("<Q", raw[12:20])[0]
        except Exception:
            pass

    if cid == 0 or fp == 0:
        seed = f"{name}|{place_id or ''}|{lat:.5f}|{lng:.5f}"
        digest = hashlib.sha256(seed.encode("utf-8")).digest()
        if cid == 0:
            cid = struct.unpack("<Q", digest[:8])[0] | 1
        if fp == 0:
            fp = struct.unpack("<Q", digest[8:16])[0] | 1

    cid &= 0xFFFFFFFFFFFFFFFF
    fp &= 0xFFFFFFFFFFFFFFFF
    ftid = f"0x{cid:016x}:0x{fp:016x}"
    return cid, fp, ftid


def place_id_to_feature_id_bytes(place_id: Optional[str], lat: float, lng: float) -> bytes:
    """Encodes FeatureIdProto (`Tag 1 fixed64 fprint`, `Tag 2 fixed64 s2_cell_id`)."""
    cid, fp, _ = place_id_to_cell_and_fprint(place_id, lat, lng)
    return encode_fixed64_int(1, fp) + encode_fixed64_int(2, cid)


def get_tz_offset_minutes(lng: Optional[float], iso_str: str) -> int:
    """Extracts signed UTC offset in minutes from an ISO-8601 string or longitude fallback."""
    if iso_str and len(iso_str) >= 25 and iso_str[19] in ("+", "-"):
        try:
            sign = 1 if iso_str[19] == "+" else -1
            hh = int(iso_str[20:22])
            mm = int(iso_str[23:25])
            return sign * (hh * 60 + mm)
        except ValueError:
            pass
    if lng is not None:
        return int(round(float(lng) / 15.0) * 60)
    return 0


def generate_fprint(segment_id: str, start_ts: int, end_ts: int) -> int:
    """Generates a deterministic signed 64-bit SQLite integer fingerprint for a segment."""
    digest = hashlib.sha256(f"{segment_id}|{start_ts}|{end_ts}".encode("utf-8")).digest()
    u64 = struct.unpack("<Q", digest[:8])[0] | 1
    return u64 if u64 < (1 << 63) else u64 - (1 << 64)


def build_myplaces_proto(
    fprint: int, cell_id: int, name: str, address: str, lat: float, lng: float
) -> bytes:
    """Builds a Corpus-8 `gmm_myplaces.db` protobuf item."""
    sub1 = encode_int(1, 3) + encode_int(2, fprint)
    sub4 = encode_int(1, int(round(lat * 1e6))) + encode_int(2, int(round(lng * 1e6)))
    ftid_str = f"0x{cell_id:016x}:0x{fprint:016x}"
    q_str = urllib.parse.quote_plus(f"{name}, {address}" if address else name)
    url = f"https://maps.google.com/?q={q_str}&ftid={ftid_str}"

    now_ms = int(time.time() * 1000)
    tag6 = bytearray()
    tag6 += encode_length_delimited(1, sub1)
    tag6 += encode_length_delimited(2, (address or "").encode("utf-8"))
    tag6 += encode_length_delimited(3, ftid_str.encode("utf-8"))
    tag6 += encode_length_delimited(4, sub4)
    tag6 += encode_int(5, now_ms)
    tag6 += encode_length_delimited(7, name.encode("utf-8"))
    tag6 += encode_length_delimited(6, url.encode("utf-8"))

    payload = bytearray()
    payload += encode_length_delimited(2, f"3:{fprint}".encode("utf-8"))
    payload += encode_length_delimited(6, bytes(tag6))
    return bytes(payload)


def populate_place_caches(
    viewer_db: Optional[str] = None,
    out_dir: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Populates `gmm_myplaces_full.db` and `gmm_sync_full.db` from `places` in `viewer_db`
    so on-device Google Maps resolves all visited `ChIJ` Feature IDs offline.
    """
    root = Path(__file__).resolve().parent.parent
    v_path = Path(viewer_db or os.environ.get("TIMELINE_DB_PATH") or (root / "timeline_viewer.db"))
    target_dir = Path(out_dir) if out_dir else (root / "scratch")
    target_dir.mkdir(parents=True, exist_ok=True)

    mp_out = target_dir / "gmm_myplaces_full.db"
    sync_out = target_dir / "gmm_sync_full.db"

    conn_v = sqlite3.connect(str(v_path))
    places: List[Tuple[Any, ...]] = conn_v.execute(
        "SELECT place_id, name, COALESCE(address, ''), COALESCE(latitude, 0.0), COALESCE(longitude, 0.0) "
        "FROM places WHERE name IS NOT NULL AND name != '';"
    ).fetchall()
    conn_v.close()

    now_ms = int(time.time() * 1000)

    conn_mp = sqlite3.connect(str(mp_out))
    conn_mp.execute(
        "CREATE TABLE IF NOT EXISTS sync_item ("
        "corpus INTEGER, key_string TEXT, timestamp INTEGER, merge_key TEXT, "
        "local_modified INTEGER, item BLOB, latitude INTEGER, longitude INTEGER, "
        "is_syncing INTEGER, PRIMARY KEY(corpus, key_string));"
    )
    mp_rows: List[Tuple[Any, ...]] = []
    sync_rows: List[Tuple[Any, ...]] = []

    for pid, name, addr, lat, lng in places:
        cid, fp, _ = place_id_to_cell_and_fprint(pid, float(lat), float(lng), str(name))
        proto = build_myplaces_proto(fp, cid, str(name), str(addr), float(lat), float(lng))
        lat_e6 = int(round(float(lat) * 1e6))
        lng_e6 = int(round(float(lng) * 1e6))
        key_u = f"3:{fp}"
        mp_rows.append((8, key_u, now_ms, key_u, 0, zlib.compress(proto), lat_e6, lng_e6, 0))
        sync_rows.append((11, key_u, now_ms, proto))

    conn_mp.executemany(
        "INSERT OR REPLACE INTO sync_item VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
        mp_rows,
    )
    conn_mp.commit()
    conn_mp.close()

    conn_sync = sqlite3.connect(str(sync_out))
    conn_sync.execute(
        "CREATE TABLE IF NOT EXISTS sync_data ("
        "corpus INTEGER, client_id TEXT, timestamp INTEGER, data BLOB, "
        "PRIMARY KEY(corpus, client_id));"
    )
    conn_sync.executemany(
        "INSERT OR REPLACE INTO sync_data VALUES (?, ?, ?, ?);",
        sync_rows,
    )
    conn_sync.commit()
    conn_sync.close()

    return str(mp_out), str(sync_out)
