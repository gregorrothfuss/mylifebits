# MyLifeBits: Personal Location Timeline & Life Archive

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

A privacy-first, zero-telemetry personal location history viewer, multi-source Google Takeout ingestion engine, and timeline studio.

Store decades of your physical movements locally in a clean, queryable SQLite database. Browse and inspect every day of your life through a responsive web interface with map trajectories, activity breakdowns, trip clustering, photo evidence, and place catalogs.

---

## Highlights

- **Universal Google Takeout Ingestion**:
  - **Location History**: Classic monthly archives (2008–2024 ZIPs/directories), modern on-device exports (`Timeline.json`), standard GeoJSON FeatureCollections, and raw GPS fixes (`Records.json`).
  - **Google Photos Takeout**: Direct streaming ingestion from ZIP files or folders with `.json` sidecars (`photoTakenTime`, `geoData`, `people`), EXIF fallback, and auto-generated WebP preview thumbnails.
  - **Google Maps Reviews**: Ingests `Reviews.json` or `reviews.geojson`, extracting star ratings and review text with spatial proximity linking to visited venues.
  - **Google Maps Saved Places**: Ingests `Saved Places.json` (Starred places, Want to go, Favorites, and custom notes).
- **Interactive Web Studio**:
  - Full-fidelity daily timeline view with interactive Leaflet map and bottom-sheet segment cards.
  - Multi-year calendar heatmap with instant date navigation and day-to-day scrubbing.
  - Places catalog with category filtering, canonical taxonomy normalization, and visit history.
  - Integrated photo evidence and contributor reviews attached to visits and days.
  - Trip clustering and international travel statistics.
- **Privacy-First & Self-Contained**:
  - 100% local SQLite storage (`timeline.db`). Zero external telemetry, zero tracking, and no cloud accounts required.
- **Physical & Temporal Plausibility**:
  - Enforces continuous overnight visit integrity (no midnight splits).
  - Enforces physical velocity constraints (distance $> 300\text{ km}$ and speed $> 250\text{ km/h}$ for flights).
  - Canonical 20-byte Google Maps Feature ID and Place ID preservation.
- **Extensible Architecture**:
  - RESTful JSON API documented for alternative clients and cross-platform reimplementations (see [ARCHITECTURE.md](docs/ARCHITECTURE.md)).

---

## Quickstart

### 1. Prerequisites
- Python 3.10 or higher
- [`uv`](https://github.com/astral-sh/uv) (recommended) or standard `pip`

### 2. Installation

Clone the repository and install dependencies:

```bash
git clone https://github.com/your-username/mylifebits.git
cd mylifebits

# Using uv (fastest):
uv sync

# Or using standard pip:
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 3. Explore with Demo Data

Generate an anonymized, multi-day demo timeline in a fresh SQLite database:

```bash
uv run python scripts/init_db.py --demo
```

Launch the local web server:

```bash
uv run python server.py
```

Open your browser to:
```text
http://127.0.0.1:8000
```
*(If you run a local reverse proxy like Caddy, configure it to route to `https://mylifebits.local`)*.

---

## Ingesting Your Google Takeout

You can import any part of your Google Takeout archive using `importer.py`. The importer automatically detects the file or archive type:

### 1. Location History Takeout
```bash
# Ingest an entire Takeout ZIP archive
uv run python importer.py /path/to/takeout-2024.zip

# Ingest an extracted Semantic Location History directory
uv run python importer.py /path/to/Takeout/"Location History (Timeline)"/

# Ingest a modern on-device Timeline export (Android / iOS)
uv run python importer.py /path/to/Timeline.json

# Ingest a GeoJSON export
uv run python importer.py /path/to/Location\ History.json
```

### 2. Google Photos Takeout
Import your Google Photos Takeout archives directly without needing to unzip 50GB archives to disk:
```bash
# Ingest Google Photos directly from a Takeout ZIP file
uv run python importer.py --photos /path/to/takeout-photos.zip

# Ingest an extracted Google Photos folder
uv run python importer.py --photos /path/to/Takeout/"Google Photos"/
```
*Photos are automatically indexed by timestamp and GPS location, generating lightweight WebP previews and linking directly to visited places on your timeline as visual evidence.*

### 3. Google Maps Reviews & Saved Places
```bash
# Ingest your Google Maps contributor reviews
uv run python importer.py --reviews /path/to/Takeout/"Maps (your places)"/Reviews.json

# Ingest your saved places (Want to go, Starred places, Favorites)
uv run python importer.py --saved /path/to/Takeout/"Maps (your places)"/"Saved Places.json"
```

### Command-Line Ingestion Reference
```bash
uv run python importer.py --help

usage: importer.py [-h] [--db DB] [--photos] [--reviews] [--saved]
                   [--include-records] [--stride STRIDE]
                   inputs [inputs ...]

Universal Google Takeout & Life Archive Importer (Location History, Google Photos, Maps Reviews, Saved Places).

positional arguments:
  inputs             Path(s) to Takeout archive (.zip), directory, Timeline JSON, Google Photos, Reviews, or GeoJSON

options:
  -h, --help         show this help message and exit
  --db DB            Target SQLite database path (default: TIMELINE_DB_PATH or ./timeline.db)
  --photos           Import input explicitly as Google Photos Takeout (directory or zip)
  --reviews          Import input explicitly as Google Maps Reviews (JSON or GeoJSON)
  --saved            Import input explicitly as Google Maps Saved Places (JSON)
  --include-records  Also stream and index raw GPS fixes from Records.json
  --stride STRIDE    Sampling stride when importing raw Records.json (default 1 = every record)
```

---

## Configuration

Settings can be customized via environment variables or a `.env` file in the root directory:

```bash
cp .env.example .env
```

| Variable | Default | Description |
| :--- | :--- | :--- |
| `TIMELINE_DB_PATH` | `timeline.db` | Path to the SQLite timeline database |
| `PORT` | `8000` | HTTP port for the web studio |
| `PHOTOS_ENABLED` | `false` | Enable local photo thumbnail and EXIF integration in web UI |
| `PHOTO_CACHE_DIR` | `data/cache/photos` | Directory for cached remote photo thumbnails |
| `PREVIEWS_DIR` | `data/previews` | Directory for local photo WebP thumbnails and day map diffs |
| `HTTP_USER_AGENT` | `MyLifeBits/1.0` | User-Agent string used for map tile and geocoding requests |

---

## Architecture & Data Model

For deep-dive documentation on the data model, database schemas, reverse-engineered Takeout specifications, and API contracts, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

### Core Database Entities

| Table | Description |
| :--- | :--- |
| `segments` | Continuous semantic timeline segments: visits (`segment_type=1`) and activities (`segment_type=2`). |
| `places` | Canonical place catalog storing coordinates, names, categories, ratings, and Google Place IDs (`ChIJ...`). |
| `days` | Aggregated daily rollups (date, total distance, segment counts, time zones). |
| `breadcrumbs` | High-frequency raw sensor telemetry (GPS coordinates, timestamps, accuracy). |
| `trips` | Multi-day travel groupings and destination clusters. |
| `photos` | Indexed photo metadata linking SHA-256 hashes, timestamps, locations, and tagged people. |
| `poi_reviews` | User's Google Maps contributor reviews with ratings, review text, and photo URLs. |
| `custom_labeled_places` | Custom starred, favorites, and saved places from Google Takeout. |

---

## Verification & Testing

The repository includes a comprehensive, hermetic test suite that runs without requiring any external or personal databases:

```bash
# Run unit tests (including Takeout, Photos, and Reviews ingestion)
uv run python -m unittest tests/test_clean_api.py tests/test_e2e_server.py tests/test_takeout_importer.py

# Run API contract auditor
uv run python scripts/audit_api_contracts.py
```

---

## License

This project is licensed under the [MIT License](LICENSE).
