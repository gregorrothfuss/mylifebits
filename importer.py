"""
High-performance Multi-Source Fusion Importer.
Fuses 2024 Cloud Takeout Backups, 2026 On-Device Timeline Exports, and Contributor Reviews GeoJSON into SQLite.
"""

import json
import zipfile
import glob
import argparse
import re
import os
import time
import math
import datetime
from typing import Dict, Any, List, Optional, Tuple
import sqlite3

from db import get_db_connection, init_db, DEFAULT_DB_PATH


def parse_latlng_str(s: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    """Parses '47.3597948°, 8.5583026°' into (47.3597948, 8.5583026)."""
    if not s:
        return None, None
    m = re.findall(r'([-+]?\d*\.\d+|\d+)', s)
    if len(m) >= 2:
        try:
            return float(m[0]), float(m[1])
        except ValueError:
            return None, None
    return None, None


def parse_iso_timestamp(ts_str: Optional[str]) -> Tuple[Optional[float], Optional[str], Optional[int], Optional[int], Optional[int]]:
    """
    Parses ISO 8601 string into (unix_ts_utc, date_str, year, month, day).
    Example: '2024-10-01T00:03:26.000Z' or '1979-07-14T07:00:00.000-04:00'.
    """
    if not ts_str:
        return None, None, None, None, None
    
    clean_ts = ts_str.strip()
    try:
        dt = datetime.datetime.fromisoformat(clean_ts.replace('Z', '+00:00'))
        utc_ts = dt.timestamp()
        date_str = clean_ts[:10]
        year = dt.year
        month = dt.month
        day = dt.day
        return utc_ts, date_str, year, month, day
    except Exception:
        try:
            date_str = clean_ts[:10]
            parts = date_str.split('-')
            year = int(parts[0])
            month = int(parts[1])
            day = int(parts[2])
            dt = datetime.datetime(year, month, day, tzinfo=datetime.timezone.utc)
            return dt.timestamp(), date_str, year, month, day
        except Exception:
            return None, None, None, None, None


def parse_iso_with_tz_offset(ts_str: Optional[str], offset_minutes: Optional[int]) -> Tuple[Optional[float], Optional[str], Optional[int], Optional[int], Optional[int], Optional[str]]:
    """
    Parses ISO 8601 timestamp and applies true local timezone offset from Takeout metadata.
    Returns: (utc_ts, local_date_str, year, month, day, local_iso_str)
    """
    if not ts_str:
        return None, None, None, None, None, None
    try:
        clean_ts = ts_str.strip().replace('Z', '+00:00')
        dt = datetime.datetime.fromisoformat(clean_ts)
        utc_ts = dt.timestamp()

        if offset_minutes is not None:
            tz = datetime.timezone(datetime.timedelta(minutes=offset_minutes))
            local_dt = datetime.datetime.fromtimestamp(utc_ts, tz=tz)
        else:
            local_dt = dt

        local_date = local_dt.strftime('%Y-%m-%d')
        local_iso = local_dt.isoformat()
        return utc_ts, local_date, local_dt.year, local_dt.month, local_dt.day, local_iso
    except Exception:
        return None, None, None, None, None, None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates great-circle distance in kilometers between two points."""
    r = 6371.0  # Earth's radius in km
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def synthesize_place_name(name: Optional[str], address: Optional[str], semantic_type: Optional[str]) -> str:
    """Synthesizes human-readable names for homes, offices, and saved locations."""
    if name and name.strip() and name.strip().upper() not in ('UNKNOWN', 'UNKNOWN_LOCATION', 'NONE'):
        return name.strip()
    
    addr_short = address.split(',')[0].strip() if address else ''
    sem = (semantic_type or '').upper()

    if 'HOME' in sem:
        if addr_short:
            return f'Home ({addr_short})'
        return 'Home'

    if 'WORK' in sem:
        if addr_short:
            return f'Work ({addr_short})'
        return 'Work'

    if addr_short:
        return addr_short

    return name.strip() if name and name.strip() else ""


def classify_category(name: Optional[str], address: Optional[str], semantic_type: Optional[str]) -> str:
    """Classifies places into standard broad categories."""
    try:
        from enrichment.contacts_and_categories import classify_advanced_category
        return classify_advanced_category(name, address, semantic_type)
    except Exception:
        text = f"{name or ''} {address or ''} {semantic_type or ''}".lower()
        if 'home' in text:
            return 'Home & Residence'
        if 'work' in text or 'google' in text:
            return 'Work & Office'
        if any(k in text for k in ['bakery', 'cafe', 'coffee', 'bar', 'restaurant', 'pizza', 'deli', 'ramen']):
            return 'Food & Drink'
        if any(k in text for k in ['station', 'subway', 'airport', 'terminal', 'train', 'tram', 'bus', 'grand central']):
            return 'Travel & Transit'
        if any(k in text for k in ['market', 'supermarket', 'mall', 'shop', 'store']):
            return 'Shopping & Retail'
        if any(k in text for k in ['hotel', 'motel', 'resort', 'inn', 'riad']):
            return 'Hotels & Lodging'
        if any(k in text for k in ['park', 'museum', 'theater', 'theater', 'garden']):
            return 'Arts & Entertainment'
        if any(k in text for k in ['spa', 'baths', 'gym', 'hospital', 'clinic']):
            return 'Health & Services'
        return 'Other / POI'


def extract_city_country(address: Optional[str], lat: Optional[float] = None, lng: Optional[float] = None) -> Tuple[str, str]:
    """Extracts city and country from address or coordinates."""
    if not address and lat is None:
        return 'Unknown', 'Unknown'

    addr = (address or '').lower()

    # US Major Cities
    if 'new york' in addr or 'brooklyn' in addr or 'manhattan' in addr or 'queens' in addr or 'bronx' in addr or 'ny ' in addr or ', ny' in addr:
        return 'New York', 'United States'
    if 'san francisco' in addr or 'oakland' in addr or 'berkeley' in addr or ', ca' in addr or 'california' in addr:
        if 'mountain view' in addr: return 'Mountain View', 'United States'
        if 'palo alto' in addr: return 'Palo Alto', 'United States'
        if 'sunnyvale' in addr: return 'Sunnyvale', 'United States'
        if 'san jose' in addr: return 'San Jose', 'United States'
        if 'san francisco' in addr: return 'San Francisco', 'United States'
        return 'California', 'United States'
    if 'chicago' in addr or ', il' in addr: return 'Chicago', 'United States'
    if 'boston' in addr or 'cambridge' in addr or ', ma' in addr: return 'Boston', 'United States'
    if 'los angeles' in addr: return 'Los Angeles', 'United States'
    if 'seattle' in addr or ', wa' in addr: return 'Seattle', 'United States'
    if 'reno' in addr or ', nv' in addr: return 'Reno', 'United States'

    # International Cities
    if 'zürich' in addr or 'zurich' in addr or 'schweiz' in addr or 'switzerland' in addr:
        return 'Zürich', 'Switzerland'
    if 'münchen' in addr or 'munich' in addr or 'germany' in addr or 'deutschland' in addr or 'berlin' in addr:
        if 'berlin' in addr: return 'Berlin', 'Germany'
        return 'Munich', 'Germany'
    if 'london' in addr or 'united kingdom' in addr or 'england' in addr:
        return 'London', 'United Kingdom'
    if 'paris' in addr or 'france' in addr:
        return 'Paris', 'France'
    if 'tokyo' in addr or 'japan' in addr:
        return 'Tokyo', 'Japan'

    # Coordinate fallback
    if lat and lng:
        if 40.5 <= lat <= 40.9 and -74.2 <= lng <= -73.7:
            return 'New York', 'United States'
        if 47.3 <= lat <= 47.5 and 8.4 <= lng <= 8.7:
            return 'Zürich', 'Switzerland'
        if 48.0 <= lat <= 48.3 and 11.4 <= lng <= 11.7:
            return 'Munich', 'Germany'
        if 37.6 <= lat <= 37.9 and -122.5 <= lng <= -122.2:
            return 'San Francisco', 'United States'

    # Fallback to comma token
    if address:
        parts = [p.strip() for p in address.split(',')]
        if len(parts) >= 2:
            return parts[-2], parts[-1]

    return 'Other', 'Other'


class TimelineFusionImporter:
    """Orchestrates multi-source ingestion and semantic data fusion."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        init_db(self.db_path)
        self.conn = get_db_connection(self.db_path)

    def import_takeout_zip(self, zip_path: str, import_segments: bool = True, include_records: bool = False, records_sample_stride: int = 1) -> Dict[str, Any]:
        """
        Extracts places catalog, road-snapped activity polylines, visits, and activities from Takeout zip.
        Works across classic Takeouts, modern on-device exports, GeoJSON, and multilingual archives.
        """
        zip_path = os.path.expanduser(zip_path)
        if not os.path.exists(zip_path):
            raise FileNotFoundError(f"Takeout archive not found: {zip_path}")

        print(f"[*] Importing Takeout archive: {zip_path}...")
        t0 = time.time()

        places_dict: Dict[str, Dict[str, Any]] = {}
        paths_by_time: Dict[int, List[List[float]]] = {}
        parsed_segments: List[Dict[str, Any]] = []
        total_semantic_files = 0
        total_takeout_objects = 0

        with zipfile.ZipFile(zip_path, 'r') as z:
            all_files = [f for f in z.namelist() if not f.startswith('__MACOSX')]
            semantic_files = [
                f for f in all_files
                if f.endswith('.json')
                and ('Semantic Location History' in f or 'Location History' in f or re.search(r'\d{4}_\w+\.json', f))
                and not f.endswith('Records.json')
                and not f.endswith('Settings.json')
                and not f.endswith('Timeline.json')
            ]
            total_semantic_files = len(semantic_files)
            if total_semantic_files > 0:
                print(f"    Found {total_semantic_files} monthly semantic files in Takeout archive.")

            for sf in semantic_files:
                try:
                    with z.open(sf) as f:
                        data = json.load(f)
                    timeline_objects = data.get('timelineObjects', [])
                    total_takeout_objects += len(timeline_objects)
                    segs, places, paths = self.parse_timeline_objects(timeline_objects, source_tag='TAKEOUT_CLOUD')
                    for pid, p in places.items():
                        if pid not in places_dict:
                            places_dict[pid] = p
                        else:
                            places_dict[pid]['visit_count'] += p['visit_count']
                    paths_by_time.update(paths)
                    if import_segments:
                        parsed_segments.extend(segs)
                except Exception as e:
                    print(f"    [!] Error reading {sf}: {e}")

            # Check if there is an on-device Timeline JSON in the zip
            if not semantic_files:
                timeline_files = [f for f in all_files if f.endswith('.json') and 'Timeline' in f]
                for tf in timeline_files:
                    try:
                        with z.open(tf) as f:
                            sample = f.read(2048).decode('utf-8', errors='ignore')
                        if 'semanticSegments' in sample:
                            import tempfile
                            with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp:
                                tmp.write(z.read(tf))
                                tmp_path = tmp.name
                            try:
                                return self.import_on_device_json(tmp_path)
                            finally:
                                if os.path.exists(tmp_path):
                                    os.unlink(tmp_path)
                    except Exception as e:
                        print(f"    [!] Error checking {tf}: {e}")

        # Batch insert/upsert places into DB
        if places_dict:
            print(f"[*] Upserting {len(places_dict)} places from Takeout...")
            place_rows = []
            for p in places_dict.values():
                place_rows.append((
                    p['place_id'], p['name'], p['address'], p['semantic_type'],
                    p['category'], p['city'], p['country'],
                    p['user_confirmed'], p['latitude'], p['longitude'],
                    p['visit_count'], 'TAKEOUT_CLOUD'
                ))

            self.conn.executemany("""
            INSERT INTO places (place_id, name, address, semantic_type, category, city, country, user_confirmed, latitude, longitude, visit_count, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(place_id) DO UPDATE SET
                name = COALESCE(excluded.name, places.name),
                address = COALESCE(excluded.address, places.address),
                semantic_type = COALESCE(excluded.semantic_type, places.semantic_type),
                category = excluded.category,
                city = COALESCE(excluded.city, places.city),
                country = COALESCE(excluded.country, places.country),
                user_confirmed = MAX(places.user_confirmed, excluded.user_confirmed),
                visit_count = places.visit_count + excluded.visit_count;
            """, place_rows)
            self.conn.commit()

        # Batch insert segments into DB if present
        if import_segments and parsed_segments:
            print(f"[*] Inserting {len(parsed_segments)} segments from Takeout...")
            parsed_segments.sort(key=lambda x: (x['start_ts'], x['end_ts']))
            segment_rows = [
                (
                    s['segment_type'], s['start_time'], s['end_time'], s['start_ts'], s['end_ts'],
                    s['duration_minutes'], s['date'], s['year'], s['month'], s['day'],
                    s['latitude'], s['longitude'], s['end_lat'], s['end_lng'],
                    s['place_id'], s['place_name'], s['place_address'], s['semantic_type'],
                    s['category'], s['city'], s['activity_type'], s['distance_meters'],
                    s['probability'], s['hierarchy_level'], s['parent_segment_id'],
                    s['path_points_json'], s['has_snapped_path'], s['is_unconfirmed'], s['source']
                ) for s in parsed_segments
            ]
            self.conn.executemany("""
            INSERT INTO segments (
                segment_type, start_time, end_time, start_ts, end_ts, duration_minutes,
                date, year, month, day, latitude, longitude, end_lat, end_lng,
                place_id, place_name, place_address, semantic_type, category, city,
                activity_type, distance_meters, probability, hierarchy_level,
                parent_segment_id, path_points_json, has_snapped_path, is_unconfirmed, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, segment_rows)
            self.conn.commit()

        # Import Records.json if requested
        records_count = 0
        if include_records:
            records_count = self._stream_records_json(zip_path, stride=records_sample_stride)

        # Record Source metadata
        self.conn.execute("""
        INSERT INTO sources (source_name, file_path, imported_at, record_count, metadata_json)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source_name) DO UPDATE SET
            imported_at = excluded.imported_at,
            record_count = excluded.record_count,
            metadata_json = excluded.metadata_json;
        """, (
            "TAKEOUT_ZIP",
            zip_path,
            datetime.datetime.now().isoformat(),
            total_takeout_objects,
            json.dumps({
                "semantic_files": total_semantic_files,
                "places_extracted": len(places_dict),
                "segments_imported": len(parsed_segments),
                "snapped_paths_extracted": len(paths_by_time),
                "raw_records_imported": records_count
            })
        ))
        self.conn.commit()

        elapsed = time.time() - t0
        print(f"[✓] Takeout archive ingested in {elapsed:.2f}s ({len(places_dict)} places, {len(parsed_segments)} segments).")
        return {
            "places_extracted": len(places_dict),
            "segments_imported": len(parsed_segments),
            "snapped_paths_extracted": len(paths_by_time),
            "paths_map": paths_by_time,
            "places_map": places_dict,
            "raw_records": records_count,
            "elapsed_sec": elapsed
        }

    def import_on_device_json(self, json_path: str, paths_map: Optional[Dict[int, List[List[float]]]] = None) -> Dict[str, Any]:
        """
        Ingests the on-device Timeline-*.json export, hydrating visits with verified place names/categories and Takeout polylines.
        """
        json_path = os.path.expanduser(json_path)
        if not os.path.exists(json_path):
            raise FileNotFoundError(f"On-device Timeline JSON not found: {json_path}")

        print(f"[*] Ingesting on-device export: {json_path}...")
        t0 = time.time()

        # Load known verified places from DB for instant hydration
        c = self.conn.cursor()
        c.execute("SELECT place_id, name, address, semantic_type, category, city, country, latitude, longitude FROM places;")
        known_places = {r['place_id']: dict(r) for r in c.fetchall()}
        print(f"    Loaded {len(known_places)} verified places for hydration.")

        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        semantic_segments = data.get('semanticSegments', [])
        raw_signals = data.get('rawSignals', [])
        print(f"    Found {len(semantic_segments)} semantic segments and {len(raw_signals)} raw signals.")

        parsed_segments = []
        for s in semantic_segments:
            st_str = s.get('startTime')
            et_str = s.get('endTime')
            st_off = s.get('startTimeTimezoneUtcOffsetMinutes')
            et_off = s.get('endTimeTimezoneUtcOffsetMinutes')

            st_ts, d_str, yr, mo, dy, local_st = parse_iso_with_tz_offset(st_str, st_off)
            et_ts, _, _, _, _, local_et = parse_iso_with_tz_offset(et_str, et_off)

            if not st_ts or not et_ts:
                continue

            dur_min = max(0.0, (et_ts - st_ts) / 60.0)

            if 'visit' in s:
                v = s['visit']
                top = v.get('topCandidate', {})
                pid = top.get('placeId')
                sem_type = top.get('semanticType')
                prob = top.get('probability', 1.0)
                # Correctly parse coordinates from placeLocation
                lat, lng = parse_latlng_str(
                    top.get('placeLocation', {}).get('latLng') or
                    v.get('hierarchy', {}).get('latLng') or
                    top.get('latLng')
                )
                h_level = 1 if (v.get('hierarchyLevel') == 1 or v.get('hierarchy', {}).get('hierarchyLevel') == 1) else 0

                # Hydrate place details from known places
                p_name, p_addr = None, None
                p_cat, p_city, p_country = 'Other / POI', 'Unknown', 'Unknown'
                if pid and pid in known_places:
                    p_info = known_places[pid]
                    p_name = p_info.get('name')
                    p_addr = p_info.get('address')
                    p_cat = p_info.get('category') or 'Other / POI'
                    p_city = p_info.get('city') or 'Unknown'
                    p_country = p_info.get('country') or 'Unknown'
                    if not lat and p_info.get('latitude'):
                        lat, lng = p_info['latitude'], p_info['longitude']

                # Synthesize residential / work names if still None
                p_name = synthesize_place_name(p_name, p_addr, sem_type)
                if not p_name and pid:
                    p_name = f"Google POI ({pid[:12]}...)" if not lat else None
                if p_cat == 'Other / POI':
                    p_cat = classify_category(p_name, p_addr, sem_type)
                if p_city == 'Unknown' and lat and lng:
                    p_city, p_country = extract_city_country(p_addr, lat, lng)

                parsed_segments.append({
                    'segment_type': 'visit',
                    'start_time': local_st or st_str,
                    'end_time': local_et or et_str,
                    'start_ts': st_ts,
                    'end_ts': et_ts,
                    'duration_minutes': dur_min,
                    'date': d_str,
                    'year': yr,
                    'month': mo,
                    'day': dy,
                    'latitude': lat,
                    'longitude': lng,
                    'end_lat': None,
                    'end_lng': None,
                    'place_id': pid,
                    'place_name': p_name or ("Confirmed POI" if pid else "Dwell Location"),
                    'place_address': p_addr,
                    'semantic_type': sem_type or ('CONFIRMED_PLACE' if pid else 'UNKNOWN'),
                    'category': p_cat,
                    'city': p_city,
                    'activity_type': None,
                    'distance_meters': 0.0,
                    'probability': prob,
                    'hierarchy_level': h_level,
                    'parent_segment_id': None,
                    'path_points_json': None,
                    'has_snapped_path': 0,
                    'is_unconfirmed': 1 if not pid and sem_type in (None, 'UNKNOWN', 'UNKNOWN_LOCATION') else 0,
                    'source': 'ON_DEVICE_2026'
                })

            elif 'activity' in s:
                act = s['activity']
                top = act.get('topCandidate', {})
                act_type = top.get('type')
                if act_type == 'IN_PASSENGER_VEHICLE':
                    act_type = 'DRIVING'
                prob = top.get('probability', 1.0)
                dist = act.get('distanceMeters', 0.0)
                s_lat, s_lng = parse_latlng_str(act.get('start', {}).get('latLng'))
                e_lat, e_lng = parse_latlng_str(act.get('end', {}).get('latLng'))

                # Calculate distance if 0.0 and coordinates exist
                if (not dist or dist == 0.0) and s_lat is not None and e_lat is not None:
                    dist = haversine_km(s_lat, s_lng, e_lat, e_lng) * 1000.0

                # Match snapped polyline from Takeout by UTC epoch minute
                path_pts = None
                has_snapped = 0
                if paths_map and st_ts:
                    ep_min = int(st_ts // 60)
                    path_pts = paths_map.get(ep_min) or paths_map.get(ep_min - 1) or paths_map.get(ep_min + 1)
                    if path_pts:
                        has_snapped = 1

                if not path_pts and s_lat is not None and e_lat is not None:
                    path_pts = [[s_lat, s_lng], [e_lat, e_lng]]

                parsed_segments.append({
                    'segment_type': 'activity',
                    'start_time': local_st or st_str,
                    'end_time': local_et or et_str,
                    'start_ts': st_ts,
                    'end_ts': et_ts,
                    'duration_minutes': dur_min,
                    'date': d_str,
                    'year': yr,
                    'month': mo,
                    'day': dy,
                    'latitude': s_lat,
                    'longitude': s_lng,
                    'end_lat': e_lat,
                    'end_lng': e_lng,
                    'place_id': None,
                    'place_name': None,
                    'place_address': None,
                    'semantic_type': None,
                    'category': 'Travel & Transit',
                    'city': None,
                    'activity_type': act_type,
                    'distance_meters': dist,
                    'probability': prob,
                    'hierarchy_level': 0,
                    'parent_segment_id': None,
                    'path_points_json': json.dumps(path_pts) if path_pts else None,
                    'has_snapped_path': has_snapped,
                    'is_unconfirmed': 1 if act_type in (None, 'UNKNOWN', 'UNKNOWN_ACTIVITY_TYPE') else 0,
                    'source': 'ON_DEVICE_2026'
                })

        # Deduplicate and upsert places from on-device segments
        new_places_dict = {}
        for s in parsed_segments:
            pid = s['place_id']
            if pid and pid not in known_places:
                if pid not in new_places_dict:
                    new_places_dict[pid] = (
                        pid, s['place_name'], s['place_address'], s['semantic_type'],
                        s['category'], s['city'], 'United States',
                        0, s['latitude'], s['longitude'], 1, 'ON_DEVICE_2026'
                    )
                else:
                    old = new_places_dict[pid]
                    new_places_dict[pid] = (
                        old[0], old[1] or s['place_name'], old[2] or s['place_address'],
                        old[3] or s['semantic_type'], old[4] or s['category'], old[5] or s['city'], old[6],
                        old[7], old[8] or s['latitude'], old[9] or s['longitude'], old[10] + 1, old[11]
                    )

        if new_places_dict:
            self.conn.executemany("""
            INSERT INTO places (place_id, name, address, semantic_type, category, city, country, user_confirmed, latitude, longitude, visit_count, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(place_id) DO UPDATE SET
                name = COALESCE(places.name, excluded.name),
                category = COALESCE(places.category, excluded.category),
                city = COALESCE(places.city, excluded.city),
                visit_count = places.visit_count + excluded.visit_count;
            """, list(new_places_dict.values()))
            self.conn.commit()

        # Sort segments chronologically and assign explicit IDs
        parsed_segments.sort(key=lambda x: (x['start_ts'], x['end_ts']))
        for idx, s in enumerate(parsed_segments, start=1):
            s['id'] = idx

        # Link parent/child visit hierarchy in memory
        print("[*] Linking parent/child visit hierarchy in memory...")
        parents = [s for s in parsed_segments if s['segment_type'] == 'visit' and s['hierarchy_level'] == 0]
        linked_count = 0
        for s in parsed_segments:
            if s['segment_type'] == 'visit' and s['hierarchy_level'] == 1:
                for p in parents:
                    if p['start_ts'] <= s['start_ts'] and p['end_ts'] >= s['end_ts']:
                        s['parent_segment_id'] = p['id']
                        linked_count += 1
                        break
        print(f"    Linked {linked_count} child visits to enclosing parent visits.")

        # Batch insert unified segments
        print(f"[*] Batch inserting {len(parsed_segments)} unified timeline segments...")
        self.conn.execute("PRAGMA foreign_keys = OFF;")
        self.conn.execute("DELETE FROM segments;")
        
        segment_rows = []
        for s in parsed_segments:
            segment_rows.append((
                s['id'], s['segment_type'], s['start_time'], s['end_time'], s['start_ts'], s['end_ts'],
                s['duration_minutes'], s['date'], s['year'], s['month'], s['day'],
                s['latitude'], s['longitude'], s['end_lat'], s['end_lng'],
                s['place_id'], s['place_name'], s['place_address'], s['semantic_type'],
                s['category'], s['city'],
                s['activity_type'], s['distance_meters'], s['probability'],
                s['hierarchy_level'], s['parent_segment_id'], s['path_points_json'],
                s['has_snapped_path'], s['is_unconfirmed'], s['source']
            ))

        self.conn.executemany("""
        INSERT INTO segments (
            id, segment_type, start_time, end_time, start_ts, end_ts,
            duration_minutes, date, year, month, day,
            latitude, longitude, end_lat, end_lng,
            place_id, place_name, place_address, semantic_type,
            category, city,
            activity_type, distance_meters, probability,
            hierarchy_level, parent_segment_id, path_points_json,
            has_snapped_path, is_unconfirmed, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, segment_rows)
        self.conn.commit()
        self.conn.execute("PRAGMA foreign_keys = ON;")

        # Ingest 30-day Raw Signals Buffer
        print(f"[*] Ingesting {len(raw_signals)} raw signals from mobile buffer...")
        raw_rows = []
        for sig in raw_signals:
            pos = sig.get('position')
            if pos:
                ts_str = pos.get('timestamp')
                u_ts, d_str, yr, mo, dy = parse_iso_timestamp(ts_str)
                lat, lng = parse_latlng_str(pos.get('LatLng'))
                acc = pos.get('accuracyMeters')
                alt = pos.get('altitudeMeters')
                spd = pos.get('speedMetersPerSecond')
                src = pos.get('source', 'WIFI').upper()
                if u_ts and lat is not None and lng is not None:
                    raw_rows.append((ts_str, u_ts, lat, lng, acc, alt, spd, src, d_str, yr))

        self.conn.executemany("""
        INSERT INTO raw_signals (timestamp, ts, latitude, longitude, accuracy_meters, altitude_meters, speed_mps, source, date, year)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, raw_rows)
        self.conn.commit()

        # Record Source
        self.conn.execute("""
        INSERT INTO sources (source_name, file_path, imported_at, record_count, metadata_json)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source_name) DO UPDATE SET
            imported_at = excluded.imported_at,
            record_count = excluded.record_count,
            metadata_json = excluded.metadata_json;
        """, (
            "ON_DEVICE_2026",
            json_path,
            datetime.datetime.now().isoformat(),
            len(parsed_segments),
            json.dumps({
                "segments": len(parsed_segments),
                "raw_signals": len(raw_rows),
                "visits": sum(1 for s in parsed_segments if s['segment_type'] == 'visit'),
                "activities": sum(1 for s in parsed_segments if s['segment_type'] == 'activity'),
                "snapped_paths_hydrated": sum(1 for s in parsed_segments if s['has_snapped_path'] == 1),
                "places_hydrated": sum(1 for s in parsed_segments if s['place_name'] is not None)
            })
        ))
        self.conn.commit()

        elapsed = time.time() - t0
        print(f"[✓] On-device Timeline imported and fused in {elapsed:.2f}s.")
        return {
            "total_segments": len(parsed_segments),
            "raw_signals_count": len(raw_rows),
            "snapped_paths_hydrated": sum(1 for s in parsed_segments if s['has_snapped_path'] == 1),
            "places_hydrated": sum(1 for s in parsed_segments if s['place_name'] is not None),
            "elapsed_sec": elapsed
        }

    def import_reviews_geojson(self, geojson_path: str) -> Dict[str, Any]:
        """
        Ingests Google Contributor Reviews, links them to visited POIs by proximity/name, and hydrates ratings & review text.
        """
        geojson_path = os.path.expanduser(geojson_path)
        if not os.path.exists(geojson_path):
            raise FileNotFoundError(f"Reviews GeoJSON not found: {geojson_path}")

        print(f"[*] Importing Google Contributor Reviews from: {geojson_path}...")
        t0 = time.time()

        with open(geojson_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        features = data.get('features', [])
        print(f"    Found {len(features)} review records.")

        # Fetch visited places
        c = self.conn.cursor()
        c.execute("SELECT place_id, name, latitude, longitude FROM places WHERE latitude IS NOT NULL;")
        places = [dict(r) for r in c.fetchall()]

        # Pre-index places into spatial hash grid for instant O(1) matching (<0.05s)
        grid_map: Dict[Tuple[int, int], List[Dict[str, Any]]] = {}
        for p in places:
            if p['latitude'] is not None and p['longitude'] is not None:
                cell = (int(round(p['latitude'] * 50)), int(round(p['longitude'] * 50)))
                grid_map.setdefault(cell, []).append(p)

        review_rows = []
        matched_updates = []
        matched_count = 0

        for feat in features:
            props = feat.get('properties') or {}
            geom = feat.get('geometry') or {}
            coords = geom.get('coordinates') or []
            r_lat = coords[1] if len(coords) >= 2 else None
            r_lng = coords[0] if len(coords) >= 2 else None

            p_name = props.get('place_name') or props.get('location', {}).get('name') or props.get('name') or ''
            r_date = props.get('date') or ''
            raw_rating = props.get('rating') if props.get('rating') is not None else props.get('five_star_rating_published')
            r_rating = int(round(raw_rating)) if raw_rating is not None else None
            r_text = (props.get('review_text') or props.get('review_text_published') or '').strip() or None
            r_url = props.get('review_direct_url') or props.get('google_maps_url') or ''
            r_pid = props.get('place_id')

            raw_photos = props.get('photo_urls') or []
            if isinstance(raw_photos, str):
                try:
                    raw_photos = json.loads(raw_photos)
                except Exception:
                    raw_photos = [raw_photos] if raw_photos.startswith('http') else []
            photo_urls_list = [u for u in raw_photos if isinstance(u, str) and u.startswith('http')]
            photo_count = props.get('photo_count') or len(photo_urls_list)
            photo_urls_json = json.dumps(photo_urls_list) if photo_urls_list else None

            # Fast candidate lookup: direct place_id or spatial grid (skip residential homes)
            matched_pid = None
            target_place = next((p for p in places if p['place_id'] == r_pid), None) if r_pid else None
            if target_place:
                # Never assign reviews to residential homes
                if target_place.get('category') != 'Home & Residence' and not (target_place.get('name') or '').startswith('Home'):
                    matched_pid = r_pid
                    matched_count += 1
                    matched_updates.append((
                        r_rating,
                        r_text,
                        p_name,
                        photo_urls_json,
                        photo_count,
                        matched_pid
                    ))

            review_rows.append((
                p_name, r_date, r_rating, r_text, r_url, r_lat, r_lng, matched_pid, photo_urls_json, photo_count
            ))

        # Insert reviews table
        self.conn.execute("DELETE FROM poi_reviews;")
        self.conn.executemany("""
        INSERT INTO poi_reviews (place_name, date, rating, review_text, google_maps_url, latitude, longitude, matched_place_id, photo_urls, photo_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, review_rows)

        # Hydrate matched places
        if matched_updates:
            self.conn.executemany("""
            UPDATE places
            SET review_rating = ?,
                review_text = ?,
                name = COALESCE(name, ?),
                has_review = 1,
                review_photos = COALESCE(?, review_photos),
                review_photo_count = MAX(COALESCE(review_photo_count, 0), ?),
                review_count = review_count + 1
            WHERE place_id = ?;
            """, matched_updates)

            # Also update segments with review rating
            self.conn.execute("""
            UPDATE segments
            SET review_rating = (SELECT p.review_rating FROM places p WHERE p.place_id = segments.place_id)
            WHERE place_id IS NOT NULL;
            """)

        self.conn.commit()
        elapsed = time.time() - t0
        print(f"[✓] Contributor Reviews imported in {elapsed:.2f}s ({len(features)} reviews, {matched_count} linked to timeline POIs).")
        return {
            "total_reviews": len(features),
            "matched_pois": matched_count,
            "elapsed_sec": elapsed
        }



    def parse_timeline_objects(
        self,
        timeline_objects: List[Dict[str, Any]],
        known_places: Optional[Dict[str, Dict[str, Any]]] = None,
        paths_map: Optional[Dict[int, List[List[float]]]] = None,
        source_tag: str = "TAKEOUT_SEMANTIC"
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[int, List[List[float]]]]:
        """Parses Takeout timelineObjects into segments, places dictionary, and waypoint paths."""
        places_dict: Dict[str, Dict[str, Any]] = {}
        paths_by_time: Dict[int, List[List[float]]] = {}
        parsed_segments: List[Dict[str, Any]] = []

        for obj in timeline_objects:
            if "placeVisit" in obj:
                pv = obj["placeVisit"]
                dur = pv.get("duration", {})
                st_str = dur.get("startTimestamp")
                et_str = dur.get("endTimestamp")
                loc = pv.get("location", {})
                pid = loc.get("placeId")
                raw_name = loc.get("name")
                addr = loc.get("address")
                sem_type = loc.get("semanticType")
                synth_name = synthesize_place_name(raw_name, addr, sem_type)
                lat = loc.get("latitudeE7") / 1e7 if "latitudeE7" in loc else None
                lng = loc.get("longitudeE7") / 1e7 if "longitudeE7" in loc else None
                is_conf = 1 if loc.get("locationConfidence", 0) > 80 or pv.get("editConfirmationStatus") == "USER_CONFIRMED" else 0
                cat = classify_category(synth_name, addr, sem_type)
                city, country = extract_city_country(addr, lat, lng)

                if pid:
                    if pid not in places_dict:
                        places_dict[pid] = {
                            "place_id": pid,
                            "name": synth_name,
                            "address": addr,
                            "semantic_type": sem_type,
                            "category": cat,
                            "city": city,
                            "country": country,
                            "user_confirmed": is_conf,
                            "latitude": lat,
                            "longitude": lng,
                            "visit_count": 1
                        }
                    else:
                        p = places_dict[pid]
                        p["visit_count"] += 1
                        if not p["name"] and synth_name:
                            p["name"] = synth_name
                        if not p["address"] and addr:
                            p["address"] = addr
                        if not p["latitude"] and lat:
                            p["latitude"] = lat
                            p["longitude"] = lng

                if st_str and et_str:
                    st_ts, d_str, yr, mo, dy = parse_iso_timestamp(st_str)
                    et_ts, _, _, _, _ = parse_iso_timestamp(et_str)
                    if st_ts and et_ts:
                        dur_min = max(0.0, (et_ts - st_ts) / 60.0)
                        parsed_segments.append({
                            "segment_type": "visit",
                            "start_time": st_str,
                            "end_time": et_str,
                            "start_ts": st_ts,
                            "end_ts": et_ts,
                            "duration_minutes": dur_min,
                            "date": d_str,
                            "year": yr,
                            "month": mo,
                            "day": dy,
                            "latitude": lat,
                            "longitude": lng,
                            "end_lat": None,
                            "end_lng": None,
                            "place_id": pid,
                            "place_name": synth_name or ("Confirmed POI" if pid else "Dwell Location"),
                            "place_address": addr,
                            "semantic_type": sem_type or ("CONFIRMED_PLACE" if pid else "UNKNOWN"),
                            "category": cat,
                            "city": city,
                            "activity_type": None,
                            "distance_meters": 0.0,
                            "probability": 1.0,
                            "hierarchy_level": 0,
                            "parent_segment_id": None,
                            "path_points_json": None,
                            "has_snapped_path": 0,
                            "is_unconfirmed": 0 if pid else 1,
                            "source": source_tag
                        })

            elif "activitySegment" in obj:
                act = obj["activitySegment"]
                dur = act.get("duration", {})
                st = dur.get("startTimestamp")
                et = dur.get("endTimestamp")

                pts: List[List[float]] = []
                if "waypointPath" in act:
                    wpts = act["waypointPath"].get("waypoints", [])
                    for wp in wpts:
                        if "latE7" in wp and "lngE7" in wp:
                            pts.append([wp["latE7"] / 1e7, wp["lngE7"] / 1e7])
                elif "simplifiedRawPath" in act:
                    spts = act["simplifiedRawPath"].get("points", [])
                    for sp in spts:
                        if "latE7" in sp and "lngE7" in sp:
                            pts.append([sp["latE7"] / 1e7, sp["lngE7"] / 1e7])
                elif "transitPath" in act:
                    tstops = act["transitPath"].get("transitStops", [])
                    for ts in tstops:
                        if "latitudeE7" in ts and "longitudeE7" in ts:
                            pts.append([ts["latitudeE7"] / 1e7, ts["longitudeE7"] / 1e7])

                if pts and st:
                    u_ts = parse_iso_timestamp(st)[0]
                    if u_ts:
                        ep_min = int(u_ts // 60)
                        paths_by_time[ep_min] = pts

                if st and et:
                    st_ts, d_str, yr, mo, dy = parse_iso_timestamp(st)
                    et_ts, _, _, _, _ = parse_iso_timestamp(et)
                    if st_ts and et_ts:
                        dur_min = max(0.0, (et_ts - st_ts) / 60.0)
                        s_loc = act.get("startLocation", {})
                        e_loc = act.get("endLocation", {})
                        s_lat = s_loc.get("latitudeE7") / 1e7 if "latitudeE7" in s_loc else (pts[0][0] if pts else None)
                        s_lng = s_loc.get("longitudeE7") / 1e7 if "longitudeE7" in s_loc else (pts[0][1] if pts else None)
                        e_lat = e_loc.get("latitudeE7") / 1e7 if "latitudeE7" in e_loc else (pts[-1][0] if pts else None)
                        e_lng = e_loc.get("longitudeE7") / 1e7 if "longitudeE7" in e_loc else (pts[-1][1] if pts else None)
                        act_type = act.get("activityType")
                        if act_type == "IN_PASSENGER_VEHICLE":
                            act_type = "DRIVING"
                        dist = float(act.get("distance", 0.0))
                        has_snapped = 1 if len(pts) > 2 else 0
                        parsed_segments.append({
                            "segment_type": "activity",
                            "start_time": st,
                            "end_time": et,
                            "start_ts": st_ts,
                            "end_ts": et_ts,
                            "duration_minutes": dur_min,
                            "date": d_str,
                            "year": yr,
                            "month": mo,
                            "day": dy,
                            "latitude": s_lat,
                            "longitude": s_lng,
                            "end_lat": e_lat,
                            "end_lng": e_lng,
                            "place_id": None,
                            "place_name": None,
                            "place_address": None,
                            "semantic_type": None,
                            "category": "Travel & Transit",
                            "city": None,
                            "activity_type": act_type or "MOVING",
                            "distance_meters": dist,
                            "probability": 1.0,
                            "hierarchy_level": 0,
                            "parent_segment_id": None,
                            "path_points_json": json.dumps(pts) if pts else None,
                            "has_snapped_path": has_snapped,
                            "is_unconfirmed": 0,
                            "source": source_tag
                        })

        return parsed_segments, places_dict, paths_by_time

    def import_semantic_json(self, json_path: str, import_segments: bool = True) -> Dict[str, Any]:
        """Ingests a single monthly Google Takeout JSON file (e.g. 2024_OCTOBER.json)."""
        json_path = os.path.expanduser(json_path)
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        timeline_objects = data.get("timelineObjects", [])
        parsed_segs, places_dict, paths_map = self.parse_timeline_objects(timeline_objects, source_tag="TAKEOUT_MONTHLY")

        # Upsert places
        if places_dict:
            place_rows = [
                (
                    p["place_id"], p["name"], p["address"], p["semantic_type"],
                    p["category"], p["city"], p["country"],
                    p["user_confirmed"], p["latitude"], p["longitude"],
                    p["visit_count"], "TAKEOUT_MONTHLY"
                ) for p in places_dict.values()
            ]
            self.conn.executemany("""
            INSERT INTO places (place_id, name, address, semantic_type, category, city, country, user_confirmed, latitude, longitude, visit_count, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(place_id) DO UPDATE SET
                name = COALESCE(excluded.name, places.name),
                address = COALESCE(excluded.address, places.address),
                category = excluded.category,
                visit_count = places.visit_count + excluded.visit_count;
            """, place_rows)
            self.conn.commit()

        # Insert segments
        if import_segments and parsed_segs:
            parsed_segs.sort(key=lambda x: (x["start_ts"], x["end_ts"]))
            segment_rows = [
                (
                    s["segment_type"], s["start_time"], s["end_time"], s["start_ts"], s["end_ts"],
                    s["duration_minutes"], s["date"], s["year"], s["month"], s["day"],
                    s["latitude"], s["longitude"], s["end_lat"], s["end_lng"],
                    s["place_id"], s["place_name"], s["place_address"], s["semantic_type"],
                    s["category"], s["city"], s["activity_type"], s["distance_meters"],
                    s["probability"], s["hierarchy_level"], s["parent_segment_id"],
                    s["path_points_json"], s["has_snapped_path"], s["is_unconfirmed"], s["source"]
                ) for s in parsed_segs
            ]
            self.conn.executemany("""
            INSERT INTO segments (
                segment_type, start_time, end_time, start_ts, end_ts, duration_minutes,
                date, year, month, day, latitude, longitude, end_lat, end_lng,
                place_id, place_name, place_address, semantic_type, category, city,
                activity_type, distance_meters, probability, hierarchy_level,
                parent_segment_id, path_points_json, has_snapped_path, is_unconfirmed, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, segment_rows)
            self.conn.commit()

        return {
            "places_extracted": len(places_dict),
            "segments_imported": len(parsed_segs) if import_segments else 0,
            "paths_map": paths_map
        }

    def import_geojson(self, geojson_path: str) -> Dict[str, Any]:
        """Ingests a GeoJSON FeatureCollection export from Google Takeout or Timeline."""
        geojson_path = os.path.expanduser(geojson_path)
        with open(geojson_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        features = data.get("features", [])
        if not features and isinstance(data, list):
            features = data

        parsed_segs: List[Dict[str, Any]] = []
        places_dict: Dict[str, Dict[str, Any]] = {}

        for feat in features:
            props = feat.get("properties", {})
            geom = feat.get("geometry", {})
            g_type = geom.get("type")
            coords = geom.get("coordinates", [])

            st_str = props.get("startTime") or props.get("startTimestamp")
            et_str = props.get("endTime") or props.get("endTimestamp")
            if not st_str or not et_str:
                continue

            st_ts, d_str, yr, mo, dy = parse_iso_timestamp(st_str)
            et_ts, _, _, _, _ = parse_iso_timestamp(et_str)
            if not st_ts or not et_ts:
                continue

            dur_min = max(0.0, (et_ts - st_ts) / 60.0)
            pid = props.get("placeId")
            p_name = props.get("name") or props.get("place_name")
            p_addr = props.get("address")
            sem_type = props.get("semanticType")
            act_type = props.get("activityType")

            if g_type == "Point" or pid or (not act_type and p_name):
                lat = coords[1] if len(coords) >= 2 else None
                lng = coords[0] if len(coords) >= 2 else None
                cat = classify_category(p_name, p_addr, sem_type)
                city, country = extract_city_country(p_addr, lat, lng)
                if pid:
                    places_dict[pid] = {
                        "place_id": pid, "name": p_name, "address": p_addr,
                        "semantic_type": sem_type, "category": cat, "city": city,
                        "country": country, "user_confirmed": 1, "latitude": lat,
                        "longitude": lng, "visit_count": 1
                    }
                parsed_segs.append({
                    "segment_type": "visit", "start_time": st_str, "end_time": et_str,
                    "start_ts": st_ts, "end_ts": et_ts, "duration_minutes": dur_min,
                    "date": d_str, "year": yr, "month": mo, "day": dy,
                    "latitude": lat, "longitude": lng, "end_lat": None, "end_lng": None,
                    "place_id": pid, "place_name": p_name or "Visited Location",
                    "place_address": p_addr, "semantic_type": sem_type or "CONFIRMED_PLACE",
                    "category": cat, "city": city, "activity_type": None,
                    "distance_meters": 0.0, "probability": 1.0, "hierarchy_level": 0,
                    "parent_segment_id": None, "path_points_json": None,
                    "has_snapped_path": 0, "is_unconfirmed": 0 if pid else 1,
                    "source": "GEOJSON"
                })
            elif g_type == "LineString" or act_type:
                pts = [[c[1], c[0]] for c in coords if len(c) >= 2] if g_type == "LineString" else None
                s_lat = pts[0][0] if pts else None
                s_lng = pts[0][1] if pts else None
                e_lat = pts[-1][0] if pts else None
                e_lng = pts[-1][1] if pts else None
                dist = float(props.get("distance", 0.0))
                parsed_segs.append({
                    "segment_type": "activity", "start_time": st_str, "end_time": et_str,
                    "start_ts": st_ts, "end_ts": et_ts, "duration_minutes": dur_min,
                    "date": d_str, "year": yr, "month": mo, "day": dy,
                    "latitude": s_lat, "longitude": s_lng, "end_lat": e_lat, "end_lng": e_lng,
                    "place_id": None, "place_name": None, "place_address": None,
                    "semantic_type": None, "category": "Travel & Transit", "city": None,
                    "activity_type": act_type or "MOVING", "distance_meters": dist,
                    "probability": 1.0, "hierarchy_level": 0, "parent_segment_id": None,
                    "path_points_json": json.dumps(pts) if pts else None,
                    "has_snapped_path": 1 if pts and len(pts) > 2 else 0,
                    "is_unconfirmed": 0, "source": "GEOJSON"
                })

        if places_dict:
            self.conn.executemany("""
            INSERT INTO places (place_id, name, address, semantic_type, category, city, country, user_confirmed, latitude, longitude, visit_count, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(place_id) DO UPDATE SET
                name = COALESCE(excluded.name, places.name),
                visit_count = places.visit_count + excluded.visit_count;
            """, [
                (p["place_id"], p["name"], p["address"], p["semantic_type"], p["category"], p["city"], p["country"], p["user_confirmed"], p["latitude"], p["longitude"], p["visit_count"], "GEOJSON")
                for p in places_dict.values()
            ])
            self.conn.commit()

        if parsed_segs:
            parsed_segs.sort(key=lambda x: (x["start_ts"], x["end_ts"]))
            self.conn.executemany("""
            INSERT INTO segments (
                segment_type, start_time, end_time, start_ts, end_ts, duration_minutes,
                date, year, month, day, latitude, longitude, end_lat, end_lng,
                place_id, place_name, place_address, semantic_type, category, city,
                activity_type, distance_meters, probability, hierarchy_level,
                parent_segment_id, path_points_json, has_snapped_path, is_unconfirmed, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, [
                (
                    s["segment_type"], s["start_time"], s["end_time"], s["start_ts"], s["end_ts"],
                    s["duration_minutes"], s["date"], s["year"], s["month"], s["day"],
                    s["latitude"], s["longitude"], s["end_lat"], s["end_lng"],
                    s["place_id"], s["place_name"], s["place_address"], s["semantic_type"],
                    s["category"], s["city"], s["activity_type"], s["distance_meters"],
                    s["probability"], s["hierarchy_level"], s["parent_segment_id"],
                    s["path_points_json"], s["has_snapped_path"], s["is_unconfirmed"], s["source"]
                ) for s in parsed_segs
            ])
            self.conn.commit()

        print(f"[✓] Imported GeoJSON: {geojson_path} ({len(places_dict)} places, {len(parsed_segs)} segments).")
        return {"places": len(places_dict), "segments": len(parsed_segs)}

    def import_takeout_directory(self, dir_path: str, include_records: bool = False, records_sample_stride: int = 1) -> Dict[str, Any]:
        """Walks an extracted Google Takeout directory and imports all monthly files, Timeline.json, and reviews."""
        dir_path = os.path.expanduser(dir_path)
        if not os.path.isdir(dir_path):
            raise NotADirectoryError(f"Directory not found: {dir_path}")

        print(f"[*] Scanning Takeout directory: {dir_path}...")
        results = {"files_processed": 0, "places": 0, "segments": 0}

        # 1. Look for on-device or unified Timeline.json
        timeline_files = glob.glob(os.path.join(dir_path, "**", "Timeline*.json"), recursive=True)
        for tf in timeline_files:
            try:
                with open(tf, "r", encoding="utf-8") as f:
                    sample = f.read(1024)
                if "semanticSegments" in sample:
                    print(f"    Found on-device Timeline JSON: {tf}")
                    res = self.import_on_device_json(tf)
                    results["segments"] += res.get("total_segments", 0)
                    results["files_processed"] += 1
            except Exception as e:
                print(f"    [!] Error parsing {tf}: {e}")

        # 2. Look for monthly semantic files
        monthly_files = []
        for root, _, files in os.walk(dir_path):
            for file in sorted(files):
                if file.endswith(".json") and re.search(r"\d{4}_\w+\.json", file):
                    monthly_files.append(os.path.join(root, file))

        if monthly_files:
            print(f"    Found {len(monthly_files)} monthly semantic files.")
            for mf in monthly_files:
                try:
                    res = self.import_semantic_json(mf, import_segments=True)
                    results["places"] += res.get("places_extracted", 0)
                    results["segments"] += res.get("segments_imported", 0)
                    results["files_processed"] += 1
                except Exception as e:
                    print(f"    [!] Error parsing {mf}: {e}")

        # 3. Look for reviews
        review_files = glob.glob(os.path.join(dir_path, "**", "*review*.geojson"), recursive=True) + \
                       glob.glob(os.path.join(dir_path, "**", "*review*.json"), recursive=True)
        for rf in review_files:
            try:
                self.import_reviews_geojson(rf)
                results["files_processed"] += 1
            except Exception:
                pass

        print(f"[✓] Takeout directory import complete: {results['files_processed']} files, {results['segments']} segments.")
        return results

    def import_any(self, path: str, include_records: bool = False, records_sample_stride: int = 1) -> Dict[str, Any]:
        """Universal entrypoint that detects file type (ZIP, Directory, JSON, GeoJSON) and imports cleanly."""
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Path does not exist: {path}")

        if os.path.isdir(path):
            return self.import_takeout_directory(path, include_records=include_records, records_sample_stride=records_sample_stride)

        if zipfile.is_zipfile(path):
            return self.import_takeout_zip(path, import_segments=True, include_records=include_records, records_sample_stride=records_sample_stride)

        if path.lower().endswith(".geojson"):
            return self.import_geojson(path)

        if path.lower().endswith(".json"):
            # Inspect first 2KB of file to identify format
            with open(path, "r", encoding="utf-8") as f:
                header = f.read(2048)
            if "semanticSegments" in header:
                return self.import_on_device_json(path)
            elif "timelineObjects" in header:
                return self.import_semantic_json(path, import_segments=True)
            elif "FeatureCollection" in header or '"type": "Feature"' in header:
                return self.import_geojson(path)
            elif "locations" in header:
                return {"records_imported": self._stream_records_json(path, stride=records_sample_stride)}
            else:
                try:
                    # Fallback try GeoJSON or on-device
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if "features" in data:
                        return self.import_geojson(path)
                    elif "semanticSegments" in data:
                        return self.import_on_device_json(path)
                    elif "timelineObjects" in data:
                        return self.import_semantic_json(path, import_segments=True)
                except Exception as e:
                    raise ValueError(f"Unrecognized Takeout JSON format: {path} ({e})")

        raise ValueError(f"Unsupported file type: {path}. Expected .zip, .json, .geojson, or directory.")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Universal Google Takeout & Location History Importer into Timeline Studio."
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="Path(s) to Takeout archive (.zip), extracted directory, Timeline JSON, or GeoJSON file(s)",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Target SQLite database path (default: TIMELINE_DB_PATH or ./timeline.db)",
    )
    parser.add_argument(
        "--include-records",
        action="store_true",
        help="Also stream and index raw GPS fixes from Records.json",
    )
    parser.add_argument(
        "--stride",
        type=int,
        default=1,
        help="Sampling stride when importing raw Records.json (default 1 = every record)",
    )
    args = parser.parse_args()

    db_path = args.db or DEFAULT_DB_PATH
    importer = TimelineFusionImporter(db_path=db_path)

    for target in args.inputs:
        print(f"\n=======================================================")
        print(f"[*] Processing: {target}")
        print(f"=======================================================")
        try:
            importer.import_any(target, include_records=args.include_records, records_sample_stride=args.stride)
        except Exception as e:
            print(f"[!] Error importing {target}: {e}")

    print("\n[✓] All imports completed successfully.")


if __name__ == "__main__":
    main()
