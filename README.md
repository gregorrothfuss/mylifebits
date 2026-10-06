# MyLifeBits: Personal Location Timeline & Life Archive

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

A privacy-first, zero-telemetry personal location history viewer, Google Takeout ingestion engine, and timeline repair studio.

Store decades of your physical movements locally in a clean, queryable SQLite database. Browse and inspect every day of your life through a responsive web interface with map trajectories, activity breakdowns, trip clustering, and place catalogs.

---

## Highlights

- **Universal Google Takeout Ingestion**:
  - Classic Takeout Archives (`.zip` containing monthly `timelineObjects` JSON files from 2008–2024).
  - Unzipped Takeout directories (`Semantic Location History/YYYY/YYYY_MONTH.json`).
  - Modern on-device JSON (`Timeline.json` from Android/Pixel Takeout exports).
  - Standard GeoJSON FeatureCollections (`Location History.json`).
  - Raw GPS breadcrumbs (`Records.json`).
- **Interactive Web Studio**:
  - Full-fidelity daily timeline view with interactive Leaflet map and bottom-sheet segment cards.
  - Multi-year calendar heatmap with instant date navigation and day-to-day scrubbing.
  - Places catalog with category filtering, canonical taxonomy normalization, and visit history.
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

You can import your personal Google Takeout data using `importer.py`. The importer automatically detects the file format:

### Option A: Takeout ZIP Archive
Import your downloaded Takeout `.zip` directly without manual unzipping:
```bash
uv run python importer.py /path/to/takeout-2024.zip
```

### Option B: Unzipped Takeout Directory
If you have already extracted your Takeout folder:
```bash
uv run python importer.py /path/to/Takeout/"Location History (Timeline)"/
```

### Option C: Modern On-Device Timeline Export
If you exported your timeline directly from Google Maps on Android / iOS:
```bash
uv run python importer.py /path/to/Timeline.json
```

### Option D: GeoJSON FeatureCollection
```bash
uv run python importer.py /path/to/Location\ History.json
```

### Command-Line Ingestion Flags
```bash
uv run python importer.py --help

usage: importer.py [-h] [--db DB] [--source SOURCE] path

Import location history data (Google Takeout, on-device exports, GeoJSON) into SQLite.

positional arguments:
  path             Path to Takeout zip, directory, or JSON/GeoJSON file.

options:
  -h, --help       show this help message and exit
  --db DB          Path to target SQLite database (default: timeline.db or TIMELINE_DB_PATH).
  --source SOURCE  Label for data source provenance (e.g., 'takeout_2024').
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
| `PHOTOS_ENABLED` | `false` | Enable local photo thumbnail and EXIF integration |
| `PHOTO_CACHE_DIR` | `data/cache/photos` | Directory for cached photo thumbnails |
| `PREVIEWS_DIR` | `data/previews` | Directory for day map visual diffs and previews |
| `HTTP_USER_AGENT` | `MyLifeBits/1.0` | User-Agent string used for map tile and geocoding requests |

---

## Architecture & Data Model

For deep-dive documentation on the data model, database schemas, reverse-engineered Takeout specifications, and API contracts, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

### Core Database Entities

| Table | Description |
| :--- | :--- |
| `segments` | Continuous semantic timeline segments: visits (`segment_type=1`) and activities (`segment_type=2`). |
| `places` | Canonical place catalog storing coordinates, names, categories, and Google Place IDs (`ChIJ...`). |
| `days` | Aggregated daily rollups (date, total distance, segment counts, time zones). |
| `breadcrumbs` | High-frequency raw sensor telemetry (GPS coordinates, timestamps, accuracy). |
| `trips` | Multi-day travel groupings and destination clusters. |

---

## Verification & Testing

The repository includes a comprehensive, hermetic test suite that runs without requiring any external or personal databases:

```bash
# Run unit tests
uv run python -m unittest tests/test_clean_api.py tests/test_e2e_server.py tests/test_takeout_importer.py

# Run API contract auditor
uv run python scripts/audit_api_contracts.py
```

---

## License

This project is licensed under the [MIT License](LICENSE).
