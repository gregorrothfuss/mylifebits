"""
Route modules registration package.
Importing this package automatically binds all domain route handlers to the router.
"""

from api.routes import (
    breadcrumbs,
    device,
    diagnostics,
    export,
    fixes,
    life,
    overview,
    photos,
    places,
    search,
    segments,
    timeline,
    trips,
)

__all__ = [
    "breadcrumbs",
    "device",
    "diagnostics",
    "export",
    "fixes",
    "life",
    "overview",
    "photos",
    "places",
    "search",
    "segments",
    "timeline",
    "trips",
]
