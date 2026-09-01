# Vision & Data Architecture: Comprehensive Life Reconstruction

## 1. Executive Vision & Core Philosophy

This project reconstructs an entire human life's physical trajectory and semantic activity with mathematical, physical, and historical fidelity. 

The dataset and pipeline serve as a **high-fidelity ground truth corpus** designed for recursive refinement by current and future, increasingly capable AI models. Future models will ingest auxiliary multi-modal signals (such as Google Fit step counts, heart rates, speed distributions, historical transit schedules, and archival records) to further constrain path snappers, calibrate mode transitions, and resolve micro-dwell times.

To enable this continuous pretraining-like data improvement loop, our architecture strictly separates **immutable raw provenance** from **canonical clean state**, while enforcing a strict **lossless round-trip contract** with Google Maps Timeline.

---

## 2. Binding Architectural Principles

### Principle I: Immutable Raw Provenance Preservation (Layer 0)
- **Raw Data Invariance:** Original source artifacts (Google Takeout JSON dumps, raw GPS telemetry, Google Fit exports, check-in histories, manual chronologies) MUST NEVER be modified in place or lossily overwritten.
- **Rich Context Preservation:** Raw candidate arrays, semantic probabilities, raw sensor breadcrumbs, and ambiguous metadata are preserved in the raw archive for future archeological re-inference.

### Principle II: Canonical Clean Master State (Layer 1)
The active master database (`timeline_viewer.db` / canonical store) represents the physically validated, topologically continuous, and fully resolved truth. It enforces the following strict invariants:
1. **Zero Temporal Gaps:** No unrecorded gaps $>1\text{s}$ between consecutive segments.
2. **Zero Spatial Teleports:** Strict spatial continuity ($<300\text{m}$ endpoint-to-startpoint jump) across all transitions.
3. **Physical Velocity Bounds:** Activity speeds must match human physiology and modal constraints (e.g. walking 1.0\text{--}1.8\text{ m/s}$, cycling 3.0\text{--}8.0\text{ m/s}$, transit 5.0\text{--}25.0\text{ m/s}$).
4. **Discrete Micro-Interactions:** Transient physical interactions (e.g., Citi Bike unlock/docking) are strictly bounded (exact 15.0s visit duration, flanked by continuous walking legs).
5. **100% Place ID Resolution:** Every visit must resolve to a valid, non-null Place ID registered in the binary `places/2` and `places` catalog tables.

### Principle III: Lossless Round-Trip Compatibility (Layer 2)
Only cleaned, verified canonical data is compiled into Google Maps on-device runtime artifacts (`odlh-storage.db`, `places/2`, `gmm_myplaces.db`, `gmm_sync.db`, `aux-odlh-storage.db`).
- **The Round-Trip Invariant:**
  85671\text{Canonical Master (L1)} \xrightarrow{\text{Compile}} \text{ODLH SQLite / places/2 (L2)} \xrightarrow{\text{Device Sync \& Backup}} \text{Google Cloud}85671
  85671\text{Google Cloud} \xrightarrow{\text{Takeout / GMS Export}} \text{Clean JSON / SQLite} \xrightarrow{\text{Ingest}} \text{Canonical Master (L1)}85671
- Compilation must produce pure wire protobufs without proprietary client decoder rejection, ensuring that Google Maps UI Day View, Places Tab, Trips Tab, and Insights load instantaneously without timeouts or fallbacks.

### Principle IV: Recursive Verification & Active Place ID Tracking
Verification is an active, closed-loop debug process:
- **Place ID Telemetry:** Maintain active tracking of all Place IDs loaded in Google Maps Timeline.
- **Systemic Root-Cause Resolution:** If a Place ID or date fails to render, times out, or falls back to generic "Moving" / "Place Visit", the system must isolate the root cause (wire format, missing catalog entry, coordinate mismatch, or type-3 pollution), patch the compiler/catalog, and re-verify on device until 100% render without defects.

---

## 3. Multi-Layer Storage Architecture

```
+-----------------------------------------------------------------------------------+
| LAYER 0: RAW PROVENANCE STORE (Immutable)                                         |
| - Google Takeout JSON (2010 - 2026)                                               |
| - Google Fit Telemetry (Steps, Cadence, Distance)                                 |
| - Archival Lifelogs, Bangkok / Cambridge / Zurich Life Chronologies               |
| - Raw GPS Breadcrumbs & Candidate Probability Trees                               |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          v (Ingestion, Fusion & Snapping Engine)
+-----------------------------------------------------------------------------------+
| LAYER 1: CANONICAL MASTER STORE (timeline_viewer.db)                              |
| - Fully resolved, continuous, non-overlapping segments                            |
| - 100% Place ID indexed (11,000+ catalog POIs)                                    |
| - Street-snapped polylines (Ramer-Douglas-Peucker decimated)                       |
| - Standardized 15s micro-docking interactions                                      |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          v (Pure ODLH & Places Serializer)
+-----------------------------------------------------------------------------------+
| LAYER 2: CLIENT RUNTIME & ROUND-TRIP ARTIFACTS                                    |
| - odlh-storage.db (semantic_segment_table, 0 type-3 rows, flat sfixed32 protos)   |
| - places/2 (11,084 binary serialized PlaceProto records)                          |
| - aux-odlh-storage.db, gmm_myplaces.db, gmm_sync.db                               |
| - Deployed live to Google Maps / Google Play Services on Android                  |
+-----------------------------------------------------------------------------------+
```

---

## 4. Google Maps Timeline Wire Protocol Contract

To guarantee flawless on-device rendering and prevent client fallback to generic labels, the compiler enforces three mandatory wire-level rules:

1. **Native Flat Coordinate Encoding (`WaypointProto`):**
   - Tag 1 (`0x0D`): `sfixed32 lat_e7` (4 bytes little-endian).
   - Tag 2 (`0x15`): `sfixed32 lng_e7` (4 bytes little-endian).
   - Tag 3 (`0x18`): `int64 timestamp_ms` (varint).
   - Tag 4 (`0x25`): `float32 accuracy_meters` (4 bytes little-endian).
   - *Never encapsulate lat/lng inside a nested `0x0A` PointProto.*

2. **Zero `segment_type = 3` Timeline Insertion:**
   - Raw path segments (`segment_type = 3`) must never be marked `shown_in_timeline = 1`. All movement belongs exclusively in `segment_type = 2` (`ActivitySegment`) with embedded `simplified_raw_path`.

3. **Strict Candidate Ranking (`PlaceCandidateProto`):**
   - Every visit segment contains a primary candidate (Tag 4) with `fprint` matching MD5 hash of `place_id`, verified `cell_id`, and `semanticType = UNKNOWN` (0) or semantic classification.
   - Corresponding metadata must exist in `places/2` with matching `fprint` and `place_id`.

---

## 5. Continuous Improvement Lifecycle

1. **Data Ingestion:** Incorporate new Takeout JSON or historical spans into Layer 0.
2. **Topological Healing:** Chain coordinates, eliminate inter-segment gaps, and enforce 15s dock bounds.
3. **Polyline Snapping:** Interpolate high-resolution road/transit paths and apply RDP geometry optimization.
4. **Catalog Indexing:** Register all new Place IDs in `places` SQLite and `places/2` binary cache.
5. **ODLH Compilation:** Serialize pure SQLite and protobuf structures.
6. **Device Deployment & Verification:** Push to Android via ADB, launch Google Maps, and visually/programmatically audit Day View, Places Tab, and active paths.
7. **Local Version Control:** Commit all verified improvements under the Conventional Commits specification.
