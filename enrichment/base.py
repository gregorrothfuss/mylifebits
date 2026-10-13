"""
Base classes and interfaces for Multi-Source Timeline Enrichment.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
import datetime
import json


@dataclass
class FixProposalData:
    target_type: str            # 'GAP', 'UNCONFIRMED_PLACE', 'ACTIVITY_PATH', 'TOP_LEVEL_OVERLAP'
    target_id: int
    date: str
    proposed_action: str        # 'INSERT_VISIT', 'INSERT_ACTIVITY', 'HYDRATE_PLACE', 'SNAP_ROUTE', 'MERGE_SEGMENTS'
    source: str                 # 'PHOTOS_EXIF', 'GMAIL', 'TRANSACTIONS', 'ROUTING_OSRM', 'TAKEOUT_FUSION'
    reasoning: str
    confidence: float
    patch_data: Dict[str, Any]

    def to_tuple(self) -> tuple:
        return (
            self.target_type,
            self.target_id,
            self.date,
            self.proposed_action,
            self.source,
            self.reasoning,
            self.confidence,
            'PENDING',
            json.dumps(self.patch_data),
            datetime.datetime.now().isoformat()
        )


class BaseEnrichmentConnector(ABC):
    """Abstract interface for external data source connectors."""

    @abstractmethod
    def get_source_name(self) -> str:
        """Returns human-readable name of data source."""
        pass

    @abstractmethod
    def generate_proposals(self, gaps: List[Dict[str, Any]], unconfirmed_places: List[Dict[str, Any]]) -> List[FixProposalData]:
        """Examines timeline anomalies and generates structured fix proposals with explainable reasoning."""
        pass
