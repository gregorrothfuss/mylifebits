# Google Maps On-Device Location History (ODLH) Architecture Post-Mortem
## Root Cause Analysis, Bytecode Reverse-Engineering, and Definitive Fixes

---

## 1. Executive Summary

This document details the exact technical root causes for past regressions in the Timeline migration and generation engine, the bytecode-level discoveries that resolved them, and the permanent architectural rules established to ensure deterministic fidelity.

---

## 2. Detailed Root Cause Analysis

### Issue 1: "On a tram" instead of "Subway" / Generic "Moving"
* **Symptom**: Timeline UI on Android displayed "On a tram" for transit trips on August 28, and generic "Moving" for cycling/walking on earlier days.
* **Root Cause**:
  1. Activity type integers were previously guessed rather than extracted from Google Maps APK bytecode. Enum integer `10` was assigned to `IN_SUBWAY`, but in Google Maps bytecode, `10` is explicitly `IN_TRAM`, whereas `IN_SUBWAY` is `9`.
  2. For activities showing "Moving", `ActivityCandidate` was placed at root Tag 3 rather than inside the nested `ActivityDetails` (Tag 2 inside Tag 3).
* **Decompiled Bytecode Proof (`com.google.android.apps.maps/classes.dex` @ `0x610e30` - `0x610f20`)**:
  ```smali
  const-string "FLYING"                 -> return 5  (0x05)
  const-string "CYCLING"                -> return 3  (0x03)
  const-string "WALKING"                -> return 2  (0x02)
  const-string "IN_TRAIN"               -> return 8  (0x08)
  const-string "IN_FERRY"               -> return 11 (0x0b)
  const-string "IN_SUBWAY"              -> return 9  (0x09)  <-- VERIFIED
  const-string "MOTORCYCLING"           -> return 30 (0x1e)
  const-string "IN_TRAM"                -> return 10 (0x0a)  <-- VERIFIED
  const-string "IN_PASSENGER_VEHICLE"   -> return 29 (0x1d) / 1
  const-string "RUNNING"                -> return 6  (0x06)
  const-string "IN_BUS"                 -> return 7  (0x07)
  ```

---

### Issue 2: Straight Lines Instead of Road-Snapped Polylines
* **Symptom**: Timeline map view displayed straight vector chords between start and destination coordinates rather than following streets and bridges.
* **Root Cause**:
  - `simplified_raw_path` (Tag 4 `0x22` inside `ActivityDetails`) was omitted in earlier protobuf builders. Without Tag 4 waypoints, Google Maps UI connects start and end points directly.
* **Permanent Fix**:
  - Integrated `road_snapper.py` (OSRM street network routing) to compute high-density road-following curves for all cycling, walking, and vehicular trips.
  - Serialized the coordinates into `WaypointListProto` (Tag 4 `0x22`) with `lat_e7`, `lng_e7`, and interpolated timestamps.

---

### Issue 3: Spurious Place Visits & Timezone Pollution on August 28
* **Symptom**: August 28 contained artificial 15-second place visits and European CET time offsets (`+60` min / `38 3c 40 3c`).
* **Root Cause**:
  - Older scripts injected 15-second place visits at Citi Bike docking stations (`qg_seg_cb_start_*` and `qg_seg_cb_end_*`).
  - Base database segments had European timezone tags from earlier synthesis steps.
* **Permanent Fix**:
  - Deleted all synthetic 15-second place visit records.
  - Normalized all US / NYC records across the database to EDT (`-240` minutes / `\x90\xfe\xff\xff\xff\xff\xff\xff\xff\x01`).

---

### Issue 4: Fallback "Place Visit" / "None" Place Labels
* **Symptom**: Visits in newly exported Takeout days showed generic "Place Visit" when place IDs were not in the local lookup table.
* **Root Cause**:
  - Raw Takeout exports for unconfirmed visits store `name: null` and `address: null`, providing only the Google `PlaceId` and `latLng`.
* **Permanent Fix**:
  - Built a comprehensive PlaceId resolver that cross-references all 10,998 indexed catalog places and geocoded locations, guaranteeing that every visit has a human-readable place name and address in `semantic_segment_table`, `places/2`, and `gmm_myplaces.db`.

---

## 3. Verified Activity Type Reference Table

| Activity Type Name | Protobuf Enum Integer | Google Maps Display Text | UI Icon |
| :--- | :---: | :--- | :---: |
| **`WALKING`** | `2` (`0x02`) | Walking | 🚶 |
| **`CYCLING`** | `3` (`0x03`) | Cycling | 🚲 |
| **`FLYING`** | `5` (`0x05`) | Flying | ✈️ |
| **`RUNNING`** | `6` (`0x06`) | Running | 🏃 |
| **`IN_BUS`** | `7` (`0x07`) | In bus | 🚌 |
| **`IN_TRAIN`** | `8` (`0x08`) | In train | 🚆 |
| **`IN_SUBWAY`** | `9` (`0x09`) | Subway | 🚇 |
| **`IN_TRAM`** | `10` (`0x0A`) | On a tram | 🚊 |
| **`IN_FERRY`** | `11` (`0x0B`) | In ferry | ⛴️ |
| **`IN_PASSENGER_VEHICLE`** | `1` / `29` (`0x1D`) | In passenger vehicle / Driving | 🚗 |
| **`MOTORCYCLING`** | `30` (`0x1E`) | Motorcycling | 🏍️ |

