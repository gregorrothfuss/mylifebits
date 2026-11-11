# Specification: Location Timeline Intelligence, LLM Insights, and Universal Search

---

## 1. Executive Summary & Value Proposition

Existing personal location systems (Google Maps Timeline, Apple Significant Locations, on-device ODLH) function as passive telemetry recorders: they answer *"At what coordinates was the device recorded?"* rather than *"What took place in the user's life, what patterns emerged, and how can those memories be recalled?"*

Native Google Maps Timeline exposes only rudimentary presentation:
* **Brittle Lexical Search:** Queries fail on semantic intent, colloquial descriptions, relative timeframes, or activity context (e.g. searching *"quiet coffee shops in Zurich where I worked in 2019"* yields zero results).
* **Flat, Unidimensional Filters:** Filter tools are restricted to coarse, static categories (*Food & Drink*, *Shopping*) and city pickers, ignoring dwell duration, recurrence cadence, transit access, social context, and life eras.
* **Trivial Presentation-Layer "Insights":** Current insights are limited to static monthly totals (e.g. *"You walked 18 km"*) with zero narrative synthesis, habit tracking, travel journals, or reflective value.

This specification defines the engineering architecture and product capabilities for a **semantic intelligence layer** running over the canonical timeline master database. It delivers three user-facing capabilities:
1. **Universal Semantic & Intent-Aware Search:** Hybrid retrieval uniting full-text search (BM25), dense on-device vector embeddings, and deterministic spatio-temporal query extraction.
2. **Multi-Dimensional Contextual Filtering:** High-performance, multi-axis faceted navigation spanning dwell duration, visit cadence (e.g. *Dormant Favorites*, *Regular Haunts*), life periods, and arrival travel modes.
3. **LLM Narrative Synthesis & Longitudinal Insights:** Hierarchical summarization generating automated daily micro-chronicles, cohesive multi-day travelogues, longitudinal habit evolution audits, and natural language memory recall (*"Ask My Timeline"*).

---

## 2. Universal Semantic & Context-Aware Search Architecture

```
User Query: "Quiet coffee shop I worked from in Zurich during autumn 2019"
                             │
                             ▼
     ┌───────────────────────────────────────────────┐
     │ 2.1 Intent & Spatio-Temporal Query Parser     │
     │ - Temporal Bounds: 2019-09-01 -> 2019-11-30   │
     │ - Spatial Anchor: Zurich (lat/lng bbox)       │
     │ - Category / Vibe: cafe / workspace / quiet   │
     │ - Duration Floor: dwell_seconds >= 3600       │
     └───────────────────────┬───────────────────────┘
                             │
             ┌───────────────┴───────────────┐
             ▼                               ▼
┌─────────────────────────┐     ┌─────────────────────────┐
│ Dense Semantic Vector   │     │ SQLite FTS5 Full-Text   │
│ On-device 256-d Gecko   │     │ BM25 Match on Names,    │
│ Cosine Sim (Vibe/Type)  │     │ Addresses, Reviews, OCR │
└────────────┬────────────┘     └────────────┬────────────┘
             │                               │
             └───────────────┬───────────────┘
                             ▼
     ┌───────────────────────────────────────────────┐
     │ 2.2 Hybrid Ranker & Spatio-Temporal Intersect │
     │ Score = 0.45*BM25 + 0.35*CosSim + 0.20*Context│
     └───────────────────────┬───────────────────────┘
                             │
                             ▼
     ┌───────────────────────────────────────────────┐
     │ Top Ranked Places with Corroborating Evidence │
     │ (Visits, Photos, Dwell Times, Review Excerpt) │
     └───────────────────────────────────────────────┘
```

### 2.1. Hybrid Retrieval Pipeline

Lexical matching alone fails because users recall subjective memories (*"the bookstore near the canal"*, *"where we had tapas after the bike ride"*), not exact POI strings. The search engine executes three concurrent stages:

1. **Deterministic Constraint Extraction (Rule & Slot Tagger):**
   * **Temporal:** Absolute dates (`"October 2021"`), relative dates (`"last summer"`, `"3 years ago"`), days of week (`"Sunday mornings"`), and named eras (`"when I lived in Zurich"` $\to$ mapped to `life_periods` table).
   * **Spatial:** Bounding boxes derived from city/country names, neighborhood polygons, or proximity to home/workplace coordinates.
   * **Physical Dwell & Mode:** Extraction of minimum dwell durations (`"worked from"` $\to \ge 90\text{ min}$; `"grabbed coffee"` $\to \le 20\text{ min}$) and arrival travel modes (`"biked to"`, `"walked to"`).

2. **Full-Text Lexical Search (FTS5):**
   Indexed over place names, normalized addresses, catalog categories, user-written Google Maps reviews, photo OCR strings, and user notes.

3. **Dense Semantic Vector Retrieval:**
   Each place in the catalog is indexed with an on-device 256-dimensional embedding vector representing its semantic profile (category, atmosphere, functional purpose, review sentiment, and surrounding context).

### 2.2. Scoring Formula
$$\text{Score}(P, q) = \alpha \cdot \text{NormBM25}(P_{\text{text}}, q_{\text{text}}) + \beta \cdot \text{CosineSim}(\mathbf{e}_P, \mathbf{e}_q) + \gamma \cdot \text{TemporalSpatialFilter}(P, q_{\text{bounds}})$$

Where:
* $\alpha = 0.45, \beta = 0.35, \gamma = 0.20$
* $\text{TemporalSpatialFilter}(P, q_{\text{bounds}}) \in \{0.0, 1.0\}$ acts as a hard filter when explicit bounds are detected, or a decay penalty based on distance when soft references are used.

### 2.3. SQLite Schema Extensions

```sql
-- Full-Text Search virtual table over places and personal notes
CREATE VIRTUAL TABLE places_fts USING fts5(
    place_id UNINDEXED,
    name,
    address,
    category,
    review_text,
    photo_scene_tags,
    tokenize = 'porter unicode61'
);

-- Dense embedding index for semantic vibe and conceptual retrieval
CREATE TABLE place_embeddings (
    place_id VARCHAR(64) PRIMARY KEY,
    embedding_dim INTEGER NOT NULL DEFAULT 256,
    embedding_bytes BLOB NOT NULL,       -- Quantized int8 vector (256 bytes)
    semantic_summary TEXT NOT NULL,      -- Canonical place descriptor string
    updated_at_utc TIMESTAMP NOT NULL
);

-- Spatio-temporal and contextual summary cache per place
CREATE TABLE place_intelligence_profile (
    place_id VARCHAR(64) PRIMARY KEY,
    first_visit_utc TIMESTAMP NOT NULL,
    latest_visit_utc TIMESTAMP NOT NULL,
    total_visits INTEGER NOT NULL DEFAULT 1,
    total_dwell_minutes INTEGER NOT NULL DEFAULT 0,
    median_dwell_minutes INTEGER NOT NULL DEFAULT 0,
    primary_arrival_mode VARCHAR(32) NOT NULL DEFAULT 'UNKNOWN',
    primary_time_of_day VARCHAR(16) NOT NULL, -- 'MORNING', 'AFTERNOON', 'EVENING', 'NIGHT'
    primary_life_period_id INTEGER,
    dominant_companion VARCHAR(64),
    photo_count INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(primary_life_period_id) REFERENCES life_periods(id)
);

CREATE INDEX idx_pip_dwell_visits ON place_intelligence_profile(total_visits, median_dwell_minutes);
CREATE INDEX idx_pip_period_time ON place_intelligence_profile(primary_life_period_id, primary_time_of_day);
```

---

## 3. Multi-Dimensional Contextual Filtering Engine

Existing UI dropdowns force users to guess static taxonomy labels (*"Establishment"*, *"Point of Interest"*). The proposed intelligence engine structures places and visits across **five orthogonal facet dimensions**:

### 3.1. The 5-Axis Facet Taxonomy

| Axis | Facet Identifier | Dynamic Criteria / Definition | User Query Value |
| :--- | :--- | :--- | :--- |
| **1. Cadence & Loyalty** | `REGULAR_HAUNT` | Visits $\ge 10$ across all time | Identify foundational life spots and daily staples. |
| | `DORMANT_FAVORITE` | Visits $\ge 5$, but zero visits in $>365\text{ days}$ | Rediscover forgotten spots worth revisiting. |
| | `ONE_OFF_GEM` | Visits $= 1$, user rating $\ge 4.5\bigstar$ or photo taken | Surface memorable stops during trips or explorations. |
| | `HIGH_FREQUENCY_ERA` | $\ge 3\text{ visits/month}$ during a specific life period | Reflect on past routines tied to old residences or jobs. |
| **2. Dwell & Depth** | `QUICK_PITSTOP` | Dwell duration $\le 15\text{ minutes}$ | Coffee pick-ups, convenience runs, dock transitions. |
| | `MEAL_OR_MEETING` | Dwell duration $45\text{--}90\text{ minutes}$ | Dinners, social lunches, professional meetings. |
| | `WORK_OR_STUDY` | Dwell duration $90\text{--}360\text{ minutes}$ | Cafes, libraries, coworking spaces used for deep work. |
| | `OVERNIGHT_STAY` | Contiguous stay across $02:00\text{--}05:00$ local time | Hotels, homes, friend stays (contiguous interval). |
| **3. Travel & Territory** | `HOME_TURF` | Physical distance $< 2.5\text{ km}$ from active residence | Neighborhood local businesses and everyday staples. |
| | `DOMESTIC_TRIP` | $> 100\text{ km}$ from active residence, same country | Weekend trips, regional getaways, domestic conferences. |
| | `INTERNATIONAL` | Country code $\ne$ residence country code at visit epoch | Overseas travel, vacations, foreign residency. |
| **4. Ingress Mobility** | `MICROMOBILITY` | Arrival preceded by `CYCLING`, `ON_BICYCLE`, or `SCOOTER` | Discover places accessible or frequented by bike. |
| | `TRANSIT_ACCESSED` | Arrival preceded by `SUBWAY`, `TRAIN`, `BUS`, or `FERRY` | Transit-convenient locations and stations. |
| | `PEDESTRIAN` | Arrival preceded strictly by `WALKING` ($> 500\text{ m}$) | Strollable destinations and foot-traffic favorites. |
| **5. Social & Multimodal** | `PHOTO_DOCUMENTED` | $\ge 1$ geocoded photo linked within visit timeframe | Places with verifiable visual memories. |
| | `ACCOMPANIED` | Face cluster detected in linked photos ($>1$ unique face) | Social gatherings, dinners with friends/family. |
| | `REVIEWED` | Matched with Google review text and numerical rating | Places with explicit personal written commentary. |

### 3.2. Query Execution & Performance SLA

To prevent UI hitching, all facet intersections must resolve within $< 8\text{ ms}$ over 15,000+ catalog places.

```sql
-- Example: Multi-axis filter query
-- "Dormant favorites in Brooklyn accessed by bike with dwell time > 1 hour"
SELECT p.place_id, p.name, p.address, p.visit_count, pip.latest_visit_utc, pip.median_dwell_minutes
FROM places p
JOIN place_intelligence_profile pip ON p.place_id = pip.place_id
WHERE p.city = 'New York'
  AND p.borough = 'Brooklyn'
  AND p.visit_count >= 5
  AND pip.latest_visit_utc < datetime('now', '-365 days')
  AND pip.median_dwell_minutes >= 60
  AND pip.primary_arrival_mode IN ('CYCLING', 'ON_BICYCLE')
ORDER BY p.visit_count DESC
LIMIT 50;
```

---

## 4. LLM Narrative Synthesis & Longitudinal Insights

### 4.1. Hierarchical Summarization Architecture

```
                          ┌───────────────────────────┐
                          │     User Life Dataset     │
                          │ (ODLH + Photos + Chrono)  │
                          └─────────────┬─────────────┘
                                        │
        ┌───────────────────────────────┼───────────────────────────────┐
        ▼                               ▼                               ▼
┌──────────────────┐          ┌──────────────────┐            ┌──────────────────┐
│   Tier 1: Daily  │          │  Tier 2: Trip    │            │  Tier 3: Era &   │
│   Micro-Digest   │          │   Chronicles     │            │  Habit Evolution │
├──────────────────┤          ├──────────────────┤            ├──────────────────┤
│ 2-sentence micro │          │ Multi-day story; │            │ Multi-year shift;│
│ summary on day   │          │ route narrative; │            │ commute changes; │
│ view card header │          │ photo highlights │            │ habit trends     │
├──────────────────┤          ├──────────────────┤            ├──────────────────┤
│ Gemini Nano      │          │ Gemini Flash     │            │ Gemini Flash     │
│ (On-Device / 1s) │          │ (Batch / 3s)     │            │ (Async / 5s)     │
└──────────────────┘          └──────────────────┘            └──────────────────┘
```

### 4.2. Narrative Capabilities

#### Capability A: Daily Micro-Digest
* **Product Behavior:** Instead of showing an empty card header or raw distance metrics, every day view renders an automated, 2-sentence narrative summary highlighting key visits, travel modes, and context.
* **Example Output:**
  > *"A brisk morning bike commute along the Hudson River to SoHo was followed by an afternoon working session at Ground Support Cafe. You closed the evening with dinner at Buvette in the West Village."*

#### Capability B: Trip Chronicles & Travelogues
* **Product Behavior:** When the user enters the Trips tab, multi-day itineraries are synthesized into rich, chronological travel chapters. The model contextualizes spatial leaps, culinary highlights, scenic routes, and companion moments based on photo EXIF clusters.
* **Structured Output Schema:**

```json
{
  "trip_id": "trip_2019_tokyo_kyoto",
  "title": "Autumn Journey Through Kanto & Kansai",
  "dates": "2019-10-12 to 2019-10-24",
  "total_km": 1420.5,
  "cities": ["Tokyo", "Hakone", "Kyoto", "Osaka"],
  "narrative_overview": "A 12-day exploration balancing high-speed Shinkansen transit with pedestrian wanders through Kyoto temples and late-night food exploration in Shinjuku.",
  "chapters": [
    {
      "day_range": "Day 1 - 4: Tokyo & Shinjuku",
      "summary": "Arrived via Haneda, establishing a base in Shinjuku. High pedestrian mobility (avg 18.2 km/day) centered around Meiji Jingu, Yanaka galleries, and late-night dining in Omoide Yokocho.",
      "highlight_places": ["ChIJ123... (Meiji Shrine)", "ChIJ456... (Fuglen Tokyo)"],
      "dominant_mode": "WALKING"
    },
    {
      "day_range": "Day 5 - 8: Hakone & Kyoto",
      "summary": "Tokaido Shinkansen transition to Kyoto with a stopover in Hakone. Transitioned to bicycle exploration along the Kamo River.",
      "highlight_places": ["ChIJ789... (Fushimi Inari)", "ChIJ012... (% Arabica Kyoto)"],
      "dominant_mode": "CYCLING"
    }
  ]
}
```

#### Capability C: Longitudinal Habit & Routine Shifts
* **Product Behavior:** Synthesizes multi-year changes across residential moves or career transitions:
  * **Commute Evolution:** *"In 2021, 82% of your weekday mobility was Citi Bike commuting (avg 14 mins). In 2024, your commute shifted to pedestrian strolls along Houston St (avg 22 mins)."*
  * **Productivity & Workspaces:** *"Your cafe dwell time dropped 40% after March 2020, shifting toward home office anchors, while outdoor park visits doubled."*
  * **Exploration Velocity:** *"During your 2018 Zurich period, you visited 4.2 new POIs per week; current NYC exploration averages 1.8 new venues per week."*

#### Capability D: "Ask My Timeline" (Conversational Memory Recall)
* **Product Behavior:** A natural language assistant embedded in the top search bar allowing complex biographical questions:
  * *"How many times have I been to Japan, and which cities have I visited?"*
  * *"Where did I have that fantastic sourdough pizza near Zurich HB?"*
  * *"Which coffee shop have I spent the most cumulative hours at over the last 10 years?"*

---

## 5. Storage Footprint, Compute Budget & Performance SLAs

The intelligence layer must maintain a strict on-device performance profile to avoid degrading battery life or storage constraints:

### 5.1. Storage Footprint (Lifelong Dataset: 15,000 Places, 45,000 Visits)

| Data Structure | Implementation | Current Baseline | Intelligence Layer | Delta |
| :--- | :--- | :--- | :--- | :--- |
| **Place Embeddings** | 256-dim int8 quantized vectors | $0\text{ MB}$ | **$3.84\text{ MB}$** | $+3.84\text{ MB}$ |
| **FTS5 Search Index** | SQLite FTS5 (Porter tokenizer) | $0\text{ MB}$ | **$2.45\text{ MB}$** | $+2.45\text{ MB}$ |
| **Intelligence Profiles** | Compact SQLite metrics table | $0\text{ MB}$ | **$1.12\text{ MB}$** | $+1.12\text{ MB}$ |
| **LLM Summaries Cache** | Pre-generated JSON strings | $0\text{ MB}$ | **$1.85\text{ MB}$** | $+1.85\text{ MB}$ |
| **Total Added Footprint** | All indexes and caches | — | **$9.26\text{ MB}$** | **$<10\text{ MB}$ total** |

*Note: The entire intelligence index ($9.26\text{ MB}$) is less than 1% of raw uncompacted GPS bloat, and provides instant offline search and filtering.*

### 5.2. Runtime Performance SLAs

| Operation | Target SLA (p50) | Target SLA (p99) | Execution Engine |
| :--- | :---: | :---: | :--- |
| **FTS5 Exact / Prefix Search** | **$1.2\text{ ms}$** | **$3.5\text{ ms}$** | SQLite FTS5 (Local B-Tree) |
| **Vector Dot-Product Ranking (15k places)** | **$4.8\text{ ms}$** | **$9.2\text{ ms}$** | SIMD int8 matrix multiplication (Accelerate / NEON) |
| **Multi-Axis Facet Filter Query** | **$2.1\text{ ms}$** | **$5.4\text{ ms}$** | Indexed SQLite scalar query |
| **Daily Micro-Digest Retrieval** | **$0.4\text{ ms}$** | **$1.1\text{ ms}$** | Key-value cache lookup (`daily_summaries`) |
| **Daily Micro-Digest Generation** | **$650\text{ ms}$** | **$1,200\text{ ms}$** | On-device Gemini Nano (Background idle / charging) |
| **Trip Chronicle Generation** | **$1.8\text{ s}$** | **$3.5\text{ s}$** | Gemini Flash (One-time batch / cached permanently) |

---

## 6. User Interface & Interaction Paradigms

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│  🔍 "quiet coffee shop with wifi in zurich during 2019"             [All Eras ▼] [✕]   │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  ⚡ Active Filters: [Zurich] [Work Dwell (>1.5h)] [2019 Era] [Cafe]    (+ Add Filter)  │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  FILTERS:                                                                              │
│  Cadence:   [All] [★ Regular Haunts] [🌙 Dormant Favorites] [✨ One-Off Gems]          │
│  Dwell:     [<15m Pitstop] [45-90m Meal] [● >90m Deep Work] [Overnight]               │
│  Mobility:  [🚲 Micromobility] [🚆 Transit] [🚶 Pedestrian]                           │
│  Social:    [📸 Has Photos] [👥 Accompanied] [⭐ Reviewed Only]                        │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  NARRATIVE INSIGHT:                                                                    │
│  "During Autumn 2019, you frequented 3 primary workspace cafes in Zurich. You logged   │
│   14 working sessions at Cafe Henrici (avg 2h 15m), usually arriving by bike."         │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  MATCHED PLACES (3):                                                                   │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │ ☕ Cafe Henrici · Niederdorfstrasse 1, Zurich               [14 Visits · 32.5h]   │  │
│  │ "Your top workspace cafe in Autumn 2019. 80% bike arrivals. Last: Nov 18, 2019"  │  │
│  ├──────────────────────────────────────────────────────────────────────────────────┤  │
│  │ ☕ MAME Cafe · Josefstrasse 160, Zurich                    [6 Visits · 11.2h]    │  │
│  │ "Preferred weekend espresso bar. High photo density. Last: Oct 29, 2019"         │  │
│  └──────────────────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### 6.1. Header Omnibox (Unified Natural Language & Facet Search)
* Single universal input supporting hybrid text, structured chips, and conversational prompts.
* Automatic chip promotion: typing `"in Zurich"` or `"in 2019"` automatically converts to filter badges `[City: Zurich]` and `[Year: 2019]`, while preserving remaining keywords for semantic vector ranking.

### 6.2. Places View Filter Drawer
* Collapsible, persistent facet drawer with real-time result counts badge updates on each pill (e.g. `[🌙 Dormant Favorites (42)]`, `[🚲 Micromobility (184)]`).
* Zero-result prevention: Facet counts dynamically grey out impossible combinations before selection.

### 6.3. Place Intelligence Cards
* Place cards report more than raw visit count: they display an automated **personal relationship summary**:
  * *"Your routine here: Tuesday mornings, 45-minute average dwell."*
  * *"Habit status: Dormant favorite (visited 28 times between 2018–2022; last visit 18 months ago)."*
  * *"Connected life era: SoHo Resident Era (2017–2021)."*

---

## 7. Implementation Roadmap & Milestones

| Milestone | Deliverable | Key Technical Artifacts | Exit Gate Criteria |
| :---: | :--- | :--- | :--- |
| **Phase 1** | **FTS5 & Profile Engine** | `places_fts` table, `place_intelligence_profile` table, SQLite triggers on visit edits. | Sub-5ms lexical search over 15k places; 100% catalog coverage. |
| **Phase 2** | **Multi-Axis Facet API & UI** | `/api/places` multi-filter endpoint (`cadence`, `dwell_tier`, `mobility`, `era`). | Web Studio UI filter pills functional with real-time count badges. |
| **Phase 3** | **On-Device Vector Embedding** | 256-d embedding generator, SIMD dot-product ranking function in Python/SQLite. | Top-5 semantic search accuracy $>90\%$ on conceptual test suite. |
| **Phase 4** | **LLM Summarization Engine** | `daily_summaries`, `trip_summaries` tables, Gemini Nano/Flash structured pipeline. | 100% of trips chaptered; zero hallucinated POIs; $<2\text{s}$ trip generation. |
| **Phase 5** | **Conversational UI & Omnibox** | Natural language query parser, conversational *"Ask My Timeline"* interface. | Complex queries (*"Where did I work in Zurich in 2019?"*) return exact venues. |
