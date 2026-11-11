"""Shared constants and deterministic hashing/parsing helpers for layered timeline passes."""

from __future__ import annotations

import datetime
import hashlib
from typing import Optional, Tuple

ENGINE_VERSION = "2.0.0"

SYNTHETIC_GUESS_SOURCES = {
    "SYNTHETIC_LIFE",
    "SYNTHETIC_GAP_HEAL",
}


def compute_source_key(
    source_stream: str,
    segment_type: str,
    start_ts: float,
    end_ts: float,
    identifier: Optional[str] = None,
) -> str:
    """Computes a deterministic 24-char SHA-256 key for an upstream observation."""
    ident = (identifier or "").strip()
    payload = f"{source_stream}|{segment_type}|{int(round(start_ts))}|{int(round(end_ts))}|{ident}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def compute_decision_key(
    action: str,
    date_str: str,
    start_ts: Optional[float],
    end_ts: Optional[float],
    target_place_id: Optional[str] = None,
) -> str:
    """Computes a stable key for a proposal or user review decision across engine versions."""
    st_bucket = int(round((start_ts or 0.0) / 300.0))
    et_bucket = int(round((end_ts or 0.0) / 300.0))
    pid = (target_place_id or "").strip()
    raw = f"{action}|{date_str}|{st_bucket}|{et_bucket}|{pid}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def parse_iso_to_ts(iso_str: Optional[str]) -> Optional[float]:
    """Parses ISO-8601 timestamp string into UTC epoch seconds."""
    if not iso_str:
        return None
    try:
        clean = iso_str.replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(clean).timestamp()
    except Exception:
        return None


def parse_latlng_str(s: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    """Parses Pixel '37.7749°, -122.4194°' string into (lat, lng) floats."""
    if not s:
        return None, None
    try:
        parts = s.replace("°", "").split(",")
        return float(parts[0].strip()), float(parts[1].strip())
    except Exception:
        return None, None
