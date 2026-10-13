"""
Photos EXIF Connector.
Extracts GPS metadata and timestamps from image libraries to resolve timeline gaps and unconfirmed places.
"""

import os
import datetime
from typing import Dict, Any, List, Optional
from enrichment.base import BaseEnrichmentConnector, FixProposalData
from importer import parse_iso_timestamp, haversine_km


class PhotosEXIFConnector(BaseEnrichmentConnector):
    """Scans local photo folders or Google Photos Takeout metadata for EXIF timestamps and coordinates."""

    def __init__(self, photo_records: Optional[List[Dict[str, Any]]] = None):
        # photo_records: list of {'timestamp': '...', 'lat': ..., 'lng': ..., 'filename': '...'}
        self.photo_records = photo_records or []

    def get_source_name(self) -> str:
        return "PHOTOS_EXIF"

    def generate_proposals(self, gaps: List[Dict[str, Any]], unconfirmed_places: List[Dict[str, Any]]) -> List[FixProposalData]:
        proposals = []
        if not self.photo_records:
            return proposals

        for gap in gaps:
            gap_st = gap['start_ts']
            gap_et = gap['end_ts']
            gap_date = gap['date']

            # Find photos taken during this gap
            matching_photos = [
                p for p in self.photo_records
                if p.get('ts') and gap_st <= p['ts'] <= gap_et
            ]

            if matching_photos:
                first_p = matching_photos[0]
                p_lat, p_lng = first_p.get('lat'), first_p.get('lng')
                reasoning = (
                    f"Found {len(matching_photos)} photo(s) taken during gap ({gap['start_time'][11:16]} - {gap['end_time'][11:16]}). "
                    f"Sample photo '{first_p.get('filename', 'IMG')}' has GPS fix at [{p_lat:.4f}, {p_lng:.4f}]."
                )
                proposals.append(FixProposalData(
                    target_type='GAP',
                    target_id=gap['id'],
                    date=gap_date,
                    proposed_action='INSERT_VISIT',
                    source=self.get_source_name(),
                    reasoning=reasoning,
                    confidence=0.92,
                    patch_data={
                        "latitude": p_lat,
                        "longitude": p_lng,
                        "start_time": first_p.get('timestamp'),
                        "photo_count": len(matching_photos),
                        "evidence_files": [p.get('filename') for p in matching_photos[:5]]
                    }
                ))

        return proposals
