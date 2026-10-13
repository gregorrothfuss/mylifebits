"""
Multi-Source Timeline Enrichment Framework.
"""
from enrichment.base import BaseEnrichmentConnector, FixProposalData
from enrichment.photos import PhotosEXIFConnector
from enrichment.transactions import TransactionsConnector
from enrichment.email_connector import EmailConnector
from enrichment.routing import RoutingSnapperConnector
from enrichment.engine import TimelineEnrichmentEngine
