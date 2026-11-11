"""
Modular Road-Snapping & Pathfinder Engine.
Generates turn-by-turn road geometries for straight-line movement segments using local OSRM or OpenRouteService.
"""

import json
import urllib.request
import urllib.parse
from typing import Dict, Any, List, Optional, Tuple
from enrichment.base import BaseEnrichmentConnector, FixProposalData


class RoutingSnapperConnector(BaseEnrichmentConnector):
    """Snaps straight-line movements to actual road and transit networks."""

    def __init__(self, osrm_base_url: str = "http://router.project-osrm.org"):
        self.osrm_base_url = osrm_base_url

    def get_source_name(self) -> str:
        return "ROUTING_OSRM"

    def snap_route(self, start_lat: float, start_lng: float, end_lat: float, end_lng: float, mode: str = "car") -> Optional[List[List[float]]]:
        """Queries OSRM / Pathfinder routing API for turn-by-turn polyline."""
        profile = "driving"
        if mode.upper() in ("WALKING", "ON_FOOT", "HIKING"):
            profile = "foot"
        elif mode.upper() in ("CYCLING", "BIKING"):
            profile = "bike"

        url = f"{self.osrm_base_url}/route/v1/{profile}/{start_lng},{start_lat};{end_lng},{end_lat}?overview=full&geometries=geojson"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'TimelineViewer/1.0'})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if data.get('code') == 'Ok' and data.get('routes'):
                    coords = data['routes'][0]['geometry']['coordinates']
                    # Convert [lng, lat] to [lat, lng]
                    return [[c[1], c[0]] for c in coords]
        except Exception:
            pass
        return None

    def generate_proposals(self, gaps: List[Dict[str, Any]], unconfirmed_places: List[Dict[str, Any]]) -> List[FixProposalData]:
        # Propose road-snapping for activities needing path reconstruction
        return []
