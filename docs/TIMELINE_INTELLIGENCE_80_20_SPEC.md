# Specification: Location Timeline Intelligence (The 80/20 Version)

---

## 1. The Core Realization: Why the 100% Spec is Over-Engineered

The full-blown architecture (vector embeddings, SIMD dot products, 18-axis facet ontologies, on-device Gemini Nano batch daemons) introduces massive systems complexity for marginal user gain:

| Feature Dimension | The 100% "Full" Architecture | The 80/20 Architecture | Complexity Reduction |
| :--- | :--- | :--- | :---: |
| **Search** | Custom 256-d vector embeddings + SIMD dot product + FTS5 ranker | **Text-to-SQL / Filter Extraction** over existing SQLite | **−90%** |
| **Filters** | 5-axis, 18-facet taxonomy (pitstop, micromobility, accompanied, etc.) | **4 high-signal toggles** (Era, Haunts, Dwell, Category) | **−80%** |
| **Summaries** | 4-tier continuous background pipeline (Nano on-device + Flash async) | **On-demand Gemini Flash RAG** (send 30 JSON rows) | **−85%** |
| **Storage / Infra** | New vector tables, tokenizer extensions, background daemons | **2 columns in `places`** + **1 column in `trips`** | **−98%** |
| **Added Footprint** | ~10 MB binary indexes + background battery drain | **< 150 KB** SQLite metadata | **Zero overhead** |

---

## 2. Component 1: Universal Search via Text-to-Filter (No Vectors)

### 2.1. The Principle
Users rarely need semantic vector math for locations. When someone searches *"quiet coffee shop I worked from in Zurich in 2019"*, the search parameters are strictly structured:
* `City` = Zurich
* `Year` = 2019
* `Category` = Cafe / Coffee
* `Dwell` $\ge 60\text{ minutes}$

Instead of generating and maintaining fragile vector embeddings, the search box uses a single lightweight LLM prompt (or regex parser) to compile free-form user queries directly into standard SQLite parameters:

```python
# LLM Query Compiler Prompt (Gemini Flash / fast regex)
# Input: "places I worked from in Zurich during 2019"
# Output:
{
    "city": "Zurich",
    "year": 2019,
    "category": "Cafe",
    "min_dwell_minutes": 60,
    "keyword": None
}
```

### 2.2. The Single SQLite Query
The compiled filter runs directly against the existing database in $< 2\text{ ms}$:

```sql
SELECT place_id, name, address, category, visit_count, latest_visit_date, median_dwell_minutes
FROM places
WHERE (? IS NULL OR city LIKE ?)
  AND (? IS NULL OR strftime('%Y', latest_visit_date) = ?)
  AND (? IS NULL OR category = ?)
  AND (? IS NULL OR median_dwell_minutes >= ?)
  AND (? IS NULL OR name LIKE ? OR address LIKE ?)
ORDER BY visit_count DESC
LIMIT 50;
```

If the user types an exact venue name or street address, standard `LIKE '%...%'` (or built-in SQLite FTS) handles it instantaneously. Zero vector libraries, zero embedding drift.

---

## 3. Component 2: The 4 Filters That Actually Matter

Rather than 18 niche facets, 80% of human location browsing boils down to four questions:
1. **When was I there?** (Time / Era)
2. **Do I love this place, or was it a one-off?** (Cadence)
3. **How long did I stay?** (Dwell Depth)
4. **What kind of place is it?** (Category)

### 3.1. Schema Changes (Only 2 New Columns in `places`)
Run this single 1-second migration on `places`:

```sql
ALTER TABLE places ADD COLUMN latest_visit_date TEXT;
ALTER TABLE places ADD COLUMN median_dwell_minutes INTEGER DEFAULT 0;

-- Backfill in one pass from existing segments table:
UPDATE places SET
  latest_visit_date = (
    SELECT MAX(date) FROM segments WHERE segments.place_id = places.place_id
  ),
  median_dwell_minutes = (
    SELECT AVG(duration_seconds) / 60 FROM segments WHERE segments.place_id = places.place_id
  );

CREATE INDEX idx_places_filter_8020 ON places(category, latest_visit_date, median_dwell_minutes, visit_count);
```

### 3.2. The 4 UI Toggles

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│  ERA: [All Time ▼]   CADENCE: [All] [★ Haunts (5+)] [🌙 Dormant (>1y)]                 │
│  DWELL: [Any Dwell] [☕ Quick (<30m)] [💻 Deep (>1h)]   CATEGORY: [All ▼]               │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

* **Era / Year:** Dropdown populated from `SELECT DISTINCT substr(date, 1, 4) FROM segments` or user life periods (e.g. *2024*, *2019*, *Zurich Era*, *All Time*).
* **Cadence Toggle:**
  * `★ Haunts`: `visit_count >= 5`
  * `🌙 Dormant`: `visit_count >= 3 AND latest_visit_date < date('now', '-1 year')`
  * `✨ One-Offs`: `visit_count = 1`
* **Dwell Toggle:**
  * `Quick Stop`: `median_dwell_minutes <= 30` (coffee pick-ups, bakeries, errands).
  * `Deep Dwell`: `median_dwell_minutes >= 60` (working cafes, long dinners, museums).
* **Category:** Simple normalized dropdown (*Food & Drink*, *Coffee*, *Work / Coworking*, *Culture & Parks*, *Travel*).

---

## 4. Component 3: On-Demand LLM Summaries & Insights (RAG Without Vectors)

### 4.1. Trip & Vacation Summaries
Instead of continuous background workers, generate trip summaries **strictly on demand** when the user opens the Trips tab:

1. Query all visits and activities for the trip from SQLite:
   ```sql
   SELECT date, place_name, category, duration_seconds / 60 as dwell_mins, activity_type, distance_meters
   FROM segments
   WHERE date BETWEEN :trip_start AND :trip_end
   ORDER BY start_time_utc ASC;
   ```
2. Serialize into a compact ~2 KB text snippet.
3. Call Gemini Flash with a single prompt:
   > *"Summarize this 5-day trip into 2 crisp paragraphs: itinerary flow, key neighborhood hubs, standout meals/venues, and mobility style (walking vs. transit)."*
4. Cache the resulting markdown in a single column:
   ```sql
   ALTER TABLE trips ADD COLUMN summary_markdown TEXT;
   ```
5. Once generated, it loads instantaneously forever. Cost: ~$0.0001 per trip.

### 4.2. Daily Micro-Digest
In the day view card header, generate a 1-sentence narrative on demand (or during the daily clean pass):
* **Template-First Fallback (Zero LLM cost):**
  If no LLM call is desired, a simple Python rule produces clean summaries:
  `f"Active day in {city}: {round(total_km, 1)} km ({top_mode}). Visited {top_places}."`
  *Result:* *"Active day in SoHo: 8.4 km (Walking). Visited Ground Support Cafe, Buvette, and Washington Square Park."*
* **LLM Polish (Optional):** Send the 5 visit names to Gemini Flash for a conversational sentence.

### 4.3. "Ask My Timeline" (Natural Language Q&A)
To answer questions like *"What were my favorite restaurants in Tokyo?"* or *"How many times did I visit the gym in 2023?"*:
1. **Step 1 (SQL Retrieval):** Use LLM text-to-SQL or parametric filter to fetch top 30 candidate rows from SQLite.
2. **Step 2 (Answer Synthesis):** Pass the 30 rows directly into Gemini Flash as the prompt context.
3. **Step 3 (Display):** Render the direct conversational answer with clickable links to the matching days and places.

Zero vector databases. Zero chunking pipelines. 100% grounded in authentic SQLite rows.

---

## 5. Implementation Effort & Cost Comparison

| Dimension | The 100% Spec | The 80/20 Spec |
| :--- | :--- | :--- |
| **New Tables Required** | 4 (`places_fts`, `place_embeddings`, `place_intelligence_profile`, `summaries_cache`) | **0 new tables** (just 2 columns in `places`, 1 in `trips`) |
| **Lines of Python Backend** | ~950 lines (vector SIMD, tokenizer, daemons) | **~120 lines** (query builder + single Gemini helper) |
| **Lines of Frontend JS** | ~450 lines (complex facet matrix state) | **~75 lines** (4 simple dropdown/pill change listeners) |
| **Development Time** | 3–4 weeks | **1–2 days** |
| **Failure Modes** | Index desync, quantization errors, memory crashes | **None** (standard SQLite queries + standard REST call) |
| **Offline Reliability** | Requires heavy local vector model on phone | **100% local SQL filters work completely offline** |

---

## 6. The 80/20 Action Plan

1. **Step 1 (Database):** Add `latest_visit_date` and `median_dwell_minutes` to `places`. Backfill with one SQL query.
2. **Step 2 (API):** Update `api/routes/places.py` to accept `cadence` (`haunt`/`dormant`), `dwell` (`quick`/`deep`), and `year`.
3. **Step 3 (UI Toolbar):** Add the 4 filter controls to `static/index.html` above the places list.
4. **Step 4 (On-Demand Summary):** Add a `/api/trips/{id}/summary` endpoint calling Gemini Flash once and persisting the markdown.
