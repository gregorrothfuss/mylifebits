# Agent Execution Contract (Python / Antigravity)

## 1. State Management & Context Hygiene (Strict JSON Protocol)

### Anti-Pollution & Log Offloading
- **Never stream raw execution logs > 25 lines into context.**
- Redirect all verbose output (tests, linters, server logs) directly to scratch files:
  `uv run pytest > .agent/scratch/pytest.log 2>&1`
- Read only the relevant failure slice using targeted extraction (`tail -n 25 .agent/scratch/pytest.log` or file inspection tools).
- Keep conversation turns strictly bounded to decisions, diffs, and exact error signatures.

### Mandatory State Tracking (`.agent/state.json`)
All multi-step tasks MUST maintain their active execution graph inside `.agent/state.json` adhering strictly to this schema:

```json
{
  "goal": "<One-sentence objective>",
  "active_step_id": 1,
  "steps": [
    {
      "id": 1,
      "description": "<Atomic action being executed>",
      "status": "in_progress"
    },
    {
      "id": 2,
      "description": "<Subsequent or refactor step verification>",
      "status": "pending"
    }
  ],
  "context_cache": {
    "target_files": ["src/module.py"],
    "test_files": ["tests/test_module.py"],
    "scratch_logs": [".agent/scratch/pytest.log"]
  }
}
```

### State Machine Enforcement Rules
1. **Pre-Execution Check:** Inspect `.agent/state.json` at the start of every turn before invoking any other tool.
2. **Atomic Transition:** Update `active_step_id` and mark the step `"status": "in_progress"` *before* modifying code or running heavy processes.
3. **Completion Verification:** Mark a step `"status": "completed"` ONLY after verifying changes with a clean linter/test exit code (`0`).
4. **Failure State:** If a step fails unexpectedly, set `"status": "failed"`, record the log path in `context_cache`, and do not proceed to dependent steps until resolved.

---

## 2. Local Version Control & Commit Protocol (Archaeology Standard)

### Commit Cadence & Atomic Changes
- **Commit on Every Verified Step:** Whenever a step in `.agent/state.json` transitions to `"completed"`, immediately stage the modified files and commit. Never batch multiple unrelated changes into one commit.
- **Explicit File Staging:** Stage files individually (`git add src/module.py tests/test_module.py`). NEVER run `git add .` or `git add -A`.
- **Clean Tree Invariant:** Before starting any new task or step, run `git status` to ensure a clean working tree.
- **Rollback Discipline:** If an experiment or implementation fails, do not patch over broken code with messy workarounds. Revert cleanly (`git checkout -- <files>` or `git restore <files>`) back to the last verified commit before attempting an alternate solution.

### Commit Message Specification
Commit messages must strictly follow the Conventional Commits format with a structured body designed for human review and future agent archaeology:

```text
<type>(<scope>): <imperative summary under 72 chars>

Why:
- Root cause, architectural intent, or requirement driving this change.
- Specific problem or bug being solved.

What:
- Key structural changes made (classes, functions, data flow).
- Any edge cases or trade-offs intentionally introduced.

Verification:
- Command: `uv run pytest tests/path/test_file.py -k "test_name"` (Exit 0)
- Command: `uv run ruff check && uv run mypy .` (Exit 0)

State-Step: <step_id from state.json>
```

**Allowed Types:**
- `feat`: New user-facing or system capability.
- `fix`: Bug fix, error resolution, or regression patch.
- `refactor`: Structural code change without behavior alteration.
- `test`: Adding or modifying test fixtures, mocks, or assertions.
- `chore`: Tooling, dependency updates, or configuration adjustments.

---

## 3. Runtime Environment & Toolchain
- **Environment Manager:** Use `uv` strictly. Never run bare `pip` or modify global interpreters.
  - Install dependencies: `uv sync`
  - Add dependency: `uv add <package>` (or `uv add --dev <package>`)
  - Run scripts: `uv run python <script.py>`
  - Run tests: `uv run pytest -v`
  - Run focused test: `uv run pytest -k "<test_name>" -s`
  - Linting & Formatting: `uv run ruff check --fix && uv run ruff format`
  - Static Type Analysis: `uv run mypy .`

---

## 4. Process Persistence & Long-Running Tasks
- **No Ephemeral Background Subshells:** Do not launch detached jobs using raw `&` or standalone `caffeinate`.
- **Persistent Workers:** For tasks running >30s (servers, watch modes, batch jobs), launch via `tmux` with a display/system sleep assertion:
  `tmux new-session -d -s worker "caffeinate -dims uv run python <entrypoint>"`
- **Verification:** Monitor status via `kill -0 <pid>` or `tmux capture-pane -pt worker`. Verify logs and exit codes on disk rather than assuming success.

---

## 5. Execution Boundaries & Anti-Laziness Directives

### Directives:
- **Zero Omission Policy:** NEVER output `# ... existing code ...`, `# TODO: implement`, or truncated placeholder blocks. Write complete, functional diffs or deterministic patches.
- **Read Before Write:** Inspect file contents, imports, and type signatures before patching. Never guess paths or interfaces.
- **Closed-Loop Verification:** Complete fixes must follow: *Inspect/Reproduce -> Minimal Fix -> Verify (`ruff` + `pytest`) -> Update `state.json` -> Atomic Git Commit*.

### ALWAYS:
- Include Python 3.10+ type annotations on all public functions.
- Prefer `pathlib.Path` over `os.path`.
- Handle exceptions explicitly; avoid bare `except:` statements.
- Clean up any spawned child processes or test artifacts before ending a task.

### NEVER:
- Commit secrets, credential files, `.env`, or `.agent/scratch/` contents.
- Modify files in `.venv/`, lockfiles manually, or cache directories (`__pycache__/`, `.pytest_cache/`).
- Commit unverified code with failing tests or lint errors.

---

## 6. Learned Invariants & Forbidden Patterns

### Explicit Negative Constraints (Derived from Git Failure Archaeology)

1. **Ground Truth Baseline Purity**:
   - **NEVER** query the modified master database (e.g., `timeline_viewer.db`) or inject synthetic cards/badges to render baseline ground truth; **always** read directly and unmodified from authentic baseline sources (`pixel10_export/Timeline-latest.json` or `scratch/original_gms_backup/.../odlh-storage.db`) to ensure 100% ground-truth baseline fidelity.

2. **Strict Dual-Source Asset Isolation**:
   - **NEVER** share, copy, or cross-paste screenshot crops, map viewports, polylines, or database cursors between baseline and master comparison panels; **always** isolate source assets completely so that the baseline panel renders strictly baseline artifacts and the master panel renders strictly master artifacts.

3. **Zero Presentation-Layer Card Fabrication**:
   - **NEVER** hardcode fake POI visits, synthetic gap cards, or candidate missing visit badges (e.g., `Ave A & 6th St`, `Prod Gap: 114 min`) in presentation scripts to explain unrecorded telemetry intervals; **always** preserve raw intervals faithfully as authentic unrecorded gaps or native moving segments.

4. **Multi-Factor Physical Validation for Travel Modes**:
   - **NEVER** assign or impute `FLYING` based solely on coarse distance thresholds (e.g., `dist > 50km`); **always** verify physical flight constraints first: distance $>300\text{ km}$, average speed $>250\text{ km/h}$, and spatial proximity ($<5\text{ km}$) to verified airport POIs. Ground transitions below $300\text{ km}$ must default to `IN_PASSENGER_VEHICLE`.

5. **Continuous Overnight Visit Integrity**:
   - **NEVER** split, duplicate, or truncate an overnight visit at midnight (00:00 local or UTC) into artificial "Left at 12:00 AM" / "Arrived at 12:00 AM" segments; **always** verify that overnight stays spanning across midnight remain a single contiguous visit entity across day transitions.

6. **Binary Protobuf & Feature ID Preservation**:
   - **NEVER** slice or arbitrarily offset binary Place ID or Feature ID strings (e.g., `place_id[4:]`) before decoding; **always** verify the exact 20-byte protobuf byte alignment against Google Maps cell ID and fingerprint specifications before applying transformations.

7. **Map Viewport and List Alignment**:
   - **NEVER** pair an unedited raw baseline map crop (containing raw path polylines or `~` moving markers) with a cleaned semantic card list; **always** verify that the map visual layer strictly corresponds to the underlying database entities shown in the card list below.

8. **Anti-Tautological Testing Mandate**:
   - **NEVER** write or commit unit tests that assert whatever structure the backend implementation happens to return (e.g. asserting `assertIn("days", data)` without validating whether `days` is a date-keyed dictionary or a flat list); **always** validate responses against explicit typed schemas and actual consumer code expectations (`static/app.js`).

9. **Zero Frontend Contract Drift & Strict Key/Type Preservation**:
   - **NEVER** alter, rename, or truncate API payload keys or data types (e.g., returning `[lat, lng]` coordinate arrays when the consumer accesses `.latitude` / `.longitude` object properties, or renaming `fixes` to `proposals`, or omitting facet counts like `counts.pending`); **always** maintain 100% key, field, and nested type parity with frontend consumers.

10. **Environment Isolation & Asset Proxy Awareness**:
    - **NEVER** deploy or background network-dependent services (e.g. image caching proxies, Google User Content photo proxying) in sandboxed subshells that silently fail or return 403/404; **always** assert network egress and verify external asset fetching end-to-end with verified network permissions (`BypassSandbox: true`).

11. **Strict Device Cloud Backup Isolation & Fresh GeoJSON Supremacy**:
    - **NEVER** treat cloud backup archives (`odlh-storage.db` from device backups) as authoritative ground truth over authentic raw client exports (`pixel10_export/Timeline-*.json` or official Google Takeout); **always** treat client GeoJSON exports as the unalterable ground-truth spine, enforce `has_snapped_path` non-interference rules, and quarantine cloud backup databases from overwriting verified pristine telemetry intervals.

12. **Dynamic Date Initialization & Pure Integer Date Stepping**:
    - **NEVER** hardcode static default dates (e.g. `"2026-08-20"`) or restrictive `max` attributes in web templates or frontend controllers, and **NEVER** use `new Date(dateStr).setDate(...)` for day navigation; **always** initialize dates dynamically from URL query parameters (`?date=`) falling back to the user's local date (`getLocalToday()`), perform day stepping using deterministic UTC integer date arithmetic (`stepDate(dateStr, delta)`), and register initial history state via `replaceState` to guarantee flawless browser Back/Forward navigation.

13. **Zero-Stub Polylines & Synchronized Activation Invariant**:
    - **NEVER** leave multi-point road polylines (JSON arrays with $\ge 3$ coordinates) with `has_snapped_path = 0` in database tables or diagnostics scorecards, and **NEVER** leave zero-span activity legs (`start == end`) when adjacent visits have distinct physical coordinates; **always** activate `has_snapped_path = 1` across 100% of valid road curves and propagate departure/arrival coordinates from adjacent visits to ensure continuous, gapless street geometries.

14. **Micro-Mobility Dock Reconciliation & Canonical Place Integrity**:
    - **NEVER** leave micro-mobility trip legs (`CYCLING`, `ON_BICYCLE`, `SCOOTER`) unflanked by verified origin and destination dock stops, and **NEVER** insert synthetic UUID place IDs (`citi_bike_<uuid>`) when canonical `ChIJ` place entities exist in the catalog; **always** reconcile dock stops ($\le 80\text{ m}$) against the canonical places catalog and link physical 15-second arrival/departure dock visits with authentic local timezone timestamps.

15. **Strict Typographic Contrast & Flexbox Truncation Integrity**:
    - **NEVER** use light text colors (e.g. `#f8fafc`, `#facc15`, light pastels, or unconstrained cyan) on white (`#ffffff` or `#f8f9fa`) card surfaces, and **NEVER** render unescaped text in HTML `title="..."` attributes or omit `min-width: 0; flex: 1;` on flexbox text truncation elements; **always** verify WCAG AA compliant text contrast ($\ge 4.5:1$), enforce `escapeHtml()` on all user-facing strings, and assign `min-width: 0; flex: 1;` with `flex-shrink: 0` on time labels to prevent typography clashing or truncation bugs.

16. **Zero Synthetic / Stale Proposal Invariant**:
    - **NEVER** insert, stage, or leave synthetic place IDs or fake placeholder entities (e.g. `citi_bike_<slug>`, `target_id = 0`) in fix proposal tables or place catalogs; **always** map physical station docks and stopovers directly to authentic canonical Google Maps `ChIJ` place entities with valid 20-byte cell/fingerprint encodings, and verify that 100% of candidate fix proposals target existing, valid segments.

17. **Strict Visit-Synchronized Place Facets & Zero-Visit Clutter Elimination**:
    - **NEVER** expose random unvisited category clusters (e.g. `airport`, `Transit`, `Leisure & Park`) or zero-visit place entities in default UI filter pills, dropdowns, or map point layers; **always** enforce `visit_count >= 1` default filtering across `/api/places` and `/api/places/map-points`, normalize raw categories into canonical taxonomies (`Travel & Transit`, `Arts & Entertainment`, `Food & Drink`), and recompute catalog `visit_count` aggregations strictly against authentic database visits. When a place card reports $N$ visits, **always** provide an exhaustive modal/list of all $N$ recorded visits with timestamps, durations, and jump buttons.

18. **Single Universal Search Architecture**:
    - **NEVER** fragment search inputs across tabs with separate, disconnected search inputs (e.g. separate places, trips, and header search boxes); **always** provide exactly 1 universal global search box (`#global-search-input`) in the top navigation header that searches holistically across days, months, places, countries, and categories, actively synchronizing results with whichever view or tab is active.

19. **Dynamic Temporal State & Zero Hardcoded Epoch Defaults**:
    - **NEVER** hardcode static past dates (e.g. `"2005-08-15"`, `"2026-08-19"`) into calendar matrices, date pickers, or jump buttons; **always** dynamically initialize views from URL query parameters (`?date=`) falling back to the user's local today (`getLocalToday()`), and wire all era jump buttons (including Today) with deterministic temporal arithmetic.

---

## 7. Full-Life Multi-Source Reconstruction & Production vs. Test Visual Diff Standard

### Strategic Goal: Lifelong Dataset Bootstrap (1976 – Present)
The central objective of this system is the complete, high-fidelity digital reconstruction of every single day of the user's life. Rather than relying on a single fallible telemetry stream, the timeline is bootstrapped and corroborated across the user's entire multi-source digital footprint:
1. **Historical Semantic Location Takeout**: Full multi-year archives (2008–2024, e.g. `lh-20241129T224901Z-001.zip`) preserving pre-deletion visits, raw GPS paths, and deprecated Place IDs before on-device FID purging occurred.
2. **Geocoded Photos & EXIF Metadata**: Spatial-temporal coordinates, camera timestamps, and visual evidence extracted from photo archives to anchor physical presence during gaps.
3. **Search & Web History**: Search queries, Google Maps lookups, navigation directions, and browsing signals.
4. **Communications Archives**: Google Chat logs (83k+ messages with venue shares), Gmail mbox (160k+ emails, reservation confirmations, flight tickets, receipts), and legacy mail archives.
5. **Transit & Micro-Mobility Logs**: Complete Citi Bike ride archives, Lyft records, and flight itineraries.
6. **Financial Transaction Records**: Timestamped credit card/bank ledgers (`general-ledger_*.csv`, `cct-*.zip`) establishing commercial venue visits.
7. **Social & Historical Check-ins**: Plazes check-ins (`plazes.zip`), Google Maps reviews (`google_contributor_reviews.json`), and saved place lists.
8. **Chronological Spine**: Historical residences and workplace anchors (`synthetic_life_chronology.md`).

### Full-Source Reverse Engineering Protocol (Maps & GMSCore)
To ensure the reconstructed timeline faithfully matches native Google Maps Timeline behavior, agents must utilize full-source decompilation and Dalvik/DEX reverse engineering of `gmm_apk/base.apk`, `gms_apk/base.apk`, and `split_MapsDynamite.apk`:
- **Data Model & Schema Parity**: Extract authoritative SQLite schemas (`odlh-storage.db`, `semantic_location_state`, `geller_metadata`, `edited_segment_table`) and exact protobuf wire field tags directly from decompiled source.
- **FID Deletion & Deprecation Semantics**: Reverse engineer client/service logic governing place deprecation, FID deletion handling, unconfirmed place generation, and candidate generation to understand why Google deleted visits instead of marking places `PERMANENTLY_CLOSED`.
- **Render Engine Reverse Engineering**: Reverse engineer Google Maps Timeline rendering pipelines to ensure that simulated bottom-sheet card unrolling, polyline rendering, and travel mode formatting match production bit-for-bit.

### Mandatory Production vs. Test Visual & Data Diff Standard
Data bootstrap and timeline repair operations must never be committed without verifiable, side-by-side proof:
1. **Automated Dual-Source Visual Diff**:
   - Every modified day must generate a side-by-side visual comparison image: **PROD BASELINE** (untouched authentic device/takeout source) vs. **TEST MASTER** (reconstructed/repaired timeline).
   - Strict dual-source isolation: the test panel must reflect actual database/rendering state without borrowing crops, markers, or polylines from the baseline panel.
2. **Comprehensive Data Diff**:
   - Accompany visual diffs with explicit field-by-field diff audits (Visits, Activities, Gaps, Coordinates, Timestamps, Duration, Distance, Place IDs/FIDs).
3. **Evidence-Based Provenance Tracking**:
   - Every restored or inserted visit must have an immutable audit trail documenting its corroborating digital life source (Photo EXIF, Takeout, Mbox, Chat, etc.) and the root cause of its original absence (e.g. FID deletion by Google Maps).

---

## 8. Zero-Loss Production Round-Trip Standard & Strict Dominance Invariant

### Absolute Gate: "Strictly Better Proven at All Levels"
No deployment or round-trip of reconstructed timeline data back to the production device (`Pixel 10`) or Google Cloud Backup is permitted until **data loss is 100% ruled out** and the candidate master database is mathematically and empirically proven to be **strictly better (Pareto dominant)** than production across all five verification tiers:

1. **Tier 1: Telemetry & Raw Signal Super-Set Invariant (Zero Signal Loss)**:
   - **NEVER** drop, compress, truncate, or overwrite the rolling 30-day raw sensor buffer (`rawSignals`: 71,960+ Wi-Fi scans, cell fixes, GPS fixes, sensor samples) or the multi-year raw GPS path segments (`segment_type = 3` in `semantic_segment_table`).
   - The candidate master timeline must contain $\ge 100\%$ of production raw signals. All raw telemetry from prod must be preserved bit-for-bit.

2. **Tier 2: Semantic Entity Dominance (No Unexplained Omissions)**:
   - Every authentic production visit and activity must be strictly accounted for. The candidate master entity set must satisfy:
     $$\text{Visits}_{\text{Master}} \supseteq \text{Visits}_{\text{ProdValid}}$$
   - Any removal or boundary adjustment of a production entity must be mathematically proven as an anomaly fix (e.g. eliminating an impossible teleport, merging a midnight-split visit) and accompanied by an automated, immutable audit log citing the exact reason and corroborating evidence.
   - 100% of Place IDs and Feature IDs must preserve full 20-byte cell/fingerprint decoding integrity.

3. **Tier 3: Spatio-Temporal Monotonicity & Physics Consistency**:
   - The candidate timeline must have:
     * **0 temporal overlaps** (no segment begins before the preceding segment finishes).
     * **0 unhandled teleports** (no spatial jump $>300\text{ m}$ between adjacent segments without an explicit, physically valid transition leg).
     * **0 midnight splits** (overnight stays across 00:00 remain single contiguous visit entities).
     * **100% physical velocity compliance** (no `FLYING` without distance $>300\text{ km}$, speed $>250\text{ km/h}$, and airport anchors; ground movements match realistic road/rail speeds).

4. **Tier 4: Visual Dominance & Full-Scroll Equivalence**:
   - Automated side-by-side visual diffs across 100% of affected days must visually prove that the test master timeline renders cleanly without missing cards, truncated bottom sheets, clipped titles, or broken route polylines.
   - Test rendering must look identical to or strictly cleaner than production Google Maps Timeline.

5. **Tier 5: Wire-Level Binary Deserialization & On-Device Smoke Gate**:
   - `PRAGMA integrity_check` on all databases (`odlh-storage.db`, `portable_geller_*.db`, `aux-odlh-storage.db`) must return `ok`.
   - 100% of protobuf blobs in `semantic_segment_table` must deserialize cleanly through standard Google Maps / GMS Protobuf parsers with zero unrecognized tag drops or byte truncations.
   - The master database must first be deployed to the rooted `Pixel 8` and pass live UI smoke tests (opening Google Maps Timeline, navigating days, verifying bottom sheet unrolling, and zero GMS crashes) *before* triggering E2EE cloud backup to production.

---

## 9. Web Server, REST API & Full-Stack Consumer Contract Verification Standard

### Strategic Goal: Zero Frontend-Backend Desync & Strict Contract Compliance
Local web studios and viewer backends (`server.py`, `api/`) are first-class production components. Server code refactoring or feature additions must never break frontend consumers (`static/app.js`, `static/index.html`). To permanently eliminate blind spot regressions and tautological tests, all changes must pass this 4-tier contract verification gate:

### Mandatory 4-Tier Web Verification Gate

1. **Tier 1: Static Route & Field Coverage Gate**:
   - **Command:** `uv run python scripts/audit_api_contracts.py` (Must exit `0`).
   - 100% of `/api/` fetch routes called in `static/app.js` must be registered in `api.router`.
   - Any missing endpoint or misspelled route fails the gate immediately.

2. **Tier 2: Typed Consumer Contract & Schema Assertion Gate**:
   - All server response payloads must strictly conform to typed schemas in `api/schemas.py`.
   - **Object vs. Array Invariant:** Endpoints consumed as objects (e.g. `/api/places/map-points` expecting `{latitude, longitude, name}`) must **never** return raw coordinate tuples (`[lat, lng]`) that trigger browser `TypeError`s.
   - **Dictionary vs. List Invariant:** Multi-day matrix endpoints (e.g. `/api/calendar-range`) must return dictionaries indexed by date string (`days[dateStr]`), not flat lists.
   - **Facet Counts Invariant:** Endpoints providing status filters (e.g. `/api/fixes`) must return complete facet count objects (`counts: {pending, accepted, rejected, total}`) preventing `undefined` UI badge interpolations.

3. **Tier 3: End-to-End HTTP Wire Integration Gate**:
   - **Commands:**
     * `uv run python -m unittest tests/test_e2e_server.py` (Must exit `0`).
     * `uv run python -m unittest tests/test_clean_api.py` (Must exit `0`).
   - Tests must exercise full HTTP/1.1 wire parsing, headers, routing, static asset delivery (`/`, `/index.html`, `/app.js`, `/style.css`), gzip compression, and database mutations (segment CRUD, fix apply/reject).

4. **Tier 4: Asset Proxy & Network Egress Smoke Gate**:
   - When running services proxying remote assets (e.g. Google User Content `/api/photo`), the service must be launched with network egress permissions (`BypassSandbox: true`).
   - The photo proxy must verify HTTP 200 delivery, image header validation (`image/jpeg`), and local disk caching under `~/.gregor_mylifebits/photo_cache/`.

### Mandatory Pre-Commit Checklist for Web & API Changes
No commit modifying `server.py`, `api/`, `static/`, or related scripts is permitted without verifying:
1. `uv run python scripts/audit_api_contracts.py` (Exit 0)
2. `uv run python -m unittest tests/test_e2e_server.py` (Exit 0)
3. `uv run python -m unittest tests/test_clean_api.py` (Exit 0)
4. `uv run python -m py_compile api/*.py api/routes/*.py server.py` (Exit 0)