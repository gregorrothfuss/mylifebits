"""
Bank & Credit Card Transactions Connector.
Matches timestamped merchant payments against unconfirmed places and timeline gaps.
"""

from typing import Dict, Any, List, Optional
from enrichment.base import BaseEnrichmentConnector, FixProposalData
from importer import haversine_km


class TransactionsConnector(BaseEnrichmentConnector):
    """Parses bank/credit card statement CSVs to associate merchant locations with timeline visits."""

    def __init__(self, transactions: Optional[List[Dict[str, Any]]] = None):
        # transactions: list of {'timestamp': '...', 'ts': ..., 'merchant': '...', 'amount': ..., 'lat': ..., 'lng': ..., 'address': '...'}
        self.transactions = transactions or []

    def get_source_name(self) -> str:
        return "TRANSACTIONS"

    def generate_proposals(self, gaps: List[Dict[str, Any]], unconfirmed_places: List[Dict[str, Any]]) -> List[FixProposalData]:
        proposals = []
        if not self.transactions:
            return proposals

        # Match transactions to unconfirmed visits
        for place in unconfirmed_places:
            p_st = place['start_ts']
            p_et = place['end_ts']
            p_lat = place.get('latitude')
            p_lng = place.get('longitude')

            for tx in self.transactions:
                tx_ts = tx.get('ts')
                if tx_ts and (p_st - 1800 <= tx_ts <= p_et + 1800):  # +/- 30 min tolerance
                    tx_lat = tx.get('lat')
                    tx_lng = tx.get('lng')
                    dist = haversine_km(p_lat, p_lng, tx_lat, tx_lng) if p_lat and tx_lat else 0.0

                    if dist <= 0.5:  # Within 500 meters
                        reasoning = (
                            f"Matched financial transaction of ${tx.get('amount', 0):.2f} at '{tx.get('merchant')}' "
                            f"({tx.get('timestamp', '')[11:16]}) located {dist*1000:.0f}m from unconfirmed visit."
                        )
                        proposals.append(FixProposalData(
                            target_type='UNCONFIRMED_PLACE',
                            target_id=place['id'],
                            date=place['date'],
                            proposed_action='HYDRATE_PLACE',
                            source=self.get_source_name(),
                            reasoning=reasoning,
                            confidence=0.88,
                            patch_data={
                                "resolved_name": tx.get('merchant'),
                                "address": tx.get('address'),
                                "transaction_amount": tx.get('amount')
                            }
                        ))
        return proposals
