"""
photo_corpus.py
High-performance photo ingestion and indexing engine for Google Photos Takeout and local media.
- Streams directly from Google Takeout ZIP files (zero disk extraction) or loose directory trees.
- Parses Google Photos companion JSON sidecars (.json, .supplemental-metadata.json, truncated names).
- Extracts EXIF timestamps, GPS coordinates, and camera metadata with Pillow.
- Generates 640px compressed WebP previews (~20-25KB) in previews directory.
- Matches photos spatially and temporally to visited timeline places and segments.
- Inserts indexed photos into the SQLite `photos` table for immediate display in the timeline viewer.
"""

from __future__ import annotations

import datetime
import glob
import hashlib
import io
import json
import math
import os
import re
import sqlite3
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from PIL import Image, ImageOps
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".heic", ".png", ".tiff", ".webp",
    ".cr2", ".nef", ".arw", ".dng", ".bmp", ".gif"
}

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv"}

MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS


def _parse_dms_coordinate(dms: Any, ref: Optional[str]) -> Optional[float]:
    """Converts EXIF degrees/minutes/seconds coordinate to decimal degrees."""
    if not dms or len(dms) < 3:
        return None
    try:
        deg = float(dms[0])
        minute = float(dms[1])
        sec = float(dms[2])
        coord = deg + (minute / 60.0) + (sec / 3600.0)
        if ref in ("S", "W"):
            coord = -coord
        return round(coord, 7)
    except Exception:
        return None


class PhotoCorpusEngine:
    """
    Ingests and indexes photos from Google Photos Takeout archives and loose directories.
    """

    def __init__(
        self,
        db_conn: sqlite3.Connection,
        previews_dir: Optional[str] = None,
    ) -> None:
        self.conn = db_conn
        self.conn.row_factory = sqlite3.Row

        env_prev = os.environ.get("PREVIEWS_DIR")
        if previews_dir:
            self.previews_dir = Path(previews_dir)
        elif env_prev:
            self.previews_dir = Path(env_prev)
        else:
            self.previews_dir = Path("data/previews")

        self.previews_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_photos_table()
        self._places_cache: Optional[List[Dict[str, Any]]] = None

    def _ensure_photos_table(self) -> None:
        c = self.conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS photos (
            sha256 TEXT PRIMARY KEY,
            filename TEXT,
            preview_path TEXT,
            timestamp_utc INTEGER,
            timezone_offset TEXT,
            local_date TEXT,
            latitude REAL,
            longitude REAL,
            place_id TEXT,
            place_name TEXT,
            address TEXT,
            city TEXT,
            country TEXT,
            people TEXT,
            face_count INTEGER DEFAULT 0,
            is_partner INTEGER DEFAULT 0
        );
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_photos_local_date ON photos(local_date);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_photos_timestamp_utc ON photos(timestamp_utc);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_photos_place_id ON photos(place_id);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_photos_coords ON photos(latitude, longitude);")
        self.conn.commit()

    def _load_places_cache(self) -> List[Dict[str, Any]]:
        if self._places_cache is None:
            c = self.conn.cursor()
            c.execute("""
            SELECT place_id, name, address, city, country, latitude, longitude
            FROM places
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL;
            """)
            self._places_cache = [dict(r) for r in c.fetchall()]
        return self._places_cache

    def match_place(
        self,
        lat: Optional[float],
        lng: Optional[float],
        ts_utc: Optional[int],
    ) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]:
        """
        Matches photo location and timestamp to known places in the catalog.
        Returns: (place_id, place_name, address, city, country)
        """
        # 1. Temporal match against timeline segments if timestamp exists
        if ts_utc:
            c = self.conn.cursor()
            c.execute("""
            SELECT place_id, place_name, place_address, city
            FROM segments
            WHERE segment_type = 'visit' AND start_ts <= ? AND end_ts >= ?
            LIMIT 1;
            """, (ts_utc + 300, ts_utc - 300))
            row = c.fetchone()
            if row and row["place_id"]:
                return (
                    row["place_id"],
                    row["place_name"],
                    row["place_address"],
                    row["city"],
                    None,
                )

        # 2. Spatial match against places catalog (within 120 meters)
        if lat is not None and lng is not None and (lat != 0.0 or lng != 0.0):
            places = self._load_places_cache()
            best_dist = 0.12  # 120m threshold
            best_place: Optional[Dict[str, Any]] = None

            for p in places:
                p_lat, p_lng = p["latitude"], p["longitude"]
                dlat = abs(p_lat - lat)
                dlng = abs(p_lng - lng)
                if dlat < 0.002 and dlng < 0.002:
                    # Rough distance in km
                    dist = math.sqrt((dlat * 111.0) ** 2 + (dlng * 85.0) ** 2)
                    if dist < best_dist:
                        best_dist = dist
                        best_place = p

            if best_place:
                return (
                    best_place["place_id"],
                    best_place["name"],
                    best_place["address"],
                    best_place["city"],
                    best_place["country"],
                )

        return None, None, None, None, None

    def extract_sidecar_metadata(self, meta: Dict[str, Any]) -> Dict[str, Any]:
        """Extracts timestamp, geo, people, and origin from Google Photos JSON sidecar."""
        out: Dict[str, Any] = {
            "timestamp_utc": None,
            "latitude": None,
            "longitude": None,
            "people": [],
            "url": meta.get("url"),
            "description": meta.get("description"),
            "is_partner": 0,
        }

        # Time
        time_info = meta.get("photoTakenTime") or meta.get("creationTime") or {}
        raw_ts = time_info.get("timestamp")
        if raw_ts:
            try:
                out["timestamp_utc"] = int(raw_ts)
            except (ValueError, TypeError):
                pass

        # GPS Geo Data
        geo = meta.get("geoData") or meta.get("geoDataExif") or {}
        lat = geo.get("latitude")
        lng = geo.get("longitude")
        if lat is not None and lng is not None and (lat != 0.0 or lng != 0.0):
            out["latitude"] = float(lat)
            out["longitude"] = float(lng)

        # People
        people_raw = meta.get("people", [])
        if isinstance(people_raw, list):
            out["people"] = [p.get("name") for p in people_raw if isinstance(p, dict) and p.get("name")]

        # Partner sharing or album origin
        origin = meta.get("googlePhotosOrigin", {})
        if "fromPartnerSharing" in origin or "fromSharedAlbum" in origin:
            out["is_partner"] = 1

        return out

    def extract_exif_metadata(self, img_bytes: bytes) -> Dict[str, Any]:
        """Extracts EXIF DateTimeOriginal and GPS coordinates using Pillow."""
        out: Dict[str, Any] = {
            "timestamp_utc": None,
            "latitude": None,
            "longitude": None,
        }
        if not HAS_PIL:
            return out

        try:
            with Image.open(io.BytesIO(img_bytes)) as img:
                exif = img.getexif()
                if not exif:
                    return out

                # EXIF 2.0 sub-IFD
                exif_sub = exif.get_ifd(0x8769) if hasattr(exif, "get_ifd") else {}
                dt_str = exif_sub.get(36867) or exif.get(306)  # DateTimeOriginal or DateTime
                if dt_str and isinstance(dt_str, str):
                    try:
                        clean_dt = dt_str.strip().replace(":", "-", 2)
                        dt = datetime.datetime.fromisoformat(clean_dt)
                        out["timestamp_utc"] = int(dt.timestamp())
                    except Exception:
                        pass

                # GPS IFD (0x8825)
                gps_info = exif.get_ifd(0x8825) if hasattr(exif, "get_ifd") else {}
                if gps_info:
                    lat_dms = gps_info.get(2)
                    lat_ref = gps_info.get(1)
                    lng_dms = gps_info.get(4)
                    lng_ref = gps_info.get(3)
                    lat = _parse_dms_coordinate(lat_dms, lat_ref)
                    lng = _parse_dms_coordinate(lng_dms, lng_ref)
                    if lat is not None and lng is not None:
                        out["latitude"] = lat
                        out["longitude"] = lng
        except Exception:
            pass

        return out

    def generate_preview(self, img_bytes: bytes, sha256: str) -> Optional[str]:
        """Generates a max 640px WebP preview (~20KB) and returns its relative path."""
        if not HAS_PIL:
            return None

        preview_name = f"{sha256}.webp"
        preview_path = self.previews_dir / preview_name
        if preview_path.exists():
            return str(preview_path)

        try:
            with Image.open(io.BytesIO(img_bytes)) as img:
                img_trans = ImageOps.exif_transpose(img)
                img_trans.thumbnail((640, 640), Image.Resampling.LANCZOS)
                if img_trans.mode in ("RGBA", "P"):
                    img_trans = img_trans.convert("RGB")
                img_trans.save(preview_path, format="WEBP", quality=55, method=4)
                return str(preview_path)
        except Exception:
            return None

    def ingest_photo(
        self,
        filename: str,
        img_bytes: bytes,
        sidecar_dict: Optional[Dict[str, Any]] = None,
        generate_preview: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Ingests a single photo with its binary payload and optional metadata sidecar."""
        sha256 = hashlib.sha256(img_bytes).hexdigest()

        # Check existing
        c = self.conn.cursor()
        c.execute("SELECT sha256, preview_path FROM photos WHERE sha256 = ?", (sha256,))
        existing = c.fetchone()
        if existing:
            return dict(existing)

        meta: Dict[str, Any] = {
            "timestamp_utc": None,
            "latitude": None,
            "longitude": None,
            "people": [],
            "is_partner": 0,
        }

        # 1. Takeout JSON sidecar
        if sidecar_dict:
            sidecar_meta = self.extract_sidecar_metadata(sidecar_dict)
            meta.update({k: v for k, v in sidecar_meta.items() if v is not None})

        # 2. EXIF fallback
        if meta["timestamp_utc"] is None or meta["latitude"] is None:
            exif_meta = self.extract_exif_metadata(img_bytes)
            if meta["timestamp_utc"] is None and exif_meta.get("timestamp_utc"):
                meta["timestamp_utc"] = exif_meta["timestamp_utc"]
            if meta["latitude"] is None and exif_meta.get("latitude"):
                meta["latitude"] = exif_meta["latitude"]
                meta["longitude"] = exif_meta["longitude"]

        # 3. Filename timestamp inference fallback
        if meta["timestamp_utc"] is None:
            m = re.search(r'(?:PXL|IMG|VID|Screenshot)[-_](\d{4})(\d{2})(\d{2})[-_](\d{2})(\d{2})(\d{2})', filename, re.I)
            if m:
                try:
                    y, mo, d, h, mi, s = map(int, m.groups())
                    dt = datetime.datetime(y, mo, d, h, mi, s, tzinfo=datetime.timezone.utc)
                    meta["timestamp_utc"] = int(dt.timestamp())
                except Exception:
                    pass

        # Calculate local_date
        local_date = None
        if meta["timestamp_utc"]:
            dt_utc = datetime.datetime.fromtimestamp(meta["timestamp_utc"], tz=datetime.timezone.utc)
            local_date = dt_utc.strftime("%Y-%m-%d")

        # Generate preview
        preview_path_str = None
        if generate_preview:
            preview_path_str = self.generate_preview(img_bytes, sha256)

        # Match place
        p_id, p_name, addr, city, country = self.match_place(
            meta.get("latitude"),
            meta.get("longitude"),
            meta.get("timestamp_utc"),
        )

        people_list = meta.get("people", [])
        people_json = json.dumps(people_list) if people_list else None
        face_count = len(people_list)

        c.execute("""
        INSERT INTO photos (
            sha256, filename, preview_path, timestamp_utc, timezone_offset,
            local_date, latitude, longitude, place_id, place_name, address, city, country,
            people, face_count, is_partner
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(sha256) DO UPDATE SET
            preview_path = COALESCE(excluded.preview_path, photos.preview_path),
            place_id = COALESCE(excluded.place_id, photos.place_id),
            place_name = COALESCE(excluded.place_name, photos.place_name);
        """, (
            sha256,
            filename,
            preview_path_str,
            meta.get("timestamp_utc"),
            None,
            local_date,
            meta.get("latitude"),
            meta.get("longitude"),
            p_id,
            p_name,
            addr,
            city,
            country,
            people_json,
            face_count,
            meta.get("is_partner", 0),
        ))

        return {
            "sha256": sha256,
            "filename": filename,
            "local_date": local_date,
            "place_name": p_name,
            "preview_path": preview_path_str,
        }

    def ingest_zip(
        self,
        zip_path: str,
        limit: Optional[int] = None,
        generate_previews: bool = True,
    ) -> Dict[str, Any]:
        """
        Streams photos and matching sidecars directly from a Google Photos Takeout ZIP archive.
        """
        zip_path = os.path.expanduser(zip_path)
        print(f"[*] Scanning Photos Takeout archive: {zip_path}...")
        results = {"total_found": 0, "ingested": 0, "skipped": 0}

        with zipfile.ZipFile(zip_path, "r") as zf:
            namelist = zf.namelist()
            file_set = set(namelist)

            media_paths = [
                p for p in namelist
                if os.path.splitext(p)[1].lower() in IMAGE_EXTENSIONS
                and not p.startswith("__MACOSX/")
            ]

            results["total_found"] = len(media_paths)
            print(f"    Found {len(media_paths)} photos in archive.")

            if limit:
                media_paths = media_paths[:limit]

            for internal_path in media_paths:
                filename = os.path.basename(internal_path)
                try:
                    with zf.open(internal_path) as f:
                        img_bytes = f.read()
                except Exception:
                    results["skipped"] += 1
                    continue

                # Locate sidecar candidate
                base_no_ext, ext = os.path.splitext(internal_path)
                clean_path = re.sub(r"-edited", "", internal_path)
                clean_path = re.sub(r"\s*\(\d+\)", "", clean_path)
                clean_base_no_ext, _ = os.path.splitext(clean_path)

                candidates = [
                    internal_path + ".supplemental-metadata.json",
                    internal_path + ".json",
                    base_no_ext + ".json",
                    clean_path + ".supplemental-metadata.json",
                    clean_path + ".json",
                    clean_base_no_ext + ".json",
                ]

                sidecar_dict = None
                for c_path in candidates:
                    if c_path in file_set:
                        try:
                            with zf.open(c_path) as jf:
                                sidecar_dict = json.loads(jf.read().decode("utf-8", errors="ignore"))
                                break
                        except Exception:
                            pass

                res = self.ingest_photo(
                    filename=filename,
                    img_bytes=img_bytes,
                    sidecar_dict=sidecar_dict,
                    generate_preview=generate_previews,
                )
                if res:
                    results["ingested"] += 1

            self.conn.commit()

        print(f"[✓] Photos archive ingestion complete: {results['ingested']} photos indexed.")
        return results

    def ingest_directory(
        self,
        dir_path: str,
        limit: Optional[int] = None,
        generate_previews: bool = True,
    ) -> Dict[str, Any]:
        """
        Scans a directory of photos with companion JSON sidecars or EXIF metadata.
        """
        dir_path = os.path.expanduser(dir_path)
        print(f"[*] Scanning Photos directory: {dir_path}...")
        results = {"total_found": 0, "ingested": 0, "skipped": 0}

        media_files = []
        for root, _, files in os.walk(dir_path):
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in IMAGE_EXTENSIONS and not f.startswith("."):
                    media_files.append(os.path.join(root, f))

        results["total_found"] = len(media_files)
        print(f"    Found {len(media_files)} photos in directory.")

        if limit:
            media_files = media_files[:limit]

        for file_path in media_files:
            filename = os.path.basename(file_path)
            try:
                with open(file_path, "rb") as f:
                    img_bytes = f.read()
            except Exception:
                results["skipped"] += 1
                continue

            # Look for sidecar files on disk
            base_no_ext, ext = os.path.splitext(file_path)
            sidecar_candidates = [
                file_path + ".supplemental-metadata.json",
                file_path + ".json",
                base_no_ext + ".json",
            ]

            sidecar_dict = None
            for sc in sidecar_candidates:
                if os.path.exists(sc):
                    try:
                        with open(sc, "r", encoding="utf-8") as jf:
                            sidecar_dict = json.load(jf)
                            break
                    except Exception:
                        pass

            res = self.ingest_photo(
                filename=filename,
                img_bytes=img_bytes,
                sidecar_dict=sidecar_dict,
                generate_preview=generate_previews,
            )
            if res:
                results["ingested"] += 1

        self.conn.commit()
        print(f"[✓] Photos directory ingestion complete: {results['ingested']} photos indexed.")
        return results
