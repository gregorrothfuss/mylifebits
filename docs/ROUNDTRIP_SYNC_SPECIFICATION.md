# Engineering Specification: Safe Bi-Directional Timeline Round-Trip Pipeline
## Web UI Master $\rightleftharpoons$ Rooted Pixel 8 $\rightleftharpoons$ Google Cloud Backup $\rightleftharpoons$ Daily Driver Pixel 10

---

## 1. Architectural Principles & Problem Statement

### 1.1 The Operational Goal
Establish a 100% automated, zero-loss, bi-directional synchronization loop between the local Web Studio (`timeline_viewer.db`) and the user's everyday phone (**Pixel 10**, unrooted daily driver), using a rooted **Pixel 8** as a headless gateway:
1. **Forward Sync**: Master edits made in the local Web UI (curated visits, road-snapped curves, custom place names, historical restorations) are packaged into SQLite databases, injected into GMS Core on the Pixel 8, backed up to Google Cloud (E2EE), and imported on the Pixel 10.
2. **Reverse Sync**: Daily telemetry, raw sensor buffers (`rawSignals`), and newly inferred visits/activities recorded by the Pixel 10 are backed up to Google Cloud automatically, restored onto the rooted Pixel 8 headlessly, pulled directly via root ADB, and integrated into `timeline_viewer.db`.
3. **Zero Manual Steps on Daily Driver**: The Pixel 10 operates purely as a standard phone running Google Maps with background Cloud Backup. **No manual JSON exports, no settings menus, and no user intervention.**
4. **Zero-Guesswork Protobuf Integrity**: Hand-rolled Python Protobuf byte-packing (`bytearray() + \x08...`) is formally eliminated as an unsound dead end. Protobuf serialization is handled strictly via **Verbatim Authentic Donor Preservation** and **Native On-Device GMS Dalvik Execution**, verified by a pre-flight **Java Deserialization Smoke Gate**.

---

## 2. Root Cause Analysis: Why Hand-Rolled Reverse Engineering Failed

Forensic audit of previous deployment attempts revealed why synthetic databases suffered corruption, table wipes, and "Maps is offline" errors:

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                             WHY SYNTHETIC PROTOBUFS FAILED                                  │
├───────────────────────────────┬─────────────────────────────────────────────────────────────┤
│ 1. Brittle Byte Concatenation │ Hand-written Python encoders (e.g. surgical_roundtrip_deploy│
│                               │ .py) inverted tags (start_point as Tag 4 instead of Tag 1;  │
│                               │ int varint on Tag 1). GMS Core threw Java deserialization   │
│                               │ exceptions, corrupting the Room ORM transaction.            │
├───────────────────────────────┼─────────────────────────────────────────────────────────────┤
│ 2. Blind PlaceId Slicing      │ Slicing place_id[4:] naively corrupted 20-byte cell/fprint   │
│                               │ alignment, creating invalid FeatureIdProto structures.       │
├───────────────────────────────┼─────────────────────────────────────────────────────────────┤
│ 3. Room Schema Hash Reset     │ Room ORM verifies database schema against an internal hash. │
│                               │ Any discrepancy in column definitions or PRAGMA user_version│
│                               │ triggers fallbackToDestructiveMigration (wipes tables).     │
├───────────────────────────────┼─────────────────────────────────────────────────────────────┤
│ 4. Binder IPC 15.0s Timeout   │ Deserializing >24,000 synthetic protobufs sequentially on   │
│                               │ Binder threads exceeded Android's 15s deadline.             │
├───────────────────────────────┼─────────────────────────────────────────────────────────────┤
│ 5. Merge Overwrite Drift      │ Blindly merging raw phone inferences without interval locks │
│                               │ overwritten curated visits (e.g. fake multi-day Gene's stay)│
└───────────────────────────────┴─────────────────────────────────────────────────────────────┘
```

---

## 3. The Two Core Architectural Fixes

### Fix 1: Zero-Manual-Step Automated Cloud Backup Loop

The manual "Export Timeline data" in Android Settings is strictly quarantined as a debugging fallback. In production, the **Google Cloud Backup E2EE snapshot** is the transport mechanism in both directions:

```mermaid
flowchart TD
    subgraph Local_Workstation ["Local Workstation (Mac)"]
        MASTER_DB[("Master Database<br/>timeline_viewer.db<br/>87,536 Segs / 11,242 Places")]
        COMPILER["ODLH Compiler & Donor Engine<br/>(Verbatim Blobs + Surgical Patches)"]
        DIFF_AUDIT["Gate 1-6 Deep Verification Suite"]
        INGEST_ENG["Incremental Two-Way Ingestion<br/>(Protected Windows)"]
    end

    subgraph Pixel8_Gateway ["Pixel 8 Gateway (Rooted / Headless ADB)"]
        P8_SQL["Surgical SQL Injection<br/>(Quiescent GMS / Checked WAL)"]
        P8_GMS["GMS Core Service<br/>(odlh-storage.db, places/2)"]
        P8_BMGR["Automated Cloud Backup / Restore<br/>(bmgr / UI Automator)"]
        P8_EXTRACT["Headless Root Database Dump<br/>(su -c tar / adb pull)"]
    end

    subgraph Google_Cloud ["Google Cloud Infrastructure"]
        G_BACKUP[("Encrypted Location History<br/>E2EE Cloud Backup Snapshot")]
    end

    subgraph Pixel10_Prod ["Pixel 10 (Daily Driver / Unrooted)"]
        P10_RESTORE["Standard Google Cloud Restore<br/>(One-time or on-demand)"]
        P10_LIVE["Daily Driver Tracking<br/>(PulpInferenceService, rawSignals)"]
        P10_AUTO_BACKUP["Automatic Overnight Cloud Backup<br/>(Charging & Idle on Wi-Fi)"]
    end

    %% FORWARD SYNC
    MASTER_DB --> COMPILER
    COMPILER --> DIFF_AUDIT
    DIFF_AUDIT -->|"Deploy Verified DBs"| P8_SQL
    P8_SQL --> P8_GMS
    P8_GMS -->|"Trigger Cloud Backup"| P8_BMGR
    P8_BMGR -->|"Upload Encrypted Snapshot"| G_BACKUP
    G_BACKUP -->|"Download Snapshot"| P10_RESTORE

    %% REVERSE SYNC (AUTOMATED)
    P10_LIVE --> P10_AUTO_BACKUP
    P10_AUTO_BACKUP -->|"Nightly E2EE Backup"| G_BACKUP
    G_BACKUP -->|"Automated Restore on P8"| P8_BMGR
    P8_BMGR --> P8_GMS
    P8_GMS --> P8_EXTRACT
    P8_EXTRACT -->|"Automated ADB Pull"| INGEST_ENG
    INGEST_ENG -->|"Merge New Inferences & Sensors"| MASTER_DB
```

**Key Advantages:**
- **Zero user actions on Pixel 10**: The user never opens settings, never taps export, never connects cables.
- **Rooted automation on Pixel 8**: All tricky operations (stopping services, moving SQLite files, setting permissions, triggering backups, dumping databases) happen on the rooted Pixel 8 over Wireless ADB.

---

### Fix 2: Eliminating Hand-Rolled Protobuf Reverse Engineering

Instead of writing brittle Python byte concatenation (`bytearray() + \x08\x00...`), the system employs three robust, non-fragile mechanisms:

#### Strategy A: Verbatim Authentic Donor Preservation
- **80,593 baseline segments** in `odlh-storage.db` already have 100% authentic, byte-for-byte pristine protobuf blobs generated by Google's proprietary C++/Java nano-proto compiler.
- **Rule**: NEVER re-encode or synthesize authentic Google blobs. Store them and deploy them bit-for-bit verbatim.

#### Strategy B: Template-Based Binary Surgery (The Pristine Donor Pattern)
When an existing visit or activity is edited in the Web UI (e.g. updating coordinates or resolving a place ID):
- Do NOT build a new blob from scratch.
- Take an authentic Google donor blob from the baseline database.
- Parse the top-level wire tags using a generic wire parser (`parse_proto`).
- Keep all internal device metadata, sensor confidence tags, hierarchy tokens, and candidate lists intact.
- Surgically replace **only** the target primitive fields (e.g., `PointProto` lat/lng or `TimestampProto`), preserving Google's exact binary layout.

#### Strategy C: Native On-Device GMS Dalvik Execution Bridge
For newly inserted segments that have no donor blob:
- Execute a lightweight Java/Kotlin runner directly on the rooted Pixel 8 via `app_process`:
  ```bash
  export CLASSPATH=/data/app/.../com.google.android.gms.apk
  app_process /system/bin com.google.android.gms.location.reporting.ProtoSerializer ...
  ```
- Uses Google's **own compiled Java classes and setters** within the Android runtime to instantiate and serialize the Protobuf.
- **Result**: Zero reverse engineering. The serialized bytes are produced by Google's own compiled bytecode.

#### Strategy D: Mandatory On-Device Java Deserialization Gate
Before any candidate database is deployed to GMS or backed up to cloud:
- Run an on-device smoke test via `app_process` on Pixel 8.
- Iterate over 100% of protobuf blobs in `semantic_segment_table`.
- Invoke GMS Core's `SemanticSegmentRecord.parseFrom(blob)`.
- If GMS throws a single `InvalidProtocolBufferException` or `ArrayIndexOutOfBoundsException`, deployment is **hard-blocked**.

---

## 4. End-to-End Operational Workflow

### Phase 1: Local Master Curation & Pre-Flight Dominance Audit
1. Master database `timeline_viewer.db` contains 87,536 segments, 42,465 visits, 45,071 activities, 11,242 places, and 71,960 raw signals.
2. Pre-flight dominance auditor runs locally:
   - Command: `uv run python scripts/audit_strict_dominance.py`
   - Validates all 5 tiers: raw signal super-set, entity dominance, physics monotonicity (0 overlaps, 0 teleports, 0 midnight splits), visual isolation, and wire deserialization.

### Phase 2: Compilation of Synchronized ODLH Databases
The compilation pipeline generates five mutually-consistent files:
1. **`odlh-storage.db`**:
   - `PRAGMA user_version = 12`.
   - `PRAGMA journal_mode = WAL`.
   - Preserves authentic Google blobs; applies surgical template patches for edited visits.
   - `database_id = 1787254103124001536`, `obfuscated_gaia_id = '104819208193648646391'`.
2. **`aux-odlh-storage.db`**:
   - Preserves rolling 71,960 `rawSignals` buffer.
3. **`places/2`**:
   - Binary record array encoding all 11,242 catalog places.
4. **`gmm_myplaces.db`**:
   - Corpus 8 sync item records mapped to `3:<fprint>`.
5. **`gmm_sync.db`**:
   - Corpus 11 sync item records.

### Phase 3: Quiescent Staging & Root Injection on Pixel 8
1. Force-stop all target processes on Pixel 8:
   ```bash
   am force-stop com.google.android.apps.maps
   am force-stop com.google.android.gms
   am force-stop com.google.android.gms.persistent
   ```
2. Dynamically discover current UIDs:
   ```bash
   GMS_UID=$(stat -c "%u:%g" /data/data/com.google.android.gms/databases)
   GMM_UID=$(stat -c "%u:%g" /data/data/com.google.android.apps.maps/databases)
   ```
3. Execute atomic SQLite copy and clean WAL/SHM:
   ```bash
   su -c '
   cp /sdcard/staging/odlh-storage.db /data/data/com.google.android.gms/databases/odlh-storage.db
   cp /sdcard/staging/odlh-storage.db /data/data/com.google.android.apps.maps/databases/odlh-storage.db
   cp /sdcard/staging/aux-odlh-storage.db /data/data/com.google.android.gms/databases/aux-odlh-storage.db
   cp /sdcard/staging/gmm_myplaces.db /data/data/com.google.android.apps.maps/databases/gmm_myplaces.db
   cp /sdcard/staging/gmm_sync.db /data/data/com.google.android.apps.maps/databases/gmm_sync.db
   cp /sdcard/staging/places_2 /data/data/com.google.android.apps.maps/files/places/2
   
   rm -f /data/data/com.google.android.gms/databases/*-wal /data/data/com.google.android.gms/databases/*-shm
   rm -f /data/data/com.google.android.apps.maps/databases/*-wal /data/data/com.google.android.apps.maps/databases/*-shm

   chown -R $GMS_UID /data/data/com.google.android.gms/databases/odlh*
   chown -R $GMM_UID /data/data/com.google.android.apps.maps/databases/
   chown -R $GMM_UID /data/data/com.google.android.apps.maps/files/places/
   chmod 660 /data/data/com.google.android.gms/databases/odlh*
   chmod 660 /data/data/com.google.android.apps.maps/databases/*
   chmod 660 /data/data/com.google.android.apps.maps/files/places/2

   restorecon -Rv /data/data/com.google.android.gms/databases/
   restorecon -Rv /data/data/com.google.android.apps.maps/databases/
   restorecon -Rv /data/data/com.google.android.apps.maps/files/places/
   '
   ```

### Phase 4: On-Device Sanity Check & Cloud Backup Trigger
1. On Pixel 8, execute on-device SQLite check:
   - `PRAGMA integrity_check == ok`.
   - Row count matches candidate database exactly.
2. Execute Native Deserialization Smoke Gate: GMS Java runner validates 100% of blobs.
3. Trigger E2EE Cloud Backup via automated ADB:
   ```bash
   bmgr backupnow com.google.android.gms
   ```
4. Assert logcat for successful upload completion and zero `DEADLINE_EXCEEDED`.

### Phase 5: Pixel 10 (Daily Driver) Restore & Continuous Operation
1. The Pixel 10 imports the fresh backup snapshot from Google Cloud.
2. Because the snapshot was built from the verified database with exact protobuf alignment, Google Maps unrolls smoothly with zero crashes and zero "Maps is offline" banners.
3. The user uses the Pixel 10 daily. As they move, GMS Core infers new visits and activities, and collects raw sensor signals.
4. Overnight (charging + Wi-Fi + idle), GMS Core automatically uploads an updated E2EE Cloud Backup snapshot to Google Cloud.

### Phase 6: Automated Reverse Sync via Pixel 8 Gateway (No Pixel 10 Actions)
1. At scheduled sync intervals (or on demand), the workstation triggers the Pixel 8 over Wireless ADB:
   - Pixel 8 restores the latest Cloud Backup from Google Cloud via automated ADB intent/script.
2. Once restored, Pixel 8 extracts the updated SQLite databases directly:
   ```bash
   su -c 'tar -czf /sdcard/sync_extract.tar.gz /data/data/com.google.android.gms/databases/odlh-storage.db* /data/data/com.google.android.gms/databases/aux-odlh-storage.db*'
   adb pull /sdcard/sync_extract.tar.gz /local/sync_extract.tar.gz
   ```
3. The local workstation ingests the extracted `odlh-storage.db`:
   - Loads immutable protected windows (curated user edits, road-snapped curves, accepted fixes).
   - Identifies new visits and activities recorded by Pixel 10 ($t > t_{\text{last\_sync}}$).
   - Resolves new places and adds them to `places` catalog.
   - Appends new raw sensor buffer records to `raw_signals_buffer`.
   - Restitches timeline boundaries via `enforce_zero_gap_constraints`.

---

## 5. The Deep Testing & Verification Suite (The 6-Gate Architecture)

Every round-trip cycle must satisfy all six gates with explicit mathematical assertions:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        THE 6-GATE ROUND-TRIP VERIFICATION SUITE                        │
├────────┬─────────────────────────────┬──────────────────┬──────────────────────────────┤
│ Gate   │ Target Boundary             │ Verification Tool│ Pass Invariant               │
├────────┼─────────────────────────────┼──────────────────┼──────────────────────────────┤
│ Gate 1 │ Master Pre-Flight (Local)   │ DominanceAuditor │ 5 Tiers Pass (0 loss)        │
├────────┼─────────────────────────────┼──────────────────┼──────────────────────────────┤
│ Gate 2 │ SQLite & Place Parity       │ SchemaAuditor    │ user_version=12, Places=11242│
├────────┼─────────────────────────────┼──────────────────┼──────────────────────────────┤
│ Gate 3 │ On-Device Java Deserializer │ GmsJavaSmokeGate │ 0 Java parse exceptions      │
├────────┼─────────────────────────────┼──────────────────┼──────────────────────────────┤
│ Gate 4 │ Cloud Backup Upload         │ BackupInspector  │ E2EE upload status: SUCCESS  │
├────────┼─────────────────────────────┼──────────────────┼──────────────────────────────┤
│ Gate 5 │ Daily Driver Cloud Sync     │ LiveGmsMonitor   │ 0 crash, cards unroll        │
├────────┼─────────────────────────────┼──────────────────┼──────────────────────────────┤
│ Gate 6 │ Post-Round-Trip Parity Diff │ RoundtripDiff    │ 100% Segs, Visits, Pl. match │
└────────┴─────────────────────────────┴──────────────────┴──────────────────────────────┘
```

### Deep Parity Metrics Checked at Gate 6 (Post-Round-Trip Differential Diff)
When databases are extracted from Pixel 8 after a full round trip:

1. **Visit Count & Identity Parity**:
   $$\text{Visits}_{\text{Extracted}} \ge \text{Visits}_{\text{MasterPre}}$$
   Every single visit ID and timestamp range present in the master database must exist in the extracted database. Zero dropped visits.
2. **Segment Count Parity**:
   $$\text{Segments}_{\text{Extracted}} \ge \text{Segments}_{\text{MasterPre}}$$
   $\text{Count}(\text{Type 1}) \ge 42,465$, $\text{Count}(\text{Type 2}) \ge 45,071$, $\text{Count}(\text{Type 3}) \ge 25,020$.
3. **Place Catalog Parity**:
   $$\text{Places}_{\text{Master}} \subseteq \text{Places}_{\text{Extracted}}$$
   The number of distinct visited places must match or grow:
   $$\text{DistinctPlaces}(\text{Extracted}) \ge 7,740$$
4. **Protobuf Wire Integrity**:
   100% of blobs in the extracted database must parse cleanly through generic wire parsing without truncation or trailing byte warnings.
5. **Protected Edit Non-Regression**:
   $$\forall W \in \text{ProtectedWindows}, \quad \text{Entity}_{\text{Master}}(W) \equiv \text{Entity}_{\text{Extracted}}(W)$$
   Zero curated visits or accepted fix proposals altered by phone sync.

---

## 6. Implementation Milestones

| Milestone | Deliverable | Description |
| :--- | :--- | :--- |
| **M1: Donor & Surgery Engine** | `scripts/compile_odlh_master.py` | Preserves authentic Google blobs; surgical patch for edits. |
| **M2: On-Device Java Smoke Gate** | `scripts/test_on_device_deserialization.py` | Runs `app_process` Java deserialization gate on Pixel 8. |
| **M3: Staging & ADB Injector** | `scripts/deploy_to_pixel8_gateway.py` | Headless quiescence, dynamic UID, atomic SQLite deploy. |
| **M4: Automated Backup Trigger** | `scripts/trigger_pixel8_cloud_backup.py` | Automates cloud backup and verifies `SUCCESS` broadcast. |
| **M5: Automated Reverse Sync** | `scripts/sync_prod_via_pixel8_gateway.py` | Headlessly restores cloud backup on P8 and pulls SQLite. |
| **M6: Deep Parity Diff Auditor** | `scripts/audit_roundtrip_diff.py` | Asserts exact segment, visit, and place parity. |
