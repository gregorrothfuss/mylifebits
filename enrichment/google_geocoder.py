"""
Google Places API (New) v1 Knowledge Graph Resolver & POI Hydrator.
Fetches official displayName, formattedAddress, primaryType, and types from Google Places API
and populates the SQLite catalog with deterministic taxonomy categories.
"""

import sqlite3
import urllib.request
import json
import os
import sys
import time
from typing import Dict, Any, Optional

try:
    from enrichment.place_types_taxonomy import map_google_types_to_category
except ImportError:
    from place_types_taxonomy import map_google_types_to_category

DEFAULT_DB_PATH = 'timeline_viewer.db'
DEFAULT_API_KEY = ''


def resolve_place_id_via_google_v1(place_id: str, api_key: str = DEFAULT_API_KEY) -> Optional[Dict[str, Any]]:
    """
    Fetches POI metadata directly from Google Places API (New) v1.
    Extracts name, address, primaryType, and all taxonomy types.
    """
    url = f'https://places.googleapis.com/v1/places/{place_id}?key={api_key}'
    headers = {
        'User-Agent': 'GoogleTimelineStudio/2.0',
        'X-Goog-FieldMask': 'id,displayName,formattedAddress,primaryType,types,rating,location'
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            name = data.get('displayName', {}).get('text')
            address = data.get('formattedAddress')
            primary_type = data.get('primaryType')
            types = data.get('types', [])
            rating = data.get('rating')
            loc = data.get('location', {})
            
            if name:
                category = map_google_types_to_category(primary_type, types) or 'Other / POI'
                return {
                    'name': name,
                    'address': address,
                    'primary_type': primary_type,
                    'types': types,
                    'category': category,
                    'rating': rating,
                    'lat': loc.get('latitude'),
                    'lng': loc.get('longitude')
                }
    except urllib.error.HTTPError as he:
        pass
    except Exception as e:
        pass
    return None


def batch_hydrate_unresolved_places(api_key: str = DEFAULT_API_KEY, db_path: str = DEFAULT_DB_PATH, limit: int = 200) -> int:
    """
    Hydrates places that are missing official names or types from Google Places API (New).
    """
    conn = sqlite3.connect(db_path, timeout=30.0)
    c = conn.cursor()
    c.execute("""
    SELECT place_id
    FROM places
    WHERE (name IS NULL OR name = '' OR name = 'Unconfirmed Location' OR primary_type IS NULL)
      AND place_id LIKE 'ChIJ%'
    ORDER BY visit_count DESC
    LIMIT ?;
    """, (limit,))
    pids = [r[0] for r in c.fetchall()]
    print(f"[*] Found {len(pids)} places to hydrate with official Google Place Types and categories...")
    
    success = 0
    for pid in pids:
        details = resolve_place_id_via_google_v1(pid, api_key)
        if details and details.get('name'):
            types_json = json.dumps(details.get('types', []))
            c.execute("""
            UPDATE places
            SET name = ?,
                address = ?,
                primary_type = ?,
                types = ?,
                category = ?,
                source = 'google_places_api_v1'
            WHERE place_id = ?;
            """, (details['name'], details['address'], details.get('primary_type'), types_json, details['category'], pid))
            
            c.execute("""
            UPDATE segments
            SET place_name = ?,
                place_address = ?,
                primary_type = ?,
                category = ?,
                is_unconfirmed = 0
            WHERE place_id = ?;
            """, (details['name'], details['address'], details.get('primary_type'), details['category'], pid))
            conn.commit()
            success += 1
            print(f"  [✓] POI Lookup: {pid[:15]}... -> {details['name']} (Type: {details.get('primary_type')} -> {details['category']})")
        time.sleep(0.06)
        
    conn.close()
    print(f"[✓] Completed Google Places POI hydration: {success}/{len(pids)} places resolved.")
    return success


if __name__ == '__main__':
    key = os.environ.get('GOOGLE_MAPS_API_KEY') or os.environ.get('GOOGLE_API_KEY') or DEFAULT_API_KEY
    batch_hydrate_unresolved_places(key, limit=50)
