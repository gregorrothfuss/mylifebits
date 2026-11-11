"""
Google Maps URL and Deep Link Resolver.
Resolves maps.app.goo.gl and goo.gl links, extracts canonical place IDs, coordinates, and metadata.
"""

from __future__ import annotations

import base64
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import struct
import urllib.parse
import urllib.request
from typing import Any, Dict, Tuple

_SSL_CTX = ssl.create_default_context()
_ALLOWED_SHORTENER_HOSTS: Tuple[str, ...] = (
    "goo.gl",
    "maps.app.goo.gl",
    "google.com",
    "maps.google.com",
)
_MAX_GEOCODE_BYTES = 1_048_576


def is_safe_public_url(url: str, allowed_suffixes: Tuple[str, ...]) -> bool:
    """Validates scheme, hostname allowlist, and non-private DNS resolution to prevent SSRF."""
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("https", "http"):
            return False
        host = (parsed.hostname or "").lower().rstrip(".")
        if not host:
            return False
        if not any(host == s or host.endswith("." + s) for s in allowed_suffixes):
            return False

        # Reject literal private/loopback/link-local IP addresses immediately
        try:
            ip_obj = ipaddress.ip_address(host)
            if (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_link_local
                or ip_obj.is_multicast
                or ip_obj.is_reserved
                or ip_obj.is_unspecified
            ):
                return False
        except ValueError:
            # Hostname: resolve and verify every returned IP is globally routable
            try:
                infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
                for info in infos:
                    addr_str = str(info[4][0])
                    resolved_ip = ipaddress.ip_address(addr_str)
                    if (
                        resolved_ip.is_private
                        or resolved_ip.is_loopback
                        or resolved_ip.is_link_local
                        or resolved_ip.is_multicast
                        or resolved_ip.is_reserved
                        or resolved_ip.is_unspecified
                    ):
                        return False
            except socket.gaierror:
                # Offline environment: allow syntactic allowlisted domain, network open will fail cleanly
                pass
        return True
    except Exception:
        return False


def resolve_google_maps_url(input_str: str) -> Dict[str, Any]:
    """
    Resolves Google Maps deep links (maps.app.goo.gl, goo.gl/maps, google.com/maps),
    extracting authentic ChIJ Place ID, lat/lng coordinates, business name, address, and category.
    """
    url = input_str.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    if not is_safe_public_url(url, _ALLOWED_SHORTENER_HOSTS):
        raise ValueError("URL host must be an official Google Maps domain")

    parsed = urllib.parse.urlparse(url)
    target_url = url
    host = (parsed.hostname or "").lower()
    if host in ("goo.gl", "maps.app.goo.gl") or host.endswith(".goo.gl"):
        try:
            conn = http.client.HTTPSConnection(host, context=_SSL_CTX, timeout=8)
            try:
                path_q = (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
                ua = os.environ.get("HTTP_USER_AGENT", "MyLifeBits/1.0")
                conn.request("GET", path_q, headers={"User-Agent": ua})
                resp = conn.getresponse()
                loc = resp.getheader("Location")
                if loc and is_safe_public_url(loc, _ALLOWED_SHORTENER_HOSTS):
                    target_url = loc
            finally:
                conn.close()
        except Exception:
            pass

    res: Dict[str, Any] = {
        "original_url": input_str,
        "final_url": target_url,
        "place_id": None,
        "name": None,
        "address": None,
        "latitude": None,
        "longitude": None,
        "category": "Other / POI",
        "city": None,
        "country": None,
    }

    # 1. Search for hex cell & fprint in target_url (e.g. 0x89c259b24ada254b:0x15a6b95e5bfd1a39)
    m_hex = re.search(r"0x([0-9a-fA-F]{10,16})[:%3A]+0x([0-9a-fA-F]{10,16})", target_url)
    if m_hex:
        try:
            cid = int(m_hex.group(1), 16)
            fp = int(m_hex.group(2), 16)
            p_cid = struct.pack("<Q", cid)
            p_fp = struct.pack("<Q", fp)
            proto = b"\x0a\x12\x09" + p_cid + b"\x11" + p_fp
            res["place_id"] = base64.urlsafe_b64encode(proto).decode("ascii").rstrip("=")
        except Exception:
            pass

    # 2. Extract Lat & Lng
    m_ll = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", target_url)
    if not m_ll:
        m_ll = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", target_url)
    if m_ll:
        res["latitude"] = float(m_ll.group(1))
        res["longitude"] = float(m_ll.group(2))

    # 3. Extract Name
    if "/maps/place/" in target_url:
        m_pname = re.search(r"/maps/place/([^/@?]+)", target_url)
        if m_pname:
            res["name"] = urllib.parse.unquote_plus(m_pname.group(1))

    # 4. Reverse geocode address if lat/lng available
    if res["latitude"] is not None and res["longitude"] is not None:
        try:
            lat_f = float(res["latitude"])
            lng_f = float(res["longitude"])
            r_url = (
                f"https://nominatim.openstreetmap.org/reverse?"
                f"format=jsonv2&lat={lat_f:.6f}&lon={lng_f:.6f}&zoom=18&addressdetails=1"
            )
            if is_safe_public_url(r_url, ("openstreetmap.org",)):
                ua = os.environ.get("HTTP_USER_AGENT", "MyLifeBits/1.0")
                r_req = urllib.request.Request(r_url, headers={"User-Agent": ua, "Accept": "application/json"})
                with urllib.request.urlopen(r_req, context=_SSL_CTX, timeout=4) as r_resp:
                    raw_bytes = r_resp.read(_MAX_GEOCODE_BYTES + 1)
                    if len(raw_bytes) <= _MAX_GEOCODE_BYTES:
                        r_data = json.loads(raw_bytes.decode("utf-8"))
                        res["address"] = r_data.get("display_name")
                        addr_dict = r_data.get("address", {})
                        city = (
                            addr_dict.get("city")
                            or addr_dict.get("town")
                            or addr_dict.get("village")
                            or addr_dict.get("borough")
                        )
                        if city:
                            res["city"] = city
                        country = addr_dict.get("country")
                        if country:
                            res["country"] = country
        except Exception:
            pass

    # Category inference
    if res["name"]:
        n_low = str(res["name"]).lower()
        if any(w in n_low for w in ("cafe", "coffee", "bar", "grill", "bistro", "restaurant", "pizza", "deli", "bakery", "tacos", "pub")):
            res["category"] = "Food & Drink"
        elif any(w in n_low for w in ("hotel", "motel", "resort", "inn")):
            res["category"] = "Hotels & Lodging"
        elif any(w in n_low for w in ("store", "shop", "market", "boutique", "grocer")):
            res["category"] = "Shopping & Retail"
        elif any(w in n_low for w in ("park", "garden", "beach", "trail", "museum", "theater", "theatre", "cinema", "gallery")):
            res["category"] = "Arts & Entertainment"

    return res
