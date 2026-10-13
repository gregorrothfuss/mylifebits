# Specification: Location Timeline Durability, Storage Optimization, and Export

---

## 1. Data Loss Mechanisms (Current Architecture)

* **Catalog Coupling:** On-device records in `semantic_segment_table` persist only the 27-character `place_id` (Protobuf tag `354932271`). Place name, address, and category are queried dynamically. When backend POIs are removed, merged, or re-keyed, unresolved historical visits become unlabeled coordinates or are purged during client reconciliation.
* **Midnight Slicing:** Stays spanning 00:00:00 are stored as two separate records (`[T_start, 00:00]` and `[00:00, T_end]`), causing duplicate cards and reconciliation race conditions across timezone changes.
* **Telemetry Bloat:** Secondary candidate arrays and uncompressed float64 GPS point streams persist indefinitely, growing local databases up to 1.4 GB for active users.
* **Sync Overwrites:** Client-side sync lacks monotonic validation; local SQLite stores can be overwritten by empty or truncated states following device restores or GMSCore storage events.

---

## 2. Engineering Changes

### 2.1. Inline Place Metadata Caching
On visit finalization (inference settlement or user confirmation), write immutable place strings directly into the local SQLite row:
* `place_name` (VARCHAR)
* `street_address` (VARCHAR)
* `category` (VARCHAR)
* `feature_id_cell` (UINT64, 20-byte S2 alignment)
* `feature_id_fingerprint` (UINT64, 20-byte alignment)

If `place_id` fails backend resolution in the future, the client renders the cached strings. Visits are never deleted due to upstream catalog deprecations.

### 2.2. Continuous Overnight Model
Store overnight stays as a single contiguous interval `[T_start, T_end)`. UI calendar queries dynamically project intersections onto requested dates without splitting database rows.

### 2.3. Path Simplification & Quantization
Apply the Douglas-Peucker algorithm (ε = 5 m) to raw GPS tracks (`segment_type = 3`). Encode simplified coordinates using 5-decimal delta-encoded polylines (2.5 bytes/point vs. 16 bytes/point for float64 pairs).

### 2.4. Monotonic Sync Guard
Before applying remote sync payloads:
1. Snapshot local database: `VACUUM INTO 'odlh-storage.db.backup.<epoch>'`. Maintain a 3-generation rolling backup.
2. If incoming sync reduces total recorded visits or distance by > 1%, abort the transaction and quarantine the payload.

---

## 3. Retention & ML Training Lifecycle

Semantic ranking models use candidate sets (positive top candidate vs. rejected negative alternatives) for negative sampling. Because POI turnover and RF drift render spatial training pairs stale after 30–60 days, candidate sets are decoupled from long-term timeline storage:

| Tier | Window | Timeline Store (`odlh-storage.db`) | ML Training Pipeline |
| :--- | :--- | :--- | :--- |
| **Hot** | 0 ≤ T ≤ 30 days | Retain top candidate + up to 3 alternatives. Retain raw sensor fixes (`rawSignals`). | On-device federated learning extracts training pairs. |
| **Warm** | 31 ≤ T ≤ 60 days | **Compact visits to Top-1.** Inline frozen place strings. Purge `rawSignals`. | Buffer extracted training pairs in ephemeral ML store (`geller`). |
| **Cold** | T > 60 days | **Permanent state:** Top-1 frozen visit + simplified polylines only. | **Hard purge** of ephemeral ML training buffers. |

---

## 4. Current vs. Proposed Sizing

### 4.1. 10-Year Storage Footprint (Disk)

| User Tier | Activity Profile | Current (Uncompacted) | Proposed (Optimized) | Delta |
| :--- | :--- | :--- | :--- | :--- |
| **p50 (Median)** | 4 visits, 15 km / day | 58 MB | **11 MB** | **−81%** |
| **p90** | 12 visits, 60 km / day | 310 MB | **43 MB** | **−86%** |
| **p99** | 35 visits, 250 km / day | 1,420 MB | **171 MB** | **−88%** |

*Proposed footprint includes: static 30-day hot buffer + compacted lifelong visits with frozen metadata + ε = 5 m simplified polylines.*

### 4.2. Runtime Memory Footprint (RAM / GMSCore)

| Operational State | Current | Proposed | Delta |
| :--- | :--- | :--- | :--- |
| **Steady-State Tracking (p50)** | 1.2 MB | **0.8 MB** | −33% |
| **Steady-State Tracking (p99)** | 3.8 MB | **2.6 MB** | −32% |
| **Month View UI Query (p99)** | 12.4 MB | **8.5 MB** | −31% |
| **Compaction Job (Idle / Charging Only)** | N/A | **10.2 MB** | +10.2 MB (Transient) |

---

## 5. Takeout & Egress Specification

### 5.1. Archive Structure
```
Takeout/Timeline/
├── manifest.json            # SHA-256 checksums, temporal bounds, entity counts
├── timeline.geojson         # RFC 7946 GeoJSON (Visits + Snapped Routes)
└── routes_compact.bin       # Quantized high-rate GPS paths (Protobuf)
```

### 5.2. Payload Constraints
* **Omit Raw Sensor Logs:** Wi-Fi BSSID scans and cell tower logs are excluded from export.
* **Omit Candidate Arrays:** Export only confirmed or Top-1 resolved venues.
* **Inline Place Strings:** Every visit feature includes frozen place attributes:

```json
{
  "type": "Feature",
  "geometry": { "type": "Point", "coordinates": [-73.9851, 40.7488] },
  "properties": {
    "start": "2026-10-06T08:30:00Z",
    "end": "2026-10-06T10:15:30Z",
    "place_id": "ChIJ51cu8I1ZwokRBnrRwfd8tU8",
    "name": "Empire State Building",
    "address": "20 W 34th St., New York, NY",
    "category": "Tourist Attraction",
    "status": "CONFIRMED"
  }
}
```

* **Size Reduction:** Reduces a 15-year export payload from > 1.5 GB to < 80 MB.

### 5.3. Ingestion & Restoration Gate
* Implement client-side import matching on `Hash(start || end || place_id)`.
* Non-destructive merge: existing confirmed segments and manual edits supersede incoming raw heuristics; telemetry gaps are backfilled without overwriting existing verified days.
