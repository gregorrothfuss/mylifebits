"""
Email & Flight Confirmation Connector.
Parses airline bookings, hotel check-ins, and ride-share receipts from Gmail / Takeout emails.
"""

from typing import Dict, Any, List, Optional
from enrichment.base import BaseEnrichmentConnector, FixProposalData
from importer import haversine_km


class EmailConnector(BaseEnrichmentConnector):
    """Matches flight itineraries, hotel bookings, and Uber/Lyft receipts against timeline gaps."""

    def __init__(self, email_events: Optional[List[Dict[str, Any]]] = None):
        # email_events: list of {'type': 'FLIGHT'|'HOTEL'|'RIDESHARE', 'flight_number': '...', 'origin': '...', 'dest': '...', 'dep_time': '...', 'arr_time': '...', 'dep_ts': ..., 'arr_ts': ..., 'origin_coords': [...], 'dest_coords': [...]}
        self.email_events = email_events or []

    def get_source_name(self) -> str:
        return "GMAIL"

    def generate_proposals(self, gaps: List[Dict[str, Any]], unconfirmed_places: List[Dict[str, Any]]) -> List[FixProposalData]:
        proposals = []
        if not self.email_events:
            return proposals

        for gap in gaps:
            gap_st = gap['start_ts']
            gap_et = gap['end_ts']
            jump_km = gap.get('jump_distance_km') or 0.0

            for ev in self.email_events:
                ev_type = ev.get('type')
                if ev_type == 'FLIGHT':
                    dep_ts = ev.get('dep_ts')
                    arr_ts = ev.get('arr_ts')
                    if dep_ts and arr_ts and (gap_st - 3600 <= dep_ts) and (arr_ts <= gap_et + 3600):
                        reasoning = (
                            f"Identified confirmed flight {ev.get('flight_number', 'FLIGHT')} from {ev.get('origin', 'A')} to {ev.get('dest', 'B')} "
                            f"in Gmail booking ({ev.get('dep_time', '')[11:16]} - {ev.get('arr_time', '')[11:16]}). "
                            f"Matches timeline jump of {jump_km:.1f} km across {gap['duration_hours']:.1f} hour gap."
                        )
                        proposals.append(FixProposalData(
                            target_type='GAP',
                            target_id=gap['id'],
                            date=gap['date'],
                            proposed_action='INSERT_ACTIVITY',
                            source=self.get_source_name(),
                            reasoning=reasoning,
                            confidence=0.98,
                            patch_data={
                                "activity_type": "FLYING",
                                "flight_number": ev.get('flight_number'),
                                "origin": ev.get('origin'),
                                "destination": ev.get('dest'),
                                "start_time": ev.get('dep_time'),
                                "end_time": ev.get('arr_time'),
                                "start_coords": ev.get('origin_coords'),
                                "end_coords": ev.get('dest_coords')
                            }
                        ))
        return proposals
