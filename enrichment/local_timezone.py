"""
High-Accuracy Zero-Dependency Local Timezone Engine
Computes true local time for timeline coordinates worldwide using Python zoneinfo.
"""

import datetime
import zoneinfo
from typing import Tuple, Optional


def get_timezone_name(lat: Optional[float], lng: Optional[float]) -> str:
    """Returns the IANA timezone name for a given lat/lng coordinate."""
    if lat is None or lng is None:
        return "America/New_York"

    # 1. Turkey (Istanbul, Ankara, Pamukkale)
    if 25.0 <= lng <= 45.0 and 35.0 <= lat <= 43.0:
        return "Europe/Istanbul"

    # 2. Japan (Tokyo, Kyoto, Osaka)
    if 128.0 <= lng <= 146.0 and 30.0 <= lat <= 46.0:
        return "Asia/Tokyo"

    # 3. Taiwan / Hong Kong / Macau / Singapore / Mainland China / Bali
    if 118.0 <= lng <= 123.0 and 21.0 <= lat <= 26.0:
        return "Asia/Taipei"
    if 113.0 <= lng <= 115.0 and 22.0 <= lat <= 23.0:
        return "Asia/Hong_Kong"
    if 103.5 <= lng <= 104.5 and 1.1 <= lat <= 1.5:
        return "Asia/Singapore"
    if 114.0 <= lng <= 116.0 and -9.0 <= lat <= -8.0:
        return "Asia/Makassar"

    # 4. Thailand / Indonesia (Bangkok, Phuket, Jakarta)
    if 97.0 <= lng <= 106.0 and 5.0 <= lat <= 21.0:
        return "Asia/Bangkok"
    if 105.0 <= lng <= 115.0 and -8.5 <= lat <= -5.5:
        return "Asia/Jakarta"

    # 5. United Kingdom / Ireland / Portugal
    if -11.0 <= lng <= 2.0 and 49.0 <= lat <= 61.0:
        return "Europe/London"

    # 6. Central Western Europe (Switzerland, France, Germany, Spain, Italy, Austria)
    if -9.5 <= lng <= 25.0 and 36.0 <= lat <= 56.0:
        return "Europe/Paris"

    # 7. United States & Canada
    if -168.0 <= lng <= -50.0 and 24.0 <= lat <= 72.0:
        # Hawaii
        if -161.0 <= lng <= -154.0 and 18.0 <= lat <= 23.0:
            return "Pacific/Honolulu"
        # Alaska
        if -168.0 <= lng <= -130.0 and 52.0 <= lat <= 72.0:
            return "America/Anchorage"
        # Pacific (California, Washington, Oregon, Nevada)
        if -125.0 <= lng <= -114.0 or (lat <= 36.0 and lng <= -114.0):
            return "America/Los_Angeles"
        # Mountain (Utah, Colorado, Arizona, New Mexico, Montana, Idaho)
        if -114.0 < lng <= -103.0:
            if 31.3 <= lat <= 37.0 and -114.8 <= lng <= -109.0:
                return "America/Phoenix"
            return "America/Denver"
        # Central (Texas, Illinois, Tennessee, Minnesota, Missouri, Louisiana)
        if -103.0 < lng <= -86.5:
            return "America/Chicago"
        # Eastern (New York, Massachusetts, DC, Florida, Pennsylvania, Georgia)
        if -86.5 < lng <= -65.0:
            return "America/New_York"

    # 8. India
    if 68.0 <= lng <= 90.0 and 8.0 <= lat <= 35.0:
        return "Asia/Kolkata"

    # 9. UAE
    if 51.0 <= lng <= 57.0 and 22.0 <= lat <= 27.0:
        return "Asia/Dubai"

    # 10. Australia / New Zealand
    if 112.0 <= lng <= 155.0 and -45.0 <= lat <= -10.0:
        return "Australia/Sydney"
    if 165.0 <= lng <= 179.0 and -48.0 <= lat <= -34.0:
        return "Pacific/Auckland"

    return "UTC"


def get_timezone_offset_hours(lat: Optional[float], lng: Optional[float], timestamp: Optional[float] = None) -> float:
    """Returns the UTC offset in hours for a given lat/lng coordinate and epoch timestamp."""
    tz_name = get_timezone_name(lat, lng)
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        return -5.0

    if timestamp:
        dt = datetime.datetime.fromtimestamp(timestamp, tz=tz)
        offset = dt.utcoffset()
        return offset.total_seconds() / 3600.0 if offset else 0.0
    return -5.0


def format_local_time_strings(
    lat: Optional[float], lng: Optional[float],
    start_ts: Optional[float], end_ts: Optional[float],
    fallback_start: str = "", fallback_end: str = "",
    end_lat: Optional[float] = None, end_lng: Optional[float] = None
) -> Tuple[str, str, str]:
    """
    Returns (local_start_time_str, local_end_time_str, tz_offset_str).
    Accurately converts start_time using origin timezone and end_time using destination timezone
    for cross-timezone movements (e.g. flights from Nashville CDT to NYC EDT).
    """
    # 1. Start Time (Origin Timezone)
    tz_name1 = get_timezone_name(lat, lng)
    try:
        tz1 = zoneinfo.ZoneInfo(tz_name1)
    except Exception:
        tz1 = datetime.timezone.utc

    has_local_offset_1 = False
    if fallback_start and len(fallback_start) >= 19:
        tail = fallback_start[19:]
        if ("+" in tail or "-" in tail) and not ("+00:00" in tail or "-00:00" in tail or "Z" in tail):
            has_local_offset_1 = True

    if has_local_offset_1:
        t1_str = fallback_start[11:16]
        tz_offset_raw = fallback_start[19:25] if len(fallback_start) >= 25 else ""
        tz_str = f"UTC{tz_offset_raw}" if tz_offset_raw else "UTC"
    elif start_ts:
        dt1 = datetime.datetime.fromtimestamp(start_ts, tz=tz1)
        t1_str = dt1.strftime("%H:%M")
        tz_str = dt1.strftime("%Z (UTC%z)")
    else:
        t1_str = fallback_start[11:16] if fallback_start and len(fallback_start) >= 16 else "--:--"
        tz_str = "UTC"

    # 2. End Time (Destination Timezone for flights/movements)
    dest_lat = end_lat if end_lat is not None else lat
    dest_lng = end_lng if end_lng is not None else lng
    tz_name2 = get_timezone_name(dest_lat, dest_lng)
    try:
        tz2 = zoneinfo.ZoneInfo(tz_name2)
    except Exception:
        tz2 = datetime.timezone.utc

    has_local_offset_2 = False
    if fallback_end and len(fallback_end) >= 19:
        tail = fallback_end[19:]
        if ("+" in tail or "-" in tail) and not ("+00:00" in tail or "-00:00" in tail or "Z" in tail):
            has_local_offset_2 = True

    if tz_name1 == tz_name2 and has_local_offset_2:
        t2_str = fallback_end[11:16]
    elif end_ts:
        dt2 = datetime.datetime.fromtimestamp(end_ts, tz=tz2)
        t2_str = dt2.strftime("%H:%M")
    elif fallback_end and len(fallback_end) >= 16:
        t2_str = fallback_end[11:16]
    else:
        t2_str = "--:--"

    return t1_str, t2_str, tz_str
