/**
 * Standalone Timeline Studio - Interactive Frontend Controller
 * Supporting Categories, City Clustering, and Google Contributor Reviews.
 */

document.addEventListener("DOMContentLoaded", () => {
  function getLocalToday() {
    const d = new Date();
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  function stepDate(dateStr, deltaDays) {
    if (!dateStr || !dateStr.includes('-')) return dateStr;
    const parts = dateStr.split('-').map(Number);
    if (parts.length !== 3 || isNaN(parts[0]) || isNaN(parts[1]) || isNaN(parts[2])) return dateStr;
    const dt = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2] + deltaDays));
    return dt.toISOString().slice(0, 10);
  }

  // App State
  let currentDate = getLocalToday();
  let currentCategory = "ALL";
  let currentCity = "ALL";
  let reviewedOnly = false;
  let currentSort = "visits";

  const urlDate = new URLSearchParams(window.location.search).get("date");
  if (urlDate) {
    currentDate = urlDate;
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
  window.escapeHtml = escapeHtml;

  function getPhotoUrl(url, size = 400) {
    if (!url) return '';
    if (url.startsWith('/api/photo')) return url;
    return `/api/photo?url=${encodeURIComponent(url)}&size=${size}`;
  }
  window.getPhotoUrl = getPhotoUrl;

  function setElText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  function format24hTime(isoStr, epochSec) {
    if (isoStr && isoStr.length >= 16) {
      return isoStr.slice(11, 16);
    }
    if (epochSec) {
      const d = new Date(epochSec * 1000);
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
    }
    return "--:--";
  }

  function formatEventTime(isoStart, isoEnd, startTs, endTs, localStart, localEnd) {
    if (localStart && localEnd && localStart !== "--:--") {
      return `${localStart} – ${localEnd}`;
    }
    const t1 = format24hTime(isoStart, startTs);
    const t2 = format24hTime(isoEnd, endTs);
    return `${t1} – ${t2}`;
  }

  let map = null;
  let heatMap = null;
  let heatLayer = null;
  let placesMap = null;
  let placesCanvasRenderer = null;
  let placesLayerGroup = L.layerGroup();
  let allPlacesMapData = [];
  let showRawSignals = false;

  // Map Layer Groups
  let visitLayerGroup = L.layerGroup();
  let routeLayerGroup = L.layerGroup();
  let rawLayerGroup = L.layerGroup();
  let gapLayerGroup = L.layerGroup();
  let segmentLayerMap = new Map();

  // Color mapping by transport mode
  const ACTIVITY_COLORS = {
    "IN_PASSENGER_VEHICLE": "#8b5cf6",
    "IN_BUS": "#a855f7",
    "IN_TAXI": "#c084fc",
    "WALKING": "#10b981",
    "ON_FOOT": "#10b981",
    "RUNNING": "#059669",
    "CYCLING": "#f59e0b",
    "IN_SUBWAY": "#06b6d4",
    "IN_TRAIN": "#0284c7",
    "IN_TRAM": "#38bdf8",
    "IN_FERRY": "#0ea5e9",
    "BOATING": "#0284c7",
    "FLYING": "#ec4899",
    "HIKING": "#84cc16",
    "IN_GONDOLA_LIFT": "#e11d48",
    "SNOWSHOEING": "#38bdf8",
    "KAYAKING": "#0284c7",
    "SWIMMING": "#06b6d4",
    "SLEDDING": "#60a5fa",
    "SAILING": "#0284c7",
    "PARAGLIDING": "#f43f5e",
    "KITESURFING": "#0ea5e9",
    "IN_FUNICULAR": "#6366f1",
    "DEFAULT": "#3b82f6"
  };

  const ACTIVITY_ICONS = {
    "IN_PASSENGER_VEHICLE": "fa-car",
    "IN_BUS": "fa-bus",
    "IN_TAXI": "fa-taxi",
    "WALKING": "fa-person-walking",
    "ON_FOOT": "fa-person-walking",
    "RUNNING": "fa-person-running",
    "CYCLING": "fa-bicycle",
    "IN_SUBWAY": "fa-train-subway",
    "IN_TRAIN": "fa-train",
    "IN_TRAM": "fa-train-tram",
    "IN_FERRY": "fa-ferry",
    "BOATING": "fa-sailboat",
    "FLYING": "fa-plane",
    "HIKING": "fa-person-hiking",
    "IN_GONDOLA_LIFT": "fa-cable-car",
    "SNOWSHOEING": "fa-person-skiing",
    "KAYAKING": "fa-water",
    "SWIMMING": "fa-person-swimming",
    "SLEDDING": "fa-sleigh",
    "SAILING": "fa-sailboat",
    "PARAGLIDING": "fa-parachute-box",
    "KITESURFING": "fa-water",
    "IN_FUNICULAR": "fa-train-tram",
    "DEFAULT": "fa-route"
  };

  const CATEGORY_ICONS = {
    "Home & Residence": "fa-house-chimney",
    "Work & Office": "fa-briefcase",
    "Food & Drink": "fa-utensils",
    "Parks & Outdoors": "fa-tree",
    "Shopping & Retail": "fa-bag-shopping",
    "Hotels & Lodging": "fa-hotel",
    "Travel & Transit": "fa-train-subway",
    "Arts & Entertainment": "fa-masks-theater",
    "Health & Services": "fa-heart-pulse",
    "Services & Civic": "fa-building-columns",
    "Other / POI": "fa-location-dot"
  };

  // Disambiguate station/transit vs airport icons based on place name and semantic type
  function getPlaceIcon(name = "", category = "", semanticType = "") {
    const text = `${name || ''} ${semanticType || ''}`.toLowerCase();
    
    if (category === "Travel & Transit" || text.includes("station") || text.includes("airport") || text.includes("terminal") || text.includes("transit") || text.includes("gare") || text.includes("bahn")) {
      // 1. Airports, Airfields & Airlines
      if (/\b(airport|aeroport|aeropuerto|flughafen|airfield|aerodrome|intl airport|terminal dr|terminal\s+\d+|airways|airlines|jetblue|lufthansa)\b/i.test(text) || /\b(jfk|lga|ewr|bna|ord|lax|sfo|cdg|ory|lhr|lgw|zrh|fra|muc|cph|arn|osl|ams|dub|ber|txl|sxf|nrt|hnd|kix|icn|sin|hkg|bkk|syd|mel)\b/i.test(text)) {
        return "fa-plane";
      }
      // 2. Subway & Metro
      if (/\b(subway|metro|u-bahn|underground|métro|metropolitana|tube|path station)\b/i.test(text)) {
        return "fa-train-subway";
      }
      // 3. Trams & Streetcars
      if (/\b(tram|streetcar|straßenbahn|tranvia|tranvía)\b/i.test(text)) {
        return "fa-train-tram";
      }
      // 4. Ferries, Ports & Marinas
      if (/\b(ferry|port|harbor|dock|pier|fähre|embarcadère|marina|wharf|terminal ferry)\b/i.test(text)) {
        return "fa-ferry";
      }
      // 5. Buses & Coaches
      if (/\b(bus|autobus|coach|greyhound|megabus|bus terminal|gare routière)\b/i.test(text)) {
        return "fa-bus";
      }
      // 6. Cable cars & Funiculars
      if (/\b(gondola|cable car|seilbahn|teleferico|teleférico|funicular)\b/i.test(text)) {
        return "fa-cable-car";
      }
      // 7. Train & Rail Stations
      if (/\b(station|gare|bahnhof|estacion|estación|stazione|train|rail|amtrak|s-bahn|caltrain|lirr|sncf|eurostar|tgv|ice|db|central station)\b/i.test(text)) {
        return "fa-train";
      }
      return "fa-train-subway";
    }

    return CATEGORY_ICONS[category] || "fa-location-dot";
  }

  // Helper to render star rating
  function renderStars(rating) {
    if (!rating) return "";
    let stars = "";
    for (let i = 1; i <= 5; i++) {
      if (i <= rating) stars += '<i class="fa-solid fa-star" style="color:#fbbf24;font-size:11px;"></i>';
      else stars += '<i class="fa-regular fa-star" style="color:#64748b;font-size:11px;"></i>';
    }
    return `<span class="star-rating" title="${rating} Stars">${stars}</span>`;
  }

  // Resilient Base Tile Layer (100% Free, Zero API Key Required)
  function createBaseTileLayer(options = {}) {
    const layer = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> contributors',
      ...options
    });

    // Automatic fallback if any tile fails to load
    layer.on("tileerror", function (error) {
      const tile = error.tile;
      if (tile && !tile.dataset.fallbackTried) {
        tile.dataset.fallbackTried = "true";
        const coords = error.coords;
        tile.src = `https://a.basemaps.cartocdn.com/rastertiles/voyager/${coords.z}/${coords.x}/${coords.y}.png`;
      }
    });

    return layer;
  }

  // Initialize Maps
  function initMaps() {
    map = L.map("map", {
      zoomControl: true,
      attributionControl: false
    }).setView([40.7270, -73.9774], 13);

    createBaseTileLayer().addTo(map);

    visitLayerGroup.addTo(map);
    routeLayerGroup.addTo(map);
    rawLayerGroup.addTo(map);
    gapLayerGroup.addTo(map);

    heatMap = L.map("heatmap-map", {
      zoomControl: true,
      attributionControl: false
    }).setView([30.0, 10.0], 2);

    createBaseTileLayer().addTo(heatMap);

    const placesMapEl = document.getElementById("places-map");
    if (placesMapEl) {
      placesMap = L.map("places-map", {
        zoomControl: true,
        attributionControl: false,
        preferCanvas: true
      }).setView([40.7300, -73.9850], 12);

      createBaseTileLayer().addTo(placesMap);

      placesCanvasRenderer = L.canvas({ padding: 0.5 });
      placesLayerGroup.addTo(placesMap);

      document.getElementById("btn-places-map-reset")?.addEventListener("click", () => {
        placesMap.setView([35.0, -10.0], 2);
      });
      document.getElementById("btn-places-map-nyc")?.addEventListener("click", () => {
        placesMap.setView([40.7300, -73.9850], 13);
      });
      document.getElementById("btn-places-map-ch")?.addEventListener("click", () => {
        placesMap.setView([47.3769, 8.5417], 12);
      });
      document.getElementById("btn-places-map-ca")?.addEventListener("click", () => {
        placesMap.setView([37.8000, -122.2500], 11);
      });
    }
  }

  let navOriginTab = null;

  // Render floating origin return banner when jumped to timeline from another tab
  function updateOriginBanner() {
    const banner = document.getElementById("timeline-origin-banner");
    if (!banner) return;

    if (navOriginTab && navOriginTab !== "timeline") {
      const tabNames = {
        fixes: "Fix Proposals",
        trips: "Trips & Expeditions",
        places: "Places Catalog",
        heatmap: "Street Discovery & Heatmap",
        diagnostics: "Timeline Diagnostics"
      };
      const label = tabNames[navOriginTab] || "Previous Tab";
      banner.style.display = "block";
      banner.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:space-between;background:rgba(26,115,232,0.1);border:1px solid #1a73e8;border-radius:10px;padding:8px 12px;margin-bottom:10px;box-shadow:var(--shadow-sm);">
          <div style="font-size:12px;color:var(--text-main);display:flex;align-items:center;gap:6px;">
            <i class="fa-solid fa-arrow-turn-down-left" style="color:var(--accent-blue);"></i>
            <span>Viewing date from <strong>${escapeHtml(label)}</strong></span>
          </div>
          <button id="btn-back-to-origin" class="btn-primary" style="padding:4px 10px;font-size:11.5px;border-radius:14px;cursor:pointer;background:var(--accent-blue);">
            <i class="fa-solid fa-arrow-left"></i> Back to ${escapeHtml(label)}
          </button>
        </div>
      `;
      banner.querySelector("#btn-back-to-origin")?.addEventListener("click", () => {
        goBackToOrigin();
      });
    } else {
      banner.style.display = "none";
      banner.innerHTML = "";
    }
  }

  function goBackToOrigin() {
    if (window.history.length > 1) {
      window.history.back();
    } else if (navOriginTab) {
      switchTab(navOriginTab, true);
    } else {
      switchTab("fixes", true);
    }
  }

  // Tab Switching with History State Support
  function switchTab(targetTab, updateHistory = true) {
    const tabBtns = document.querySelectorAll(".tab-btn");
    const panels = document.querySelectorAll(".tab-panel");

    tabBtns.forEach(b => b.classList.remove("active"));
    panels.forEach(p => p.classList.remove("active"));

    const btn = document.querySelector(`.tab-btn[data-tab="${targetTab}"]`);
    if (btn) btn.classList.add("active");
    const activePanel = document.getElementById(`tab-${targetTab}`);
    if (activePanel) activePanel.classList.add("active");

    if (targetTab !== "timeline") {
      navOriginTab = null;
      updateOriginBanner();
    }

    if (updateHistory) {
      const datePart = (targetTab === "timeline" && currentDate) ? `&date=${currentDate}` : '';
      const url = `?tab=${targetTab}${datePart}`;
      if (window.location.search !== url) {
        window.history.pushState({ tab: targetTab, date: currentDate }, "", url);
      }
    }

    if (targetTab === "timeline") {
      setTimeout(() => map && map.invalidateSize(), 150);
    } else if (targetTab === "calendar") {
      loadCalendarMatrix();
    } else if (targetTab === "activities") {
      loadActivitySummaries();
    } else if (targetTab === "trips") {
      loadPassportStats();
      loadTrips();
      loadArchiveNuggets();
    } else if (targetTab === "places") {
      loadPlaces();
    } else if (targetTab === "heatmap") {
      setTimeout(() => {
        if (!heatMap) {
          heatMap = L.map("heatmap-map", {
            zoomControl: true,
            attributionControl: false
          }).setView([30.0, 10.0], 2);

          createBaseTileLayer().addTo(heatMap);
        } else {
          heatMap.invalidateSize(true);
        }
        loadWorldHeatmap();
      }, 100);
    } else if (targetTab === "diagnostics") {
      loadDiagnosticsGaps();
    } else if (targetTab === "fixes") {
      loadFixProposals();
    }
  }

  // Centralized Navigation to Timeline Day (Single clean pushState)
  let pendingHighlightSegmentId = null;

  function jumpToTimelineDay(targetDate, updateHistory = true, fromTab = null, highlightSegmentId = null) {
    if (highlightSegmentId) {
      pendingHighlightSegmentId = highlightSegmentId;
    }
    const currentActiveTab = document.querySelector(".tab-btn.active")?.getAttribute("data-tab") || "fixes";
    navOriginTab = fromTab || (currentActiveTab !== "timeline" ? currentActiveTab : "fixes");

    if (updateHistory) {
      const url = `?tab=timeline&date=${targetDate}`;
      if (window.location.search !== url) {
        window.history.pushState({ tab: "timeline", date: targetDate, fromTab: navOriginTab }, "", url);
      }
    }
    switchTab("timeline", false);
    loadDay(targetDate, false);
    updateOriginBanner();
  }

  function setupTabs() {
    const tabBtns = document.querySelectorAll(".tab-btn");

    tabBtns.forEach(btn => {
      btn.addEventListener("click", () => {
        const targetTab = btn.getAttribute("data-tab");
        navOriginTab = null;
        updateOriginBanner();
        switchTab(targetTab, true);
      });
    });

    // Diagnostics Subtabs
    const subtabBtns = document.querySelectorAll(".subtab-btn");
    subtabBtns.forEach(btn => {
      btn.addEventListener("click", () => {
        subtabBtns.forEach(b => b.classList.remove("active"));
        document.querySelectorAll(".subtab-content").forEach(c => c.classList.remove("active"));

        btn.classList.add("active");
        const target = btn.getAttribute("data-subtab");
        document.getElementById(`${target}-view`)?.classList.add("active");

        if (target === "gaps-table") loadDiagnosticsGaps();
        else if (target === "speed-table") loadSpeedAnomalies();
        else if (target === "unconf-table") loadUnconfirmedPlaces();
      });
    });

    // Make Diag Top Cards Clickable
    document.querySelectorAll(".diag-card").forEach((card, idx) => {
      card.style.cursor = "pointer";
      card.addEventListener("click", () => {
        if (idx === 0) document.querySelector('.subtab-btn[data-subtab="gaps-table"]')?.click();
        else if (idx === 2) document.querySelector('.subtab-btn[data-subtab="speed-table"]')?.click();
        else if (idx === 3 || idx === 1) document.querySelector('.subtab-btn[data-subtab="unconf-table"]')?.click();
      });
    });
  }

  // Load Overview Stats
  async function loadOverview() {
    try {
      const res = await fetch("/api/overview");
      const data = await res.json();
      if (data.status === "SUCCESS") {
        const sc = data.scorecard || {};
        setElText("stat-hydrated", `${sc.place_hydration_rate_pct || 100}%`);
        setElText("stat-snapped", `${sc.path_snapped_rate_pct || 0}%`);
        setElText("stat-distance", `${((sc.total_distance_km || 0) / 1000).toFixed(1)}k km`);

        setElText("badge-trips", `${sc.total_trips || 150}`);
        setElText("badge-places", `${((sc.total_places_catalog || 0) / 1000).toFixed(1)}k`);
        setElText("badge-fixes", `${sc.post_2010_gaps || 0}`);
        if (sc.reviewed_pois) {
          setElText("badge-reviews", `${(sc.reviewed_pois / 1000).toFixed(1)}k`);
        }

        setElText("diag-post-gaps", sc.post_2010_gaps || 0);
        setElText("diag-speed-outliers", sc.speed_anomalies || 0);
        setElText("diag-child-visits", sc.child_visits || 0);

        if (sc.max_date) {
          const picker = document.getElementById("date-picker");
          if (picker) {
            picker.min = sc.min_date || "1976-11-30";
            picker.max = sc.max_date || "2030-12-31";
          }
        }
      }
    } catch (e) {
      console.error("Error loading overview:", e);
    }
  }

  // Load Day Data
  async function loadDay(dateStr, updateHistory = true) {
    currentDate = dateStr;
    if (updateHistory) {
      const activeTab = document.querySelector(".tab-btn.active")?.getAttribute("data-tab") || "timeline";
      const newUrl = `?tab=${activeTab}&date=${dateStr}`;
      if (window.location.search !== newUrl) {
        window.history.pushState({ tab: activeTab, date: dateStr }, "", newUrl);
      }
    }
    const picker = document.getElementById("date-picker");
    if (picker) picker.value = dateStr;
    const container = document.getElementById("itinerary-container");
    container.innerHTML = '<div class="loading-spinner"><i class="fa-solid fa-circle-notch fa-spin"></i> Loading Day...</div>';

    try {
      const res = await fetch(`/api/day?date=${dateStr}`);
      const data = await res.json();

      if (data.status !== "SUCCESS") {
        container.innerHTML = `<div class="empty-state"><p>${data.error || 'No records found'}</p></div>`;
        return;
      }

      renderDayItinerary(data);
      renderDayMap(data);
      render24HourScrubber(data);

      if (gmmPanelOpen) {
        const dateBadge = document.getElementById("gmm-active-date");
        if (dateBadge) dateBadge.textContent = dateStr;
        syncGMMDate(dateStr);
        loadGMMComparison(dateStr);
      }

    } catch (e) {
      console.error("Error loading day:", e);
      container.innerHTML = `<div class="empty-state"><p>Failed to load day: ${e.message}</p></div>`;
    }
  }


  // Render 24-Hour Visual Scrubber
  function render24HourScrubber(dayData) {
    const bar = document.getElementById("scrubber-bar");
    bar.innerHTML = "";

    const segments = dayData.segments || [];
    const gaps = dayData.gaps || [];

    if (segments.length === 0) return;

    const dayStartTs = new Date(`${dayData.date}T00:00:00Z`).getTime() / 1000.0;
    const daySeconds = 86400.0;

    segments.forEach(s => {
      const leftPct = Math.max(0, Math.min(100, ((s.start_ts - dayStartTs) / daySeconds) * 100));
      const widthPct = Math.max(0.5, Math.min(100 - leftPct, ((s.duration_minutes * 60) / daySeconds) * 100));

      const block = document.createElement("div");
      block.className = "scrub-block";
      block.style.left = `${leftPct}%`;
      block.style.width = `${widthPct}%`;

      if (s.segment_type === "visit") {
        block.classList.add(s.hierarchy_level === 1 ? "child-visit" : "visit");
        block.title = `Visit: ${s.place_name || 'Home/Place'} (${s.start_time.slice(11,16)} - ${s.end_time.slice(11,16)})`;
      } else {
        const act = (s.activity_type || "").toUpperCase();
        if (act.includes("VEHICLE") || act.includes("BUS") || act.includes("TAXI")) block.classList.add("drive");
        else if (act.includes("WALK") || act.includes("FOOT") || act.includes("RUN")) block.classList.add("walk");
        else if (act.includes("CYCLE") || act.includes("BIKE")) block.classList.add("cycle");
        else if (act.includes("FLY")) block.classList.add("flight");
        else block.classList.add("drive");
        block.title = `${s.activity_type || 'Travel'}: ${(s.distance_meters/1000).toFixed(1)}km (${s.start_time.slice(11,16)} - ${s.end_time.slice(11,16)})`;
      }

      bar.appendChild(block);
    });

    gaps.forEach(g => {
      const leftPct = Math.max(0, Math.min(100, ((g.start_ts - dayStartTs) / daySeconds) * 100));
      const widthPct = Math.max(0.5, Math.min(100 - leftPct, ((g.duration_hours * 3600) / daySeconds) * 100));

      const block = document.createElement("div");
      block.className = "scrub-block gap";
      block.style.left = `${leftPct}%`;
      block.style.width = `${widthPct}%`;
      const gStart = g.local_start_time || g.start_time.slice(11,16);
      const gEnd = g.local_end_time || g.end_time.slice(11,16);
      block.title = `Timeline Gap: ${g.duration_hours.toFixed(1)}h (${gStart} - ${gEnd})`;
      bar.appendChild(block);
    });
  }

  // Render Day Itinerary Cards
  function renderDayItinerary(dayData) {
    const container = document.getElementById("itinerary-container");
    container.innerHTML = "";

    const segments = dayData.segments || [];
    const gaps = dayData.gaps || [];

    const visitsCount = segments.filter(s => s.segment_type === "visit").length;
    const activitiesCount = segments.filter(s => s.segment_type === "activity").length;
    const totalKm = segments.reduce((acc, s) => acc + (s.distance_meters || 0) / 1000.0, 0);
    const dayPhotosCount = dayData.photo_count || (dayData.photos ? dayData.photos.length : 0);

    document.getElementById("day-summary-text").textContent = 
      `${visitsCount} visits · ${activitiesCount} travel movements · ${totalKm.toFixed(1)} km · ${gaps.length} gaps` + (dayPhotosCount ? ` · ${dayPhotosCount} photos` : '');

    if (segments.length === 0 && (!dayData.memories || dayData.memories.length === 0)) {
      container.innerHTML = '<div class="empty-state"><p>No timeline records recorded for this day.</p></div>';
      return;
    }

    if (dayData.memories && dayData.memories.length > 0) {
      dayData.memories.forEach(m => {
        const memCard = document.createElement("div");
        memCard.className = "card timeline-memory-card";
        memCard.style.cssText = "background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.3);padding:12px 14px;border-radius:8px;margin-bottom:12px;display:flex;align-items:flex-start;gap:12px;";
        const noteText = escapeHtml(m.raw_text || m.title || "Day Note");
        const titleText = escapeHtml(m.title && m.title !== m.raw_text ? m.title : "Day Note");
        memCard.innerHTML = `
          <i class="fa-solid fa-note-sticky" style="color:#d97706;font-size:20px;margin-top:2px;flex-shrink:0;"></i>
          <div style="flex:1;min-width:0;">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:3px;">
              <span style="font-size:11px;font-weight:700;color:#d97706;text-transform:uppercase;letter-spacing:0.5px;">${titleText}</span>
              <span style="font-size:10px;font-weight:600;color:var(--text-muted);">Timeline Note</span>
            </div>
            <p style="margin:0;font-size:13px;font-weight:400;color:var(--text-main);line-height:1.45;">${noteText}</p>
          </div>
        `;
        container.appendChild(memCard);
      });
    }

    // Render interactive day photos gallery if photos exist for this day
    if (dayData.photos && dayData.photos.length > 0) {
      const photosBox = document.createElement("div");
      photosBox.className = "card day-photos-box";
      photosBox.style.cssText = "background:var(--bg-subtle);border:1px solid var(--border-color);padding:10px 12px;border-radius:8px;margin-bottom:12px;";
      const photoUrls = dayData.photos.map(p => p.preview_url);
      photosBox.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
          <div style="display:flex;align-items:center;gap:6px;font-size:12px;font-weight:600;color:var(--text-main);">
            <i class="fa-solid fa-camera" style="color:#0284c7;"></i> Photos from this Day
            <span class="tag-badge" style="background:#e0f2fe;color:#0369a1;font-size:10px;font-weight:700;">${dayData.photos.length}</span>
          </div>
          <span class="day-photos-view-all-btn" style="font-size:11px;color:var(--text-muted);cursor:pointer;">View All (${dayData.photos.length}) <i class="fa-solid fa-arrow-up-right-from-square"></i></span>
        </div>
        <div class="day-photos-strip" style="display:flex;gap:8px;overflow-x:auto;padding-bottom:4px;">
          ${dayData.photos.map((p, idx) => `
            <div class="review-photo-thumb-wrapper day-photo-thumb" data-idx="${idx}" title="${escapeHtml(p.filename || '')} (${escapeHtml(p.place_name || '')})">
              <img class="review-photo-thumb" src="${getPhotoUrl(p.preview_url, 180)}" style="width:60px;height:60px;object-fit:cover;border-radius:6px;cursor:pointer;border:1px solid var(--border-color);" alt="Photo" loading="lazy" onerror="this.parentElement.style.display='none'" />
            </div>
          `).join('')}
        </div>
      `;
      photosBox.querySelector(".day-photos-view-all-btn")?.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        window.openPhotoLightbox(photoUrls, 0, `Photos from ${dayData.date}`, "");
      });
      photosBox.querySelectorAll(".day-photo-thumb").forEach(thumb => {
        thumb.addEventListener("click", (e) => {
          e.preventDefault();
          e.stopPropagation();
          const idx = parseInt(thumb.getAttribute("data-idx") || "0", 10);
          const p = dayData.photos[idx] || {};
          window.openPhotoLightbox(photoUrls, idx, p.place_name || dayData.date, p.filename || "");
        });
      });
      container.appendChild(photosBox);
    }

    // Separate top-level events and child visits
    const topSegments = segments.filter(s => s.hierarchy_level !== 1);
    const childSegments = segments.filter(s => s.hierarchy_level === 1);

    const allEvents = [];
    topSegments.forEach(s => allEvents.push({ kind: "segment", ts: s.start_ts, data: s }));
    gaps.forEach(g => allEvents.push({ kind: "gap", ts: g.start_ts, data: g }));
    allEvents.sort((a, b) => a.ts - b.ts);

    allEvents.forEach(ev => {
      if (ev.kind === "segment") {
        const s = ev.data;
        const card = document.createElement("div");
        card.className = "item-card";
        card.setAttribute("data-id", s.id);

        const isPrevDayStart = s.started_previous_day || (s.start_time && s.start_time.slice(0, 10) < currentDate);
        const timeStr = isPrevDayStart
          ? `Left at ${s.local_end_time || (s.end_time ? s.end_time.slice(11, 16) : '--:--')} (Started yesterday at ${s.local_start_time || (s.start_time ? s.start_time.slice(11, 16) : '--:--')})`
          : formatEventTime(s.start_time, s.end_time, s.start_ts, s.end_ts, s.local_start_time, s.local_end_time);
        const durStr = s.duration_minutes >= 60 
          ? `${(s.duration_minutes/60).toFixed(1)}h` 
          : (s.duration_minutes < 1 ? `${Math.max(5, Math.round(s.duration_minutes * 60))}s` : `${Math.round(s.duration_minutes)}m`);

        if (s.segment_type === "visit") {
          const title = s.place_name || s.catalog_place_name || "Home/Place";
          const addr = s.place_address || s.catalog_place_address || (s.latitude ? `${s.latitude.toFixed(4)}, ${s.longitude.toFixed(4)}` : "");
          const cat = s.catalog_category || s.category || "Other / POI";
          const city = s.catalog_city || s.city || "";
          const rating = s.catalog_review_rating || s.review_rating;
          const revText = s.catalog_review_text;

          // Find all child visits inside this parent visit window
          const matchingChildren = childSegments.filter(c => 
            c.start_ts >= (s.start_ts - 300) && c.end_ts <= (s.end_ts + 300)
          );

          // Group multiple sessions of the same child venue
          const childGroups = {};
          matchingChildren.forEach(c => {
            const cName = c.place_name || c.catalog_place_name || "Venue";
            if (!childGroups[cName]) {
              childGroups[cName] = { name: cName, category: c.category || "Other / POI", totalMins: 0, sessions: [] };
            }
            childGroups[cName].totalMins += (c.duration_minutes || 0);
            const cTimeStr = `${c.start_time ? c.start_time.slice(11, 16) : ''} – ${c.end_time ? c.end_time.slice(11, 16) : ''}`;
            const cDurStr = c.duration_minutes >= 60 ? `${(c.duration_minutes/60).toFixed(1)}h` : `${Math.round(c.duration_minutes)}m`;
            childGroups[cName].sessions.push(`${cTimeStr} (${cDurStr})`);
          });

          let iconType = "visit";
          if (cat === "Home & Residence") iconType = "home";
          else if (cat === "Work & Office") iconType = "work";
          else if (cat === "Food & Drink") iconType = "food";

          let childHtml = "";
          const groupKeys = Object.keys(childGroups);
          if (groupKeys.length > 0) {
            childHtml = `
              <div class="nested-child-box" style="margin-top:8px;padding:8px 10px;background:rgba(6,182,212,0.08);border-left:3px solid #06b6d4;border-radius:6px;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                  <span style="font-size:10px;font-weight:700;color:#0e7490;text-transform:uppercase;letter-spacing:0.5px;">
                    <i class="fa-solid fa-sitemap"></i> Venues Inside:
                  </span>
                </div>
                ${groupKeys.map(k => {
                  const g = childGroups[k];
                  const totStr = g.totalMins >= 60 ? `${(g.totalMins/60).toFixed(1)}h` : `${Math.round(g.totalMins)}m`;
                  return `
                    <div style="margin-top:4px;font-size:12px;display:flex;align-items:center;gap:6px;">
                      <strong style="color:var(--text-main);"><i class="fa-solid ${getPlaceIcon(g.name, g.category)}" style="color:#0284c7;font-size:11px;"></i> ${escapeHtml(g.name)}</strong>
                      <span class="tag-badge child-tag" style="font-size:10px;"><i class="fa-regular fa-clock"></i> ${totStr}</span>
                    </div>
                  `;
                }).join('')}
              </div>
            `;
          }

          card.innerHTML = `
            <div class="item-icon ${iconType}">
              <i class="fa-solid ${getPlaceIcon(title, cat, s.semantic_type)}"></i>
            </div>
            <div class="item-body">
              <div class="item-title-row">
                <span class="item-title" title="${escapeHtml(title)}">${escapeHtml(title)}</span>
                <span class="item-time">${timeStr}</span>
              </div>
              <div class="item-address" title="${escapeHtml(addr)}">${escapeHtml(addr)}</div>
              <div class="item-tags">
                <span class="tag-badge"><i class="fa-regular fa-clock"></i> ${durStr}</span>
                ${isPrevDayStart ? '<span class="tag-badge" style="background:#f3e8ff;color:#6b21a8;border:1px solid #e9d5ff;font-size:10px;font-weight:600;"><i class="fa-solid fa-moon"></i> Overnight Stay</span>' : ''}
                <span class="tag-badge category-tag">${escapeHtml(cat)}</span>
                ${s.source === 'plazes' ? '<span class="tag-badge" style="background:#fef3c7;color:#92400e;border:1px solid #fde68a;font-size:10px;font-weight:600;"><i class="fa-solid fa-bolt"></i> Plazes</span>' : ''}
                ${rating ? `<span class="tag-badge review-tag" title="Your Personal Rating: ${rating} Stars">${renderStars(rating)}</span>` : ''}
                ${s.review_photos && s.review_photos.length ? `<span class="tag-badge visit-photo-badge" style="font-size:10px;background:#dbeafe;color:#1d4ed8;border:1px solid #bfdbfe;font-weight:600;cursor:pointer;" title="View photos in lightbox"><i class="fa-solid fa-camera"></i> ${s.review_photos.length}</span>` : ''}
                <button class="icon-btn edit-place-btn" style="width:20px;height:20px;font-size:10px;margin-left:auto;" title="Edit Visit Details"><i class="fa-solid fa-pen"></i></button>
              </div>
              ${s.review_text ? `
                <div class="user-review-snippet" style="margin-top:6px;padding:6px 10px;background:#f0fdf4;border-left:3px solid #22c55e;border-radius:6px;font-size:11px;color:#166534;">
                  <div style="display:flex;align-items:flex-start;gap:4px;"><i class="fa-solid fa-star" style="color:#f59e0b;font-size:10px;margin-top:2px;"></i><div><strong>Your Review:</strong> "${escapeHtml(s.review_text)}"</div></div>
                </div>
              ` : ''}
              ${s.review_photos && s.review_photos.length ? `
                <div class="review-photos-strip" style="margin-top:6px;">
                  ${s.review_photos.map((url, idx) => `
                    <div class="review-photo-thumb-wrapper visit-photo-thumb" data-idx="${idx}" title="View photo (${idx+1}/${s.review_photos.length})">
                      <img class="review-photo-thumb" src="${getPhotoUrl(url, 240)}" alt="Photo" loading="lazy" referrerpolicy="no-referrer" onerror="this.parentElement.style.display='none'" />
                    </div>
                  `).join('')}
                </div>
              ` : ''}
              ${s.event_title ? `
                <div class="calendar-event-box" style="margin-top:6px;padding:6px 10px;background:rgba(139,92,246,0.10);border-left:3px solid #8b5cf6;border-radius:6px;font-size:11px;color:#e2e8f0;">
                  <div style="display:flex;align-items:center;gap:6px;font-weight:600;color:#c084fc;">
                    <i class="fa-solid fa-calendar-check"></i> ${escapeHtml(s.event_title)}
                  </div>
                  ${s.with_people && Array.isArray(s.with_people) && s.with_people.length ? `
                    <div style="margin-top:3px;font-size:11px;color:#94a3b8;display:flex;align-items:center;gap:5px;">
                      <i class="fa-solid fa-user-group" style="color:#a855f7;"></i> With: <strong style="color:#f1f5f9;">${escapeHtml(s.with_people.join(', '))}</strong>
                    </div>
                  ` : ''}
                  ${s.event_location ? `
                    <div style="margin-top:2px;font-size:10px;color:#94a3b8;">
                      <i class="fa-solid fa-location-dot" style="color:#a855f7;"></i> ${escapeHtml(s.event_location)}
                    </div>
                  ` : ''}
                </div>
              ` : ''}
              ${childHtml}
              ${(() => {
                const matchingVisitFix = (dayData.fix_proposals || []).find(f => f.target_id === s.id && f.status === 'PENDING');
                if (!matchingVisitFix) return '';
                let patch = {};
                try { patch = JSON.parse(matchingVisitFix.patch_data_json || '{}'); } catch(e) {}
                const propPlace = patch.target_place || 'Verified Place';
                return `
                  <div class="proposal-box" style="margin-top:8px;padding:8px 10px;background:rgba(59,130,246,0.08);border:1px dashed #3b82f6;border-radius:6px;">
                    <div style="font-size:10px;font-weight:700;color:#60a5fa;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">
                      <i class="fa-solid fa-wand-magic-sparkles"></i> Proposed Fix: Confirm Venue
                    </div>
                    <div style="font-size:11px;color:#e2e8f0;margin-bottom:6px;">
                      ${escapeHtml(matchingVisitFix.reasoning)}
                    </div>
                    <div style="display:flex;gap:6px;">
                      <button class="btn btn-sm apply-visit-fix-btn" style="background:#3b82f6;color:#fff;border:none;padding:3px 8px;font-size:11px;border-radius:4px;cursor:pointer;">
                        <i class="fa-solid fa-check"></i> Apply (${escapeHtml(propPlace)})
                      </button>
                      <button class="btn btn-sm btn-secondary edit-visit-fix-btn" style="padding:3px 8px;font-size:11px;border-radius:4px;cursor:pointer;">
                        <i class="fa-solid fa-pen"></i> Edit
                      </button>
                    </div>
                  </div>
                `;
              })()}
            </div>
          `;

          const matchingVisitFix = (dayData.fix_proposals || []).find(f => f.target_id === s.id && f.status === 'PENDING');
          if (matchingVisitFix) {
            card.querySelector(".apply-visit-fix-btn")?.addEventListener("click", async (e) => {
              e.stopPropagation();
              let patch = {};
              try { patch = JSON.parse(matchingVisitFix.patch_data_json || '{}'); } catch(err) {}
              const btn = e.currentTarget;
              btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Applying...';
              btn.disabled = true;
              try {
                const res = await fetch("/api/proposals/edit-and-apply", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({
                    proposal_id: matchingVisitFix.id,
                    custom_place: patch.target_place,
                    custom_cat: patch.category || "Other / POI"
                  })
                });
                const resData = await res.json();
                if (resData.status === "SUCCESS") {
                  await loadDay(currentDate, false);
                } else {
                  alert(resData.error || "Failed to apply fix");
                  btn.innerHTML = '<i class="fa-solid fa-check"></i> Apply';
                  btn.disabled = false;
                }
              } catch (err) {
                alert("Error: " + err.message);
                btn.innerHTML = '<i class="fa-solid fa-check"></i> Apply';
                btn.disabled = false;
              }
            });

            card.querySelector(".edit-visit-fix-btn")?.addEventListener("click", (e) => {
              e.stopPropagation();
              openEditProposalModal(matchingVisitFix, null);
            });
          }

          card.querySelector(".edit-place-btn")?.addEventListener("click", (e) => {
            e.stopPropagation();
            openEditSegmentModal(s);
          });

          // Attach robust click listeners to visit photo thumbnails and badge
          card.querySelectorAll(".visit-photo-thumb").forEach(thumb => {
            thumb.addEventListener("click", (e) => {
              e.preventDefault();
              e.stopPropagation();
              const idx = parseInt(thumb.getAttribute("data-idx") || "0", 10);
              const photos = s.review_photos || [];
              window.openPhotoLightbox(photos, idx, title, s.review_text || "");
            });
          });

          card.querySelector(".visit-photo-badge")?.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            window.openPhotoLightbox(s.review_photos || [], 0, title, s.review_text || "");
          });

        } else {
          const actType = (s.activity_type || "TRAVEL").toUpperCase();
          const iconClass = ACTIVITY_ICONS[actType] || ACTIVITY_ICONS["DEFAULT"];
          let modeClass = "drive";
          if (actType.includes("WALK") || actType.includes("FOOT") || actType.includes("RUN")) modeClass = "walk";
          else if (actType.includes("CYCLE") || actType.includes("BIKE")) modeClass = "cycle";
          else if (actType.includes("FLY")) modeClass = "flight";

          const distM = s.distance_meters || 0.0;
          const distKm = (distM / 1000.0).toFixed(1);
          const hasSnapped = s.has_snapped_path === 1 || Boolean(s.path_points_json && s.path_points_json.length > 5);
          const isSameDockLoop = (actType.includes("CYCLE") || actType.includes("BIKE")) && distM < 30.0 && s.duration_minutes >= 2.0;
          const isStationaryActivity = !isSameDockLoop && actType !== "CYCLING" && !(s.source || "").includes("citibike") && distM < 30.0 && s.duration_minutes >= 3.0;
          
          let displayDistKm = distKm;
          if (isSameDockLoop && distM < 30.0) {
            // Estimate loop distance based on cycling speed (~14 km/h = 233 m/min)
            const estM = Math.round(s.duration_minutes * 230.0);
            displayDistKm = (estM / 1000.0).toFixed(1);
          }

          const actTitle = `${actType.replace(/_/g, ' ')}${isSameDockLoop ? ' (Round-Trip Loop)' : (isStationaryActivity ? ' · Stationary Dwell / Pause' : '')}`;

          card.innerHTML = `
            <div class="item-icon ${modeClass}">
              <i class="fa-solid ${iconClass}"></i>
            </div>
            <div class="item-body">
              <div class="item-title-row">
                <span class="item-title" title="${escapeHtml(actTitle)}">${escapeHtml(actTitle)}</span>
                <span class="item-time">${timeStr}</span>
              </div>
              <div class="item-address">${isStationaryActivity ? `Stationary dwell (${durStr})` : `${displayDistKm} km · ${durStr}${isSameDockLoop ? ' · Out & Back' : ''}`}</div>
              <div class="item-tags">
                ${isStationaryActivity 
                  ? `<span class="tag-badge" style="background:#fef9c3;color:#854d0e;border:1px solid #fef08a;font-size:10px;font-weight:600;"><i class="fa-solid fa-pause"></i> Stationary Pause (${durStr})</span>`
                  : `<span class="tag-badge"><i class="fa-solid fa-arrows-left-right"></i> ${displayDistKm} km</span>`
                }
                ${hasSnapped ? '<span class="tag-badge snapped"><i class="fa-solid fa-route"></i> Snapped Route</span>' : ''}
                ${s.review_photos && s.review_photos.length ? `<span class="tag-badge activity-photo-badge" style="font-size:10px;background:#dbeafe;color:#1d4ed8;border:1px solid #bfdbfe;font-weight:600;cursor:pointer;" title="View photos in lightbox"><i class="fa-solid fa-camera"></i> ${s.review_photos.length}</span>` : ''}
                ${!isStationaryActivity ? `<button class="btn-3d-ride" title="Ride along this route in 3D Earth view"><i class="fa-solid fa-earth-americas"></i> 3D Ride</button>` : ''}
                <button class="icon-btn edit-activity-btn" style="width:20px;height:20px;font-size:10px;margin-left:auto;" title="Edit Activity Details"><i class="fa-solid fa-pen"></i></button>
              </div>
              ${s.review_photos && s.review_photos.length ? `
                <div class="review-photos-strip" style="margin-top:6px;">
                  ${s.review_photos.map((url, idx) => `
                    <div class="review-photo-thumb-wrapper activity-photo-thumb" data-idx="${idx}" title="View photo (${idx+1}/${s.review_photos.length})">
                      <img class="review-photo-thumb" src="${getPhotoUrl(url, 240)}" alt="Photo" loading="lazy" referrerpolicy="no-referrer" onerror="this.parentElement.style.display='none'" />
                    </div>
                  `).join('')}
                </div>
              ` : ''}
              ${(() => {
                const matchingFlightFix = (dayData.fix_proposals || []).find(f => f.target_id === s.id && f.target_type === 'flight' && f.status === 'PENDING');
                if (!matchingFlightFix) return '';
                let patch = {};
                try { patch = JSON.parse(matchingFlightFix.patch_data_json || '{}'); } catch(e) {}
                const propAirport = patch.airport_name ? `${patch.airport_name} (${patch.airport_iata || ''})` : 'Airport';
                return `
                  <div class="proposal-box" style="margin-top:8px;padding:8px 10px;background:rgba(26,115,232,0.08);border:1px dashed #1a73e8;border-radius:8px;">
                    <div style="font-size:10.5px;font-weight:700;color:var(--accent-blue);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">
                      <i class="fa-solid fa-plane-arrival"></i> Proposed Airport Continuity Fix
                    </div>
                    <div style="font-size:11.5px;color:var(--text-main);margin-bottom:6px;">
                      ${escapeHtml(matchingFlightFix.reasoning)}
                    </div>
                    <div style="display:flex;gap:6px;">
                      <button class="btn btn-sm apply-flight-fix-btn" style="background:var(--accent-blue);color:#fff;border:none;padding:4px 10px;font-size:11px;border-radius:12px;cursor:pointer;">
                        <i class="fa-solid fa-plus"></i> Insert (${escapeHtml(propAirport)})
                      </button>
                      <button class="btn btn-sm btn-secondary edit-flight-fix-btn" style="padding:4px 8px;font-size:11px;border-radius:12px;cursor:pointer;">
                        <i class="fa-solid fa-pen"></i> Edit
                      </button>
                      <button class="btn btn-sm btn-secondary reject-flight-fix-btn" style="padding:4px 8px;font-size:11px;color:var(--accent-red);border-radius:12px;cursor:pointer;">
                        <i class="fa-solid fa-xmark"></i> Dismiss
                      </button>
                    </div>
                  </div>
                `;
              })()}
            </div>
          `;

          const matchingFlightFix = (dayData.fix_proposals || []).find(f => f.target_id === s.id && f.target_type === 'flight' && f.status === 'PENDING');
          if (matchingFlightFix) {
            card.querySelector(".apply-flight-fix-btn")?.addEventListener("click", async (e) => {
              e.stopPropagation();
              const btn = e.currentTarget;
              btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i>';
              btn.disabled = true;
              try {
                const res = await fetch("/api/fixes/apply", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ proposal_id: matchingFlightFix.id })
                });
                const resData = await res.json();
                if (resData.status === "SUCCESS") {
                  loadDay(currentDate, false);
                  loadOverview();
                } else {
                  alert("Failed to apply airport proposal");
                  btn.innerHTML = '<i class="fa-solid fa-plus"></i> Insert';
                  btn.disabled = false;
                }
              } catch(err) {
                alert("Error: " + err.message);
              }
            });

            card.querySelector(".edit-flight-fix-btn")?.addEventListener("click", (e) => {
              e.stopPropagation();
              openEditProposalModal(s, matchingFlightFix);
            });

            card.querySelector(".reject-flight-fix-btn")?.addEventListener("click", async (e) => {
              e.stopPropagation();
              await fetch("/api/fixes/reject", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ proposal_id: matchingFlightFix.id })
              });
              card.querySelector(".proposal-box")?.remove();
            });
          }

          card.querySelector(".edit-activity-btn")?.addEventListener("click", (e) => {
            e.stopPropagation();
            openEditSegmentModal(s);
          });

          card.querySelector(".btn-3d-ride")?.addEventListener("click", (e) => {
            e.stopPropagation();
            openEarthRidePlayer(s.id, false);
          });

          // Attach robust click listeners to activity photo thumbnails and badge
          card.querySelectorAll(".activity-photo-thumb").forEach(thumb => {
            thumb.addEventListener("click", (e) => {
              e.preventDefault();
              e.stopPropagation();
              const idx = parseInt(thumb.getAttribute("data-idx") || "0", 10);
              const photos = s.review_photos || [];
              window.openPhotoLightbox(photos, idx, actTitle, "");
            });
          });

          card.querySelector(".activity-photo-badge")?.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            window.openPhotoLightbox(s.review_photos || [], 0, actTitle, "");
          });
        }

        card.addEventListener("click", () => {
          if (s.latitude && s.longitude) {
            map.flyTo([s.latitude, s.longitude], 15, { duration: 0.8 });
          }
        });

        container.appendChild(card);

      } else {
        const g = ev.data;
        const gapCard = document.createElement("div");
        gapCard.className = "item-card is-gap";
        const timeStr = formatEventTime(g.start_time, g.end_time, g.start_ts, g.end_ts, g.local_start_time, g.local_end_time);
        const jumpStr = g.jump_distance_km ? `${g.jump_distance_km.toFixed(1)} km leap` : 'Stationary';

        // Check if there is an active proposal for this gap
        const matchingFix = (dayData.fix_proposals || []).find(f => f.target_id === g.id && f.status === 'PENDING');

        gapCard.innerHTML = `
          <div class="item-icon gap">
            <i class="fa-solid fa-triangle-exclamation"></i>
          </div>
          <div class="item-body">
            <div class="item-title-row">
              <span class="item-title" style="color:#f87171;">Timeline Gap (${g.duration_hours.toFixed(1)}h)</span>
              <span class="item-time">${timeStr}</span>
            </div>
            <div class="item-address">Tracking dropped between segments · ${jumpStr}</div>
            <div class="item-tags">
              <span class="tag-badge" style="color:#f87171;"><i class="fa-regular fa-clock"></i> ${g.duration_hours.toFixed(1)} hours</span>
              <span class="tag-badge"><i class="fa-solid fa-satellite-dish"></i> ${g.raw_signals_count} sensor pings</span>
              <button class="btn-secondary add-segment-to-gap-btn" style="padding:2px 8px;font-size:10px;margin-left:auto;" title="Manually insert segment into this gap"><i class="fa-solid fa-plus"></i> Add Segment</button>
            </div>
            ${matchingFix ? `
              <div class="gap-proposal-box" style="margin-top:10px;padding:8px 12px;background:rgba(192,132,252,0.12);border:1px dashed #c084fc;border-radius:8px;">
                <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">
                  <div style="flex:1;">
                    <strong style="color:#c084fc;font-size:12px;display:block;"><i class="fa-solid fa-wand-magic-sparkles"></i> Proposed Fix: ${matchingFix.proposed_action.replace(/_/g, ' ')}</strong>
                    <span style="font-size:11px;color:var(--text-muted);display:block;margin-top:2px;">${matchingFix.reasoning}</span>
                  </div>
                  <div style="display:flex;gap:6px;">
                    <button class="btn-primary inline-apply-fix-btn" data-id="${matchingFix.id}" style="padding:4px 10px;font-size:11px;background:var(--accent-green);cursor:pointer;" title="Apply proposed patch">
                      <i class="fa-solid fa-check"></i> Apply
                    </button>
                    <button class="btn-secondary inline-edit-fix-btn" data-id="${matchingFix.id}" style="padding:4px 8px;font-size:11px;cursor:pointer;" title="Edit and customize proposal">
                      <i class="fa-solid fa-pen-to-square"></i> Edit
                    </button>
                    <button class="btn-secondary inline-reject-fix-btn" data-id="${matchingFix.id}" style="padding:4px 8px;font-size:11px;color:var(--accent-red);cursor:pointer;" title="Dismiss proposal">
                      <i class="fa-solid fa-xmark"></i>
                    </button>
                  </div>
                </div>
              </div>
            ` : ''}
          </div>
        `;

        gapCard.querySelector(".inline-edit-fix-btn")?.addEventListener("click", (e) => {
          e.stopPropagation();
          openEditProposalModal(g, matchingFix);
        });

        gapCard.querySelector(".add-segment-to-gap-btn")?.addEventListener("click", (e) => {
          e.stopPropagation();
          openAddSegmentModal(g);
        });

        gapCard.querySelector(".inline-apply-fix-btn")?.addEventListener("click", async (e) => {
          e.stopPropagation();
          const btn = gapCard.querySelector(".inline-apply-fix-btn");
          btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i>';
          btn.disabled = true;
          try {
            const res = await fetch("/api/fixes/apply", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ proposal_id: matchingFix.id })
            });
            const data = await res.json();
            if (data.status === "SUCCESS") {
              loadDay(currentDate);
              loadOverview();
            } else {
              alert("Failed to apply fix proposal.");
              btn.innerHTML = '<i class="fa-solid fa-check"></i> Apply Fix';
              btn.disabled = false;
            }
          } catch(err) {
            alert("Error applying fix: " + err.message);
            btn.innerHTML = '<i class="fa-solid fa-check"></i> Apply Fix';
            btn.disabled = false;
          }
        });

        gapCard.querySelector(".inline-reject-fix-btn")?.addEventListener("click", async (e) => {
          e.stopPropagation();
          await fetch("/api/fixes/reject", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ proposal_id: matchingFix.id })
          });
          gapCard.querySelector(".gap-proposal-box")?.remove();
        });

        container.appendChild(gapCard);
      }
    });

    if (pendingHighlightSegmentId) {
      const hId = pendingHighlightSegmentId;
      pendingHighlightSegmentId = null;
      setTimeout(() => {
        const targetCard = document.querySelector(`.item-card[data-id="${hId}"]`);
        if (targetCard) {
          targetCard.scrollIntoView({ behavior: "smooth", block: "center" });
          targetCard.classList.add("highlight-pulse");
          setTimeout(() => targetCard.classList.remove("highlight-pulse"), 3600);
        }
      }, 250);
    }
  }

  // Render Day Map Layers
  function renderDayMap(dayData) {
    visitLayerGroup.clearLayers();
    routeLayerGroup.clearLayers();
    rawLayerGroup.clearLayers();
    gapLayerGroup.clearLayers();

    const segments = dayData.segments || [];
    const gaps = dayData.gaps || [];
    const rawSignals = dayData.raw_signals || [];
    const bounds = [];

    // Helper to calculate distance between coordinates in meters
    function coordDistMeters(c1, c2) {
      const dLat = (c2[0] - c1[0]) * 111320;
      const dLng = (c2[1] - c1[1]) * 111320 * Math.cos(c1[0] * Math.PI / 180);
      return Math.sqrt(dLat * dLat + dLng * dLng);
    }

    const sortedSegs = segments.slice().sort((a, b) => (a.start_ts || 0) - (b.start_ts || 0));

    // Global map layer registry for selection & highlight
    segmentLayerMap.clear();

    function selectSegment(segId) {
      document.querySelectorAll(".item-card").forEach(c => c.classList.remove("is-selected"));
      const card = document.querySelector(`.item-card[data-id="${segId}"]`);
      if (card) {
        card.classList.add("is-selected");
        card.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }

      // Reset all layer styles
      segmentLayerMap.forEach((entry, id) => {
        if (entry.type === "activity") {
          entry.layer.setStyle({ weight: entry.defaultWeight, color: entry.defaultColor, opacity: 0.85 });
        } else if (entry.type === "visit") {
          entry.layer.setStyle({ radius: entry.defaultRadius, color: "#ffffff", weight: 2 });
        }
      });

      // Highlight selected layer
      const target = segmentLayerMap.get(segId);
      if (target) {
        if (target.type === "activity") {
          target.layer.setStyle({ weight: 9, color: "#06b6d4", opacity: 1 });
          target.layer.bringToFront();
        } else if (target.type === "visit") {
          target.layer.setStyle({ radius: target.defaultRadius + 4, color: "#06b6d4", weight: 4 });
        }
      }
    }

    // 1. Render Activities (Polylines with Continuous Visit Anchoring)
    sortedSegs.forEach((s, idx) => {
      if (s.segment_type === "activity") {
        const actType = (s.activity_type || "").toUpperCase();
        const color = ACTIVITY_COLORS[actType] || ACTIVITY_COLORS["DEFAULT"];

        let coords = [];
        if (s.path_points && s.path_points.length > 1) {
          coords = s.path_points.slice();
        } else if (s.latitude && s.end_lat) {
          coords = [[s.latitude, s.longitude], [s.end_lat, s.end_lng]];
        }

        if (coords.length > 0) {
          // Bridge visual gap to preceding visit
          const prevSeg = sortedSegs.slice(0, idx).reverse().find(x => x.segment_type === "visit" && x.latitude && x.longitude);
          if (prevSeg) {
            const d = coordDistMeters([prevSeg.latitude, prevSeg.longitude], coords[0]);
            if (d > 0.5 && d < 800) {
              coords.unshift([prevSeg.latitude, prevSeg.longitude]);
            }
          }

          // Bridge visual gap to succeeding visit
          const nextSeg = sortedSegs.slice(idx + 1).find(x => x.segment_type === "visit" && x.latitude && x.longitude);
          if (nextSeg) {
            const d = coordDistMeters(coords[coords.length - 1], [nextSeg.latitude, nextSeg.longitude]);
            if (d > 0.5 && d < 800) {
              coords.push([nextSeg.latitude, nextSeg.longitude]);
            }
          }

          const defaultWeight = s.has_snapped_path ? 5 : 3;
          const polyline = L.polyline(coords, {
            color: color,
            weight: defaultWeight,
            opacity: 0.85,
            dashArray: s.has_snapped_path ? null : "6, 8"
          });

          segmentLayerMap.set(s.id, { layer: polyline, type: "activity", defaultWeight: defaultWeight, defaultColor: color });

          polyline.on("click", () => selectSegment(s.id));
          polyline.on("mouseover", () => {
            polyline.setStyle({ weight: defaultWeight + 3, opacity: 1 });
          });
          polyline.on("mouseout", () => {
            const card = document.querySelector(`.item-card[data-id="${s.id}"]`);
            if (!card || !card.classList.contains("is-selected")) {
              polyline.setStyle({ weight: defaultWeight, color: color, opacity: 0.85 });
            }
          });

          polyline.bindPopup(`
            <div style="font-family:var(--font-sans);font-size:12px;">
              <strong style="color:${color};font-size:13px;"><i class="fa-solid ${ACTIVITY_ICONS[actType] || 'fa-route'}"></i> ${actType.replace(/_/g, ' ')}</strong>
              <p style="margin:4px 0 0 0;">${(s.distance_meters/1000).toFixed(1)} km in ${s.duration_minutes.toFixed(0)} mins</p>
              <p style="margin:2px 0 0 0;color:#94a3b8;font-size:11px;">${s.start_time.slice(11,16)} - ${s.end_time.slice(11,16)}</p>
              <p style="margin:2px 0 0 0;font-size:10px;color:${s.has_snapped_path ? '#34d399' : '#94a3b8'};">
                ${s.has_snapped_path ? '✓ Road-Snapped' : '⚠ Straight-Line Chord'}
              </p>
            </div>
          `);

          polyline.addTo(routeLayerGroup);
          coords.forEach(pt => bounds.push(pt));
        }
      }
    });

    // 2. Render Visits (Markers)
    segments.filter(s => s.segment_type === "visit").forEach(s => {
      if (s.latitude && s.longitude) {
        const isChild = s.hierarchy_level === 1;
        const cat = s.catalog_category || s.category || "Other / POI";
        let fillColor = "#3b82f6";
        if (cat === "Home & Residence") fillColor = "#10b981";
        else if (cat === "Work & Office") fillColor = "#8b5cf6";
        else if (cat === "Food & Drink") fillColor = "#f59e0b";
        else if (isChild) fillColor = "#06b6d4";

        const defaultRadius = isChild ? 6 : (cat === "Home & Residence" || cat === "Work & Office" ? 10 : 8);
        const marker = L.circleMarker([s.latitude, s.longitude], {
          radius: defaultRadius,
          fillColor: fillColor,
          color: "#ffffff",
          weight: 2,
          opacity: 1,
          fillOpacity: 0.9
        });

        segmentLayerMap.set(s.id, { layer: marker, type: "visit", defaultRadius: defaultRadius, fillColor: fillColor });

        marker.on("click", () => selectSegment(s.id));

        const title = s.place_name || s.catalog_place_name || "Home/Place";
        const addr = s.place_address || s.catalog_place_address || "";
        const rating = s.catalog_review_rating || s.review_rating;

        marker.bindPopup(`
          <div style="font-family:var(--font-sans);font-size:12px;">
            <strong style="color:${fillColor};font-size:13px;"><i class="fa-solid ${getPlaceIcon(title, cat, s.semantic_type)}"></i> ${title}</strong>
            ${rating ? `<div style="margin-top:2px;">${renderStars(rating)}</div>` : ''}
            ${addr ? `<p style="margin:4px 0 0 0;color:#cbd5e1;font-size:11px;">${addr}</p>` : ''}
            <p style="margin:4px 0 0 0;color:#94a3b8;font-size:11px;">${s.start_time.slice(11,16)} - ${s.end_time.slice(11,16)} (${s.duration_minutes.toFixed(0)} min)</p>
            <p style="color:#c084fc;font-size:10px;margin-top:2px;">${cat} · ${s.catalog_city || ''}</p>
            ${s.review_photos && s.review_photos.length ? `
              <div style="margin-top:6px;display:flex;gap:4px;overflow-x:auto;">
                ${s.review_photos.slice(0, 4).map(u => `
                  <img src="${getPhotoUrl(u, 100)}" style="width:36px;height:36px;object-fit:cover;border-radius:4px;border:1px solid #cbd5e1;" alt="Photo" loading="lazy" />
                `).join('')}
              </div>
            ` : ''}
          </div>
        `);

        marker.addTo(visitLayerGroup);
        bounds.push([s.latitude, s.longitude]);
      }
    });

    // Attach card click handlers for itinerary
    document.querySelectorAll(".item-card").forEach(card => {
      const sid = parseInt(card.getAttribute("data-id"), 10);
      if (sid) {
        card.addEventListener("click", () => selectSegment(sid));
        card.addEventListener("mouseenter", () => {
          const entry = segmentLayerMap.get(sid);
          if (entry && entry.type === "activity") {
            entry.layer.setStyle({ weight: entry.defaultWeight + 3, opacity: 1 });
            entry.layer.bringToFront();
          }
        });
        card.addEventListener("mouseleave", () => {
          if (!card.classList.contains("is-selected")) {
            const entry = segmentLayerMap.get(sid);
            if (entry && entry.type === "activity") {
              entry.layer.setStyle({ weight: entry.defaultWeight, color: entry.defaultColor, opacity: 0.85 });
            }
          }
        });
      }
    });

    // 3. Render Gaps
    gaps.forEach(g => {
      if (g.prev_lat && g.next_lat) {
        const gapLine = L.polyline([[g.prev_lat, g.prev_lng], [g.next_lat, g.next_lng]], {
          color: "#ef4444",
          weight: 2,
          opacity: 0.7,
          dashArray: "4, 6"
        });

        gapLine.bindPopup(`
          <div style="font-family:var(--font-sans);font-size:12px;color:#f87171;">
            <strong><i class="fa-solid fa-triangle-exclamation"></i> Timeline Gap</strong>
            <p style="margin:4px 0 0 0;">${g.duration_hours.toFixed(1)} hours missing (${g.start_time.slice(11,16)} - ${g.end_time.slice(11,16)})</p>
            <p style="margin:2px 0 0 0;color:#94a3b8;font-size:11px;">Jump distance: ${g.jump_distance_km ? g.jump_distance_km.toFixed(1) : 0} km</p>
          </div>
        `);

        gapLine.addTo(gapLayerGroup);
      }
    });

    // 4. Render Rich Breadcrumbs & Anomaly Fixes
    if (showRawSignals) {
      fetch(`/api/breadcrumbs?date=${dayData.date}`)
        .then(res => res.json())
        .then(data => {
          if (data.status === "SUCCESS") {
            const bcPoints = data.breadcrumbs || [];
            document.getElementById("count-breadcrumbs").textContent = bcPoints.length;
            
            // Draw Trajectory Polyline
            const validCoords = bcPoints.filter(p => !p.is_excluded && p.anomaly_type !== 'TELEPORTATION').map(p => [p.lat, p.lng]);
            if (validCoords.length > 1) {
              const trajLine = L.polyline(validCoords, {
                color: "#64748b",
                weight: 1.5,
                opacity: 0.5,
                dashArray: "3, 5"
              });
              trajLine.addTo(rawLayerGroup);
            }

            bcPoints.forEach(p => {
              let color = "#10b981"; // Normal emerald
              let radius = 3.5;
              let fillOpacity = 0.8;

              if (p.is_excluded) {
                color = "#64748b";
                radius = 2.5;
                fillOpacity = 0.4;
              } else if (p.anomaly_type === "TELEPORTATION") {
                color = "#ef4444"; // Bright red
                radius = 7;
              } else if (p.anomaly_type === "EXTREME_VELOCITY") {
                color = "#f97316"; // Orange
                radius = 5.5;
              } else if (p.anomaly_type === "MULTIPATH_BOUNCE") {
                color = "#eab308"; // Yellow
                radius = 5.5;
              } else if (p.anomaly_type === "DWELL_SCATTER") {
                color = "#a855f7"; // Purple
                radius = 4.5;
              }

              const dot = L.circleMarker([p.lat, p.lng], {
                radius: radius,
                fillColor: color,
                color: "#ffffff",
                weight: p.anomaly_type ? 2 : 1,
                fillOpacity: fillOpacity
              });

              const timeStr = new Date(p.timestamp * 1000).toISOString().slice(11, 19);
              dot.bindPopup(`
                <div style="font-family:var(--font-sans);font-size:12px;min-width:200px;">
                  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;">
                    <strong style="color:${color};font-size:13px;">
                      <i class="fa-solid fa-satellite-dish"></i> ${p.anomaly_type || 'Normal Fix'}
                    </strong>
                    <span style="font-size:10px;color:#94a3b8;">${timeStr} UTC</span>
                  </div>
                  <p style="margin:2px 0;font-size:11px;color:#cbd5e1;">Speed: <strong>${p.speed_kmh} km/h</strong> · Accuracy: ±${p.accuracy}m</p>
                  <p style="margin:2px 0;font-size:11px;color:#94a3b8;">Coord: ${p.lat.toFixed(6)}, ${p.lng.toFixed(6)}</p>
                  ${p.anomaly_reason ? `<p style="margin:4px 0;color:#f87171;font-size:11px;background:rgba(239,68,68,0.1);padding:4px 6px;border-radius:4px;">${p.anomaly_reason}</p>` : ''}
                  <div style="margin-top:8px;text-align:right;">
                    <button class="action-btn" style="padding:3px 8px;font-size:10px;background:${p.is_excluded ? '#10b981' : '#ef4444'};" onclick="toggleExcludeBreadcrumb(${p.id}, ${p.is_excluded ? 0 : 1})">
                      <i class="fa-solid ${p.is_excluded ? 'fa-rotate-left' : 'fa-ban'}"></i> ${p.is_excluded ? 'Restore Point' : 'Exclude Point'}
                    </button>
                  </div>
                </div>
              `);
              dot.addTo(rawLayerGroup);
            });
          }
        })
        .catch(err => console.error("Error loading breadcrumbs:", err));
    } else {
      document.getElementById("count-breadcrumbs").textContent = "0";
    }

    if (bounds.length > 0) {
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 15 });
    }
  }

  // Load LinkedIn-Style Life Periods Chronology
  async function loadLifePeriods() {
    const track = document.getElementById("life-periods-track-container");
    if (!track) return;

    try {
      const res = await fetch("/api/life-periods");
      const data = await res.json();
      if (data.status === "SUCCESS") {
        track.innerHTML = "";
        const periods = data.periods || [];
        
        periods.forEach(p => {
          const card = document.createElement("div");
          card.className = "life-period-card";
          const isHome = p.type === "HOME";
          const isEdu = p.type === "EDUCATION";
          const typeClass = isHome ? 'home' : (isEdu ? 'education' : 'work');
          const typeIcon = isHome ? 'fa-house-chimney' : (isEdu ? 'fa-graduation-cap' : 'fa-briefcase');
          const startY = p.start_date.slice(0, 4);
          const endY = p.is_current ? "Present" : p.end_date.slice(0, 4);

          card.innerHTML = `
            <div class="life-period-icon ${typeClass}">
              <i class="fa-solid ${typeIcon}"></i>
            </div>
            <div class="life-period-body">
              <div class="life-period-title-row">
                <span class="life-period-name">${p.name}</span>
                ${p.is_current ? '<span class="pill-badge green" style="font-size:10px;">Current</span>' : ''}
              </div>
              <div class="life-period-role">${p.role_title || (isHome ? 'Residence' : (isEdu ? 'Education' : 'Workplace'))}</div>
              <div class="life-period-dates"><i class="fa-regular fa-calendar"></i> ${startY} – ${endY}</div>
              <div class="life-period-addr">${p.address}</div>
            </div>
          `;

          card.addEventListener("click", () => {
            if (p.lat && p.lng) {
              switchTab("timeline", true);
              map.flyTo([p.lat, p.lng], 16, { duration: 0.8 });
            }
          });

          track.appendChild(card);
        });
      }
    } catch (e) {
      console.error("Error loading life periods:", e);
    }
  }

  const CATEGORY_MAP_COLORS = {
    "Travel & Transit": "#06b6d4",
    "Food & Drink": "#f59e0b",
    "Arts & Entertainment": "#a855f7",
    "Culture & Arts": "#a855f7",
    "Home & Residence": "#10b981",
    "Work & Office": "#3b82f6",
    "Shopping & Retail": "#ec4899",
    "Shopping": "#ec4899",
    "Hotels & Lodging": "#6366f1",
    "Services & Civic": "#64748b",
    "Health & Services": "#64748b",
    "Parks & Outdoors": "#22c55e",
    "Leisure & Park": "#22c55e"
  };

  // Places in-memory cache & state
  const placesCache = new Map();
  let cachedMapPoints = null;
  let currentPlacesQuery = "";

  async function loadAllPlacesMap(query = "") {
    if (!placesMap) return;
    const countLabel = document.getElementById("places-map-count-label");
    if (countLabel) countLabel.textContent = "Loading places map...";

    try {
      if (!cachedMapPoints) {
        const res = await fetch("/api/places/map-points?min_visits=1");
        const data = await res.json();
        if (data.status === "SUCCESS" && data.points) {
          cachedMapPoints = data.points;
        }
      }

      placesLayerGroup.clearLayers();
      let points = cachedMapPoints || [];

      // Filter in-memory for instant response
      if (currentCategory && currentCategory !== "ALL") {
        points = points.filter(p => p.category === currentCategory);
      }
      if (currentCity && currentCity !== "ALL") {
        points = points.filter(p => p.city === currentCity);
      }
      if (query) {
        const qLower = query.toLowerCase();
        points = points.filter(p => 
          (p.name || "").toLowerCase().includes(qLower) || 
          (p.address || "").toLowerCase().includes(qLower) ||
          (p.city || "").toLowerCase().includes(qLower)
        );
      }

      allPlacesMapData = points;

      if (countLabel) {
        countLabel.textContent = `${points.length.toLocaleString()} places plotted`;
      }

      const bounds = [];
      points.forEach(p => {
        if (!p.latitude || !p.longitude) return;
        bounds.push([p.latitude, p.longitude]);

        let color = CATEGORY_MAP_COLORS[p.category] || "#8b5cf6";
        if ((p.name || "").toLowerCase().includes("citi bike")) {
          color = "#06b6d4";
        } else if ((p.name || "").toLowerCase().includes("home")) {
          color = "#10b981";
        }

        const visits = p.visit_count || 1;
        const radius = Math.max(4, Math.min(13, 3.5 + Math.log2(visits + 1) * 1.5));

        const marker = L.circleMarker([p.latitude, p.longitude], {
          renderer: placesCanvasRenderer,
          radius: radius,
          fillColor: color,
          color: "#ffffff",
          weight: 1,
          opacity: 0.9,
          fillOpacity: 0.75
        });

        const catIcon = getPlaceIcon(p.name, p.category);
        const stars = renderStars(p.review_rating);
        const firstDate = (p.first_visit_time || "").slice(0, 10);
        const lastDate = (p.last_visit_time || "").slice(0, 10);
        const dateRangeStr = (firstDate && lastDate) ? (firstDate === lastDate ? firstDate : `${firstDate} → ${lastDate}`) : "";

        marker.bindPopup(`
          <div class="place-map-popup" style="min-width:220px;max-width:280px;font-family:var(--font-sans);color:var(--text-main);">
            <div style="font-weight:700;font-size:13px;color:var(--text-main);margin-bottom:2px;">
              <i class="fa-solid ${catIcon}" style="color:${color};margin-right:4px;"></i> ${escapeHtml(p.name || 'Place')}
            </div>
            ${stars ? `<div style="margin-bottom:4px;">${stars}</div>` : ''}
            <div style="font-size:11px;color:var(--text-muted);margin-bottom:6px;line-height:1.3;">
              ${escapeHtml(p.address || `${p.latitude.toFixed(4)}, ${p.longitude.toFixed(4)}`)}
            </div>
            <div style="display:flex;gap:6px;flex-wrap:wrap;font-size:10.5px;margin-bottom:8px;">
              <span style="background:${color}20;color:${color};padding:2px 6px;border-radius:4px;font-weight:600;">${escapeHtml(p.category || 'POI')}</span>
              <span style="background:var(--bg-main);border:1px solid var(--border-color);padding:2px 6px;border-radius:4px;font-weight:600;"><strong>${visits}</strong> visits</span>
            </div>
            ${dateRangeStr ? `<div style="font-size:10px;color:var(--text-muted);margin-bottom:6px;"><i class="fa-regular fa-calendar"></i> ${dateRangeStr}</div>` : ''}
            <div style="display:flex;gap:6px;margin-top:4px;">
              <button class="btn btn-sm btn-primary" style="flex:1;font-size:11px;padding:4px 8px;cursor:pointer;" onclick="openPlaceVisitsModal('${p.place_id}', '${escapeHtml(p.name || '').replace(/'/g, "\\'")}')">
                <i class="fa-solid fa-list"></i> All Visits (${visits})
              </button>
              ${lastDate ? `
                <button class="btn btn-sm btn-secondary" style="font-size:11px;padding:4px 8px;cursor:pointer;" onclick="window.jumpToTimelineDay('${lastDate}', true, 'places')">
                  <i class="fa-solid fa-route"></i> Last Visit
                </button>
              ` : ''}
            </div>
          </div>
        `);

        marker.addTo(placesLayerGroup);
      });

      // If filtered and bounds exist, fit bounds
      if ((query || currentCity !== "ALL" || (currentCategory && currentCategory !== "ALL")) && bounds.length > 0) {
        placesMap.fitBounds(L.latLngBounds(bounds), { maxZoom: 15, padding: [30, 30] });
      }
    } catch (e) {
      console.error("Error loading places map:", e);
      if (countLabel) countLabel.textContent = "Error loading places map";
    }
  }

  // Load Places Catalog with Category & City Filtering and in-memory caching
  async function loadPlaces(query = "") {
    currentPlacesQuery = query;
    loadLifePeriods();
    loadAllPlacesMap(query);

    const grid = document.getElementById("places-grid-container");
    const cacheKey = `${query}_${currentCategory}_${currentCity}_${reviewedOnly}_${currentSort}`;

    // Render immediately from cache if available
    if (placesCache.has(cacheKey)) {
      renderPlacesData(placesCache.get(cacheKey));
      return;
    }

    grid.innerHTML = '<div class="loading-spinner"><i class="fa-solid fa-circle-notch fa-spin"></i> Loading Places Catalog...</div>';
    const url = `/api/places?q=${encodeURIComponent(query)}&category=${encodeURIComponent(currentCategory)}&city=${encodeURIComponent(currentCity)}&reviewed_only=${reviewedOnly ? 1 : 0}&sort_by=${currentSort}&limit=120&min_visits=1`;

    try {
      const res = await fetch(url);
      const data = await res.json();
      if (data.status === "SUCCESS") {
        placesCache.set(cacheKey, data);
        renderPlacesData(data);
      }
    } catch (e) {
      console.error("Error loading places:", e);
      grid.innerHTML = `<div class="empty-state">Error loading places: ${escapeHtml(e.message)}</div>`;
    }
  }

  function renderPlacesData(data) {
    const grid = document.getElementById("places-grid-container");
    if (!grid) return;

    const pillsContainer = document.getElementById("category-pills-container");
    if (pillsContainer && data.categories) {
      pillsContainer.innerHTML = `<button class="cat-pill ${currentCategory === 'ALL' ? 'active' : ''}" data-cat="ALL">All Categories</button>`;
      data.categories.forEach(c => {
        const btn = document.createElement("button");
        btn.className = `cat-pill ${currentCategory === c.category ? 'active' : ''}`;
        btn.setAttribute("data-cat", c.category);
        const icon = CATEGORY_ICONS[c.category] || 'fa-tag';
        btn.innerHTML = `<i class="fa-solid ${icon}"></i> ${c.category} (${c.cnt})`;
        btn.addEventListener("click", () => {
          document.querySelectorAll(".cat-pill").forEach(p => p.classList.remove("active"));
          btn.classList.add("active");
          currentCategory = c.category;
          loadPlaces(currentPlacesQuery);
        });
        pillsContainer.appendChild(btn);
      });
      pillsContainer.querySelector('[data-cat="ALL"]')?.addEventListener("click", () => {
        document.querySelectorAll(".cat-pill").forEach(p => p.classList.remove("active"));
        pillsContainer.querySelector('[data-cat="ALL"]').classList.add("active");
        currentCategory = "ALL";
        loadPlaces(currentPlacesQuery);
      });
    }

    const citySelect = document.getElementById("places-city-select");
    if (citySelect && data.cities && citySelect.options.length <= 1) {
      data.cities.forEach(ct => {
        if (ct.city && ct.city !== 'Unknown') {
          const opt = document.createElement("option");
          opt.value = ct.city;
          opt.textContent = `${ct.city} (${ct.cnt || ct.places_cnt} places, ${ct.visits} visits)`;
          citySelect.appendChild(opt);
        }
      });
    }

    grid.innerHTML = "";
    if (data.places.length === 0) {
      grid.innerHTML = '<div class="empty-state" style="grid-column: 1 / -1;"><p>No places found matching current filter.</p></div>';
      return;
    }

    data.places.forEach(p => {
      const card = document.createElement("div");
      card.className = "place-card";
      const cat = p.category || "Other / POI";
      const catIcon = getPlaceIcon(p.name, cat, p.semantic_type);
      const stars = renderStars(p.review_rating);

      card.innerHTML = `
        <div>
          <div class="place-header">
            <div>
              <span class="place-name">${escapeHtml(p.name || 'Place')}</span>
              ${stars ? `<div style="margin-top:2px;">${stars}</div>` : ''}
            </div>
            <span class="place-visits" style="cursor:pointer;" title="Click to view all ${p.visit_count} visits">${p.visit_count} visits</span>
          </div>
          <div class="place-address" style="margin-top:6px;">${escapeHtml(p.address || (p.latitude ? `${p.latitude.toFixed(4)}, ${p.longitude.toFixed(4)}` : 'No address'))}</div>
          ${p.review_text ? `<div class="review-snippet-box">"${escapeHtml(p.review_text.slice(0, 100))}..."</div>` : ''}
          ${p.review_photos && p.review_photos.length ? `
            <div class="review-photos-strip" style="margin-top:6px;">
              ${p.review_photos.map((url, idx) => `
                <div class="review-photo-thumb-wrapper places-photo-thumb" data-idx="${idx}" title="View photo (${idx+1}/${p.review_photos.length})">
                  <img class="review-photo-thumb" style="width:48px;height:48px;" src="${getPhotoUrl(url, 200)}" alt="Place photo" loading="lazy" referrerpolicy="no-referrer" onerror="this.parentElement.style.display='none'" />
                </div>
              `).join('')}
            </div>
          ` : ''}
        </div>
        <div class="place-footer">
          <div style="display:flex;gap:4px;flex-wrap:wrap;">
            <span class="tag-badge category-tag"><i class="fa-solid ${catIcon}"></i> ${cat}</span>
            ${p.city && p.city !== 'Unknown' ? `<span class="tag-badge city-tag">${escapeHtml(p.city)}</span>` : ''}
          </div>
          <div style="display:flex;gap:6px;">
            <button class="btn-primary list-visits-btn" style="padding:4px 8px;font-size:11px;" title="View complete visit history"><i class="fa-solid fa-list"></i> Visits</button>
            <button class="btn-secondary view-place-btn" style="padding:4px 8px;font-size:11px;" title="Fly to location on map"><i class="fa-solid fa-map-pin"></i> View</button>
          </div>
        </div>
      `;

      card.querySelectorAll(".places-photo-thumb").forEach(thumb => {
        thumb.addEventListener("click", (e) => {
          e.preventDefault();
          e.stopPropagation();
          const idx = parseInt(thumb.getAttribute("data-idx") || "0", 10);
          window.openPhotoLightbox(p.review_photos || [], idx, p.name || 'Place', p.review_text || "");
        });
      });

      card.querySelector(".view-place-btn")?.addEventListener("click", (e) => {
        e.stopPropagation();
        if (p.latitude && p.longitude && placesMap) {
          placesMap.flyTo([p.latitude, p.longitude], 17, { duration: 0.8 });
          document.getElementById("places-map")?.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      });

      card.querySelector(".list-visits-btn")?.addEventListener("click", (e) => {
        e.stopPropagation();
        openPlaceVisitsModal(p.place_id, p.name);
      });

      card.querySelector(".place-visits")?.addEventListener("click", (e) => {
        e.stopPropagation();
        openPlaceVisitsModal(p.place_id, p.name);
      });

      card.addEventListener("click", () => {
        openPlaceVisitsModal(p.place_id, p.name);
      });

      grid.appendChild(card);
    });
  }

  // Place Visits History Modal
  window.openPlaceVisitsModal = openPlaceVisitsModal;
  async function openPlaceVisitsModal(placeId, placeName) {
    const modal = document.getElementById("place-visits-modal");
    const body = document.getElementById("place-visits-body");
    const titleEl = document.getElementById("place-visits-title");
    const subEl = document.getElementById("place-visits-subtitle");
    if (!modal || !body) return;

    modal.style.display = "flex";
    modal.classList.remove("hidden");
    if (titleEl) titleEl.textContent = placeName || "Place Visits";
    if (subEl) subEl.textContent = "Loading visit records...";
    body.innerHTML = '<div class="loading-spinner" style="padding:40px;text-align:center;"><i class="fa-solid fa-circle-notch fa-spin"></i> Loading all visit records...</div>';

    try {
      const res = await fetch(`/api/places/visits?place_id=${encodeURIComponent(placeId)}`);
      const data = await res.json();

      if (data.status !== "SUCCESS" || !data.visits) {
        body.innerHTML = '<div class="empty-state">No visits recorded for this place.</div>';
        return;
      }

      if (titleEl) titleEl.textContent = data.place?.name || placeName || "Place Visits";
      if (subEl) {
        const addr = data.place?.address ? ` · ${data.place.address}` : '';
        subEl.textContent = `${data.count} total recorded visits${addr}`;
      }

      if (data.visits.length === 0 && (!data.photos || data.photos.length === 0)) {
        body.innerHTML = '<div class="empty-state">No visits found.</div>';
        return;
      }

      let photosHtml = '';
      if (data.photos && data.photos.length > 0) {
        const photoUrls = data.photos.map(p => p.preview_url);
        photosHtml = `
          <div class="place-photos-modal-strip" style="margin-bottom:14px;padding:10px 12px;background:var(--bg-subtle);border-radius:8px;border:1px solid var(--border-color);">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
              <span style="font-size:12px;font-weight:600;color:var(--text-main);"><i class="fa-solid fa-camera" style="color:#0284c7;"></i> Photos at this Place (${data.photos.length})</span>
              <span class="modal-photos-view-all-btn" style="font-size:11px;color:var(--text-muted);cursor:pointer;">View Fullscreen <i class="fa-solid fa-expand"></i></span>
            </div>
            <div style="display:flex;gap:8px;overflow-x:auto;padding-bottom:4px;">
              ${data.photos.map((p, pIdx) => `
                <div class="review-photo-thumb-wrapper modal-place-photo-thumb" data-idx="${pIdx}" title="${escapeHtml(p.filename || '')} (${p.local_date || ''})">
                  <img src="${getPhotoUrl(p.preview_url, 160)}" style="width:56px;height:56px;object-fit:cover;border-radius:6px;cursor:pointer;" alt="Photo" loading="lazy" />
                </div>
              `).join('')}
            </div>
          </div>
        `;
      }

      let html = photosHtml + `
        <div class="place-visits-table-wrapper" style="overflow-x:auto;">
          <table class="table" style="width:100%;font-size:12.5px;border-collapse:collapse;">
            <thead>
              <tr style="border-bottom:1px solid var(--border-color);text-align:left;color:var(--text-muted);font-size:11px;text-transform:uppercase;">
                <th style="padding:8px 10px;">#</th>
                <th style="padding:8px 10px;">Date</th>
                <th style="padding:8px 10px;">Time Window</th>
                <th style="padding:8px 10px;">Duration</th>
                <th style="padding:8px 10px;text-align:right;">Action</th>
              </tr>
            </thead>
            <tbody>
      `;

      data.visits.forEach((v, idx) => {
        const startStr = v.start_time ? v.start_time.slice(11, 16) : '--:--';
        const endStr = v.end_time ? v.end_time.slice(11, 16) : '--:--';
        const durMin = Math.round(v.duration_minutes || 0);
        let durStr = `${durMin} min`;
        if (durMin >= 60) {
          const hrs = Math.floor(durMin / 60);
          const rem = durMin % 60;
          durStr = rem > 0 ? `${hrs}h ${rem}m` : `${hrs}h`;
        }

        html += `
          <tr style="border-bottom:1px solid var(--border-color);transition:background 0.15s;" onmouseover="this.style.background='var(--bg-subtle)'" onmouseout="this.style.background='transparent'">
            <td style="padding:8px 10px;color:var(--text-muted);font-family:var(--font-mono);font-size:11px;">${idx + 1}</td>
            <td style="padding:8px 10px;font-weight:600;color:var(--text-main);font-family:var(--font-mono);">${v.date}</td>
            <td style="padding:8px 10px;color:var(--text-muted);">${startStr} – ${endStr}</td>
            <td style="padding:8px 10px;"><span class="tag-badge" style="font-size:11px;background:rgba(59,130,246,0.12);color:var(--accent-blue);font-weight:600;">${durStr}</span></td>
            <td style="padding:8px 10px;text-align:right;">
              <button class="btn btn-sm btn-primary" style="padding:4px 10px;font-size:11px;cursor:pointer;" onclick="closePlaceVisitsModal(); window.jumpToTimelineDay('${v.date}', true, 'places')">
                <i class="fa-solid fa-route"></i> Jump
              </button>
            </td>
          </tr>
        `;
      });

      html += `
            </tbody>
          </table>
        </div>
      `;

      body.innerHTML = html;

      body.querySelector(".modal-photos-view-all-btn")?.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        const pUrls = (data.photos || []).map(p => p.preview_url);
        window.openPhotoLightbox(pUrls, 0, data.place?.name || placeName || 'Place', '');
      });

      body.querySelectorAll(".modal-place-photo-thumb").forEach(thumb => {
        thumb.addEventListener("click", (e) => {
          e.preventDefault();
          e.stopPropagation();
          const pIdx = parseInt(thumb.getAttribute("data-idx") || "0", 10);
          const p = (data.photos || [])[pIdx] || {};
          const pUrls = (data.photos || []).map(x => x.preview_url);
          window.openPhotoLightbox(pUrls, pIdx, data.place?.name || placeName || 'Place', p.local_date || '');
        });
      });
    } catch (e) {
      console.error("Error loading place visits:", e);
      body.innerHTML = `<div class="empty-state">Error loading visit history: ${escapeHtml(e.message)}</div>`;
    }
  }

  window.closePlaceVisitsModal = closePlaceVisitsModal;
  function closePlaceVisitsModal() {
    const modal = document.getElementById("place-visits-modal");
    if (modal) {
      modal.style.display = "none";
      modal.classList.add("hidden");
    }
  }

  document.getElementById("btn-close-place-visits")?.addEventListener("click", closePlaceVisitsModal);
  document.getElementById("btn-done-place-visits")?.addEventListener("click", closePlaceVisitsModal);

  // Load Contributor Reviews Tab
  async function loadReviews(query = "") {
    const grid = document.getElementById("reviews-grid-container");
    grid.innerHTML = '<div class="loading-spinner"><i class="fa-solid fa-circle-notch fa-spin"></i> Loading Reviews...</div>';

    try {
      const res = await fetch("/api/reviews");
      const data = await res.json();

      if (data.status === "SUCCESS") {
        grid.innerHTML = "";
        let reviews = data.reviews || [];
        if (query) {
          reviews = reviews.filter(r => (r.review_text || "").toLowerCase().includes(query.toLowerCase()) || (r.place_name || "").toLowerCase().includes(query.toLowerCase()));
        }

        reviews.forEach(r => {
          const card = document.createElement("div");
          card.className = "review-card";
          const stars = renderStars(r.rating);
          const photos = r.photo_urls || [];
          const placeName = r.place_name || r.current_poi_name || 'Place';
          const reviewText = r.review_text || '';

          card.innerHTML = `
            <div>
              <div class="review-top">
                <strong style="font-size:14px;color:#f8fafc;">${escapeHtml(placeName)}</strong>
                <span style="font-size:11px;color:#94a3b8;">${r.date ? r.date.slice(0, 10) : ''}</span>
              </div>
              <div style="margin:4px 0 8px 0;display:flex;align-items:center;justify-content:space-between;">
                <div>${stars}</div>
                ${photos.length ? `<span class="tag-badge" style="font-size:10.5px;background:rgba(59,130,246,0.15);color:#60a5fa;"><i class="fa-solid fa-camera"></i> ${photos.length} photo${photos.length > 1 ? 's' : ''}</span>` : ''}
              </div>
              <div class="review-body-text">"${escapeHtml(reviewText || 'No review comments.')}"</div>
              ${photos.length ? `
                <div class="review-photos-grid">
                  ${photos.map((url, idx) => `
                    <div class="review-photo-thumb-wrapper review-tab-photo-thumb" data-idx="${idx}" title="View photo (${idx+1}/${photos.length})">
                      <img class="review-photo-thumb" src="${getPhotoUrl(url, 360)}" alt="Review photo ${idx+1}" loading="lazy" referrerpolicy="no-referrer" onerror="this.parentElement.style.display='none'" />
                    </div>
                  `).join('')}
                </div>
              ` : ''}
            </div>
            <div class="place-footer">
              <span class="tag-badge"><i class="fa-solid fa-location-dot"></i> ${r.current_poi_address ? r.current_poi_address.split(',')[0] : 'Visited'}</span>
              ${r.google_maps_url ? `<a href="${r.google_maps_url}" target="_blank" class="tag-badge snapped" style="text-decoration:none;"><i class="fa-solid fa-arrow-up-right-from-square"></i> Google Maps</a>` : ''}
            </div>
          `;

          card.querySelectorAll(".review-tab-photo-thumb").forEach(thumb => {
            thumb.addEventListener("click", (e) => {
              e.preventDefault();
              e.stopPropagation();
              const idx = parseInt(thumb.getAttribute("data-idx") || "0", 10);
              window.openPhotoLightbox(photos, idx, placeName, reviewText);
            });
          });

          grid.appendChild(card);
        });
      }
    } catch (e) {
      console.error("Error loading reviews:", e);
    }
  }

  // Load Diagnostics Gaps
  async function loadDiagnosticsGaps() {
    const minHours = document.getElementById("gap-filter-duration").value;
    const tbody = document.getElementById("gaps-table-body");
    tbody.innerHTML = '<tr><td colspan="8" class="text-center">Loading gaps...</td></tr>';

    try {
      const res = await fetch(`/api/diagnostics/gaps?min_hours=${minHours}&limit=100`);
      const data = await res.json();

      if (data.status === "SUCCESS") {
        tbody.innerHTML = "";
        data.gaps.forEach(g => {
          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td><strong>${g.date}</strong></td>
            <td><span class="tag-badge" style="color:#f87171;font-weight:700;">${g.duration_hours.toFixed(1)}h</span></td>
            <td style="font-family:var(--font-mono);font-size:11px;">${g.start_time.slice(11,16)} - ${g.end_time.slice(11,16)}</td>
            <td>${g.prev_place_name || g.prev_act_type || 'Unknown location'}</td>
            <td>${g.next_place_name || g.next_act_type || 'Unknown location'}</td>
            <td>${g.jump_distance_km ? `${g.jump_distance_km.toFixed(1)} km` : 'Stationary'}</td>
            <td>${g.raw_signals_count > 0 ? `<span class="tag-badge snapped">${g.raw_signals_count} fixes</span>` : '<span style="color:var(--text-dim)">0</span>'}</td>
            <td><button class="btn-secondary jump-date-btn" data-date="${g.date}" style="padding:4px 8px;font-size:11px;"><i class="fa-solid fa-eye"></i> View Day</button></td>
          `;
          tr.querySelector(".jump-date-btn")?.addEventListener("click", () => {
            jumpToTimelineDay(g.date, true);
          });
          tbody.appendChild(tr);
        });
      }
    } catch (e) {
      console.error("Error loading gaps:", e);
    }
  }

  // Load Speed Anomalies
  async function loadSpeedAnomalies() {
    const tbody = document.getElementById("speed-table-body");
    tbody.innerHTML = '<tr><td colspan="7" class="text-center"><i class="fa-solid fa-circle-notch fa-spin"></i> Loading speed outliers...</td></tr>';

    try {
      const res = await fetch("/api/diagnostics/anomalies");
      const data = await res.json();

      if (data.status === "SUCCESS") {
        tbody.innerHTML = "";
        const speedItems = (data.anomalies || []).filter(a => a.anomaly_type === "SPEED_OUTLIER");
        if (speedItems.length === 0) {
          tbody.innerHTML = '<tr><td colspan="7" class="text-center" style="color:var(--text-muted);">No speed outliers found.</td></tr>';
          return;
        }
        speedItems.forEach(a => {
          let dt = {};
          if (typeof a.data_json === "string") {
            try { dt = JSON.parse(a.data_json || "{}"); } catch(e) { dt = {}; }
          } else if (a.data_json) {
            dt = a.data_json;
          }
          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td><strong>${a.date || 'N/A'}</strong></td>
            <td><span class="tag-badge">${dt.activity_type || 'Movement'}</span></td>
            <td><span class="tag-badge" style="color:#c084fc;font-weight:700;">${dt.speed_kmh ? dt.speed_kmh.toFixed(1) + ' km/h' : 'High Speed'}</span></td>
            <td>${dt.distance_km ? dt.distance_km.toFixed(1) + ' km' : '--'}</td>
            <td>${dt.duration_min ? Math.round(dt.duration_min) + ' min' : '--'}</td>
            <td style="font-size:12px;color:var(--text-muted);">${a.description || 'Velocity anomaly'}</td>
            <td><button class="btn-secondary jump-date-btn" data-date="${a.date}" style="padding:4px 8px;font-size:11px;cursor:pointer;"><i class="fa-solid fa-eye"></i> View Day</button></td>
          `;
          tr.querySelector(".jump-date-btn")?.addEventListener("click", () => {
            jumpToTimelineDay(a.date, true);
          });
          tbody.appendChild(tr);
        });
      }
    } catch (e) {
      console.error("Error loading speed anomalies:", e);
      tbody.innerHTML = `<tr><td colspan="7" class="text-center" style="color:#ef4444;">Failed to load speed anomalies: ${e.message}</td></tr>`;
    }
  }

  // Load Unconfirmed Places
  async function loadUnconfirmedPlaces() {
    const tbody = document.getElementById("unconf-table-body");
    tbody.innerHTML = '<tr><td colspan="7" class="text-center"><i class="fa-solid fa-circle-notch fa-spin"></i> Loading unconfirmed visits...</td></tr>';

    try {
      const res = await fetch("/api/diagnostics/unconfirmed?limit=100");
      const data = await res.json();

      if (data.status === "SUCCESS") {
        tbody.innerHTML = "";
        const unconfList = data.unconfirmed || [];
        if (unconfList.length === 0) {
          tbody.innerHTML = '<tr><td colspan="7" class="text-center" style="color:var(--text-muted);">No unconfirmed visits found. 100% of visits are hydrated.</td></tr>';
          return;
        }
        unconfList.forEach(u => {
          const stTime = u.start_time ? (u.start_time.includes("T") ? u.start_time.slice(11, 16) : u.start_time) : "--:--";
          const etTime = u.end_time ? (u.end_time.includes("T") ? u.end_time.slice(11, 16) : u.end_time) : "--:--";
          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td><strong>${u.date || 'N/A'}</strong></td>
            <td style="font-family:var(--font-mono);">${stTime} - ${etTime}</td>
            <td style="font-family:var(--font-mono);font-size:11px;">${u.place_id ? u.place_id.slice(0, 18) + '...' : 'Raw GPS Dwell'}</td>
            <td><span class="tag-badge">${u.category || 'Other / POI'}</span></td>
            <td>${u.city || 'N/A'}</td>
            <td>${u.probability ? (u.probability * 100).toFixed(0) + '%' : '100%'}</td>
            <td><button class="btn-secondary jump-date-btn" data-date="${u.date}" style="padding:4px 8px;font-size:11px;cursor:pointer;"><i class="fa-solid fa-eye"></i> View Day</button></td>
          `;
          tr.querySelector(".jump-date-btn")?.addEventListener("click", () => {
            jumpToTimelineDay(u.date, true);
          });
          tbody.appendChild(tr);
        });
      }
    } catch (e) {
      console.error("Error loading unconfirmed places:", e);
      tbody.innerHTML = `<tr><td colspan="7" class="text-center" style="color:#ef4444;">Failed to load unconfirmed visits: ${e.message}</td></tr>`;
    }
  }

  let heatmapPoiLayerGroup = L.layerGroup();

  // Load World Heatmap & Fog-of-War Discovery
  async function loadWorldHeatmap() {
    try {
      const mapEl = document.getElementById("heatmap-map");
      if (!mapEl) return;
      if (heatMap) heatMap.invalidateSize(true);

      const res = await fetch("/api/heatmap");
      const data = await res.json();

      if (data.status === "SUCCESS" && data.points && data.points.length > 0) {
        if (heatLayer && heatMap) heatMap.removeLayer(heatLayer);
        if (heatMap) {
          heatLayer = L.heatLayer(data.points, {
            radius: 12,
            blur: 16,
            maxZoom: 13,
            max: 15,
            gradient: { 0.2: '#3b82f6', 0.5: '#10b981', 0.8: '#f59e0b', 1.0: '#ef4444' }
          }).addTo(heatMap);
        }
      }

      if (heatMap) {
        if (!heatMap.hasLayer(heatmapPoiLayerGroup)) heatmapPoiLayerGroup.addTo(heatMap);
        heatMap.off("zoomend", updateHeatmapZoomLayers);
        heatMap.on("zoomend", updateHeatmapZoomLayers);
        updateHeatmapZoomLayers();
      }
    } catch (e) {
      console.error("Error loading heatmap:", e);
    }
  }

  async function updateHeatmapZoomLayers() {
    if (!heatMap) return;
    const mapEl = document.getElementById("heatmap-map");
    if (!mapEl || mapEl.clientWidth === 0 || mapEl.clientHeight === 0) return;

    const currentZoom = heatMap.getZoom();
    heatmapPoiLayerGroup.clearLayers();

    if (currentZoom >= 13) {
      const bounds = heatMap.getBounds();
      try {
        const pRes = await fetch(`/api/places?limit=250`);
        const pData = await pRes.json();
        if (pData.status === "SUCCESS" && pData.places) {
          pData.places.forEach(p => {
            if (p.latitude && p.longitude && bounds.contains([p.latitude, p.longitude])) {
              const marker = L.circleMarker([p.latitude, p.longitude], {
                radius: 5,
                fillColor: '#38bdf8',
                color: '#ffffff',
                weight: 1.5,
                fillOpacity: 0.9
              });
              marker.bindPopup(`
                <div style="font-size:12px;color:#0f172a;min-width:140px;">
                  <strong style="color:#0f172a;">${p.name || 'Visited Place'}</strong>
                  <div style="font-size:11px;color:#64748b;margin:2px 0;">${p.address || ''}</div>
                  <div style="font-size:10px;font-weight:600;color:#3b82f6;">${p.visit_count || 1} lifetime visits · ${p.category || 'POI'}</div>
                </div>
              `);
              heatmapPoiLayerGroup.addLayer(marker);
            }
          });
        }
      } catch (err) {
        console.error("Error loading POIs for heatmap:", err);
      }
    }
  }

  let currentFixesFilter = "PENDING";

  // Load Fix Proposals
  async function loadFixProposals() {
    const list = document.getElementById("fixes-list-container");
    list.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-muted);"><i class="fa-solid fa-circle-notch fa-spin"></i> Loading fix proposals...</div>';

    try {
      const res = await fetch(`/api/fixes?status=${encodeURIComponent(currentFixesFilter)}`);
      const data = await res.json();
      if (data.status === "SUCCESS") {
        const fixes = data.fixes || [];
        const counts = data.counts || { pending: 0, accepted: 0, rejected: 0, total: 0 };
        const badge = document.getElementById("badge-fixes");
        if (badge) badge.textContent = (counts.pending || 0).toLocaleString();

        const pendingCount = counts.pending || 0;
        const airportCount = fixes.filter(f => f.status === "PENDING" && (f.proposed_action === "INSERT_ORIGIN_AIRPORT" || f.proposed_action === "INSERT_DESTINATION_AIRPORT")).length;
        const fitCount = fixes.filter(f => f.status === "PENDING" && f.proposed_action === "SYNTHESIZE_FIT_ACTIVITY").length;
        const dwellCount = fixes.filter(f => f.status === "PENDING" && f.proposed_action === "EXTEND_STATIONARY_DWELL").length;
        const breadcrumbCount = fixes.filter(f => f.status === "PENDING" && f.proposed_action === "RECONSTRUCT_FROM_BREADCRUMBS").length;
        const hiatusCount = fixes.filter(f => f.status === "PENDING" && f.proposed_action === "DOCUMENTED_HIATUS").length;

        list.innerHTML = `
          <!-- Status Filter Tabs & Purge Button Toolbar -->
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;flex-wrap:wrap;gap:10px;">
            <div class="filter-pills" style="display:flex;gap:6px;">
              <button class="pill-btn ${currentFixesFilter === 'PENDING' ? 'active' : ''}" data-filter="PENDING" style="padding:6px 14px;font-size:12px;border-radius:16px;border:1px solid var(--border-color);background:${currentFixesFilter === 'PENDING' ? 'var(--accent-blue)' : 'var(--bg-card)'};color:${currentFixesFilter === 'PENDING' ? '#fff' : 'var(--text-main)'};cursor:pointer;font-weight:600;">
                <i class="fa-solid fa-clock"></i> Pending (${counts.pending})
              </button>
              <button class="pill-btn ${currentFixesFilter === 'ALL' ? 'active' : ''}" data-filter="ALL" style="padding:6px 14px;font-size:12px;border-radius:16px;border:1px solid var(--border-color);background:${currentFixesFilter === 'ALL' ? 'var(--accent-blue)' : 'var(--bg-card)'};color:${currentFixesFilter === 'ALL' ? '#fff' : 'var(--text-main)'};cursor:pointer;font-weight:600;">
                All History (${counts.total})
              </button>
              <button class="pill-btn ${currentFixesFilter === 'ACCEPTED' ? 'active' : ''}" data-filter="ACCEPTED" style="padding:6px 14px;font-size:12px;border-radius:16px;border:1px solid var(--border-color);background:${currentFixesFilter === 'ACCEPTED' ? 'var(--accent-green)' : 'var(--bg-card)'};color:${currentFixesFilter === 'ACCEPTED' ? '#fff' : 'var(--text-main)'};cursor:pointer;font-weight:600;">
                <i class="fa-solid fa-check"></i> Accepted (${counts.accepted})
              </button>
              <button class="pill-btn ${currentFixesFilter === 'REJECTED' ? 'active' : ''}" data-filter="REJECTED" style="padding:6px 14px;font-size:12px;border-radius:16px;border:1px solid var(--border-color);background:${currentFixesFilter === 'REJECTED' ? 'var(--accent-red)' : 'var(--bg-card)'};color:${currentFixesFilter === 'REJECTED' ? '#fff' : 'var(--text-main)'};cursor:pointer;font-weight:600;">
                <i class="fa-solid fa-xmark"></i> Rejected (${counts.rejected})
              </button>
            </div>
            ${(counts.accepted > 0 || counts.rejected > 0) ? `
              <button id="btn-purge-fixes" class="btn-secondary" style="padding:6px 12px;font-size:12px;color:var(--accent-red);border-radius:16px;cursor:pointer;" title="Permanently delete accepted and rejected proposal records from history">
                <i class="fa-solid fa-trash-can"></i> Clear Resolved History (${counts.accepted + counts.rejected})
              </button>
            ` : ''}
          </div>

          ${(currentFixesFilter === 'PENDING' && pendingCount > 0) ? `
            <div style="background:var(--bg-card);border:1px solid var(--border-color);border-radius:12px;padding:16px 20px;margin-bottom:16px;box-shadow:var(--shadow-sm);">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                <div>
                  <strong style="font-size:14px;color:var(--text-main);"><i class="fa-solid fa-layer-group" style="color:var(--accent-blue);"></i> Batch Proposal Actions</strong>
                  <span style="font-size:12px;color:var(--text-muted);margin-left:8px;">(${pendingCount} pending proposals)</span>
                </div>
              </div>
              <div style="display:flex;gap:10px;flex-wrap:wrap;">
                ${airportCount > 0 ? `
                  <button class="btn-primary batch-airport-btn" style="background:#1a73e8;font-size:12px;padding:7px 14px;cursor:pointer;">
                    <i class="fa-solid fa-plane-arrival"></i> Accept All ${airportCount} Airport Continuity Patches
                  </button>
                ` : ''}
                ${fitCount > 0 ? `
                  <button class="btn-primary batch-fit-btn" style="background:#f59e0b;font-size:12px;padding:7px 14px;cursor:pointer;">
                    <i class="fa-solid fa-person-running"></i> Accept All ${fitCount} Google Fit Workouts
                  </button>
                ` : ''}
                ${dwellCount > 0 ? `
                  <button class="btn-primary batch-dwell-btn" style="background:#10b981;font-size:12px;padding:7px 14px;cursor:pointer;">
                    <i class="fa-solid fa-house-user"></i> Accept All ${dwellCount} Home/Dwell Extensions
                  </button>
                ` : ''}
                ${breadcrumbCount > 0 ? `
                  <button class="btn-primary batch-bc-btn" style="background:#8b5cf6;font-size:12px;padding:7px 14px;cursor:pointer;">
                    <i class="fa-solid fa-satellite-dish"></i> Accept All ${breadcrumbCount} Breadcrumb Recoveries
                  </button>
                ` : ''}
                ${hiatusCount > 0 ? `
                  <button class="btn-primary batch-hiatus-btn" style="background:#64748b;font-size:12px;padding:7px 14px;cursor:pointer;">
                    <i class="fa-solid fa-power-off"></i> Accept All ${hiatusCount} Hiatus Records
                  </button>
                ` : ''}
              </div>
            </div>
          ` : ''}

          <div id="fixes-cards-wrapper"></div>
        `;

        // Bind filter pill buttons
        list.querySelectorAll(".filter-pills .pill-btn").forEach(btn => {
          btn.addEventListener("click", () => {
            currentFixesFilter = btn.dataset.filter;
            loadFixProposals();
          });
        });

        // Bind Purge button
        list.querySelector("#btn-purge-fixes")?.addEventListener("click", async () => {
          if (confirm("Permanently clear all applied and rejected fix records from history? Pending proposals will remain untouched.")) {
            try {
              const pRes = await fetch("/api/fixes/purge", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ type: "RESOLVED" })
              });
              const pData = await pRes.json();
              if (pData.status === "SUCCESS") {
                loadFixProposals();
              }
            } catch (err) {
              alert("Error clearing history: " + err.message);
            }
          }
        });

        // Batch Action handler
        async function handleBatchAction(actionType, btnEl, originalHtml) {
          btnEl.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Applying batch...';
          btnEl.disabled = true;
          try {
            const bRes = await fetch("/api/fixes/batch-apply", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ action: actionType })
            });
            const bData = await bRes.json();
            if (bData.status === "SUCCESS") {
              alert(`Successfully applied ${bData.applied_count} fix proposals!`);
              loadFixProposals();
              loadOverview();
            } else {
              alert("Batch apply failed.");
              btnEl.innerHTML = originalHtml;
              btnEl.disabled = false;
            }
          } catch (e) {
            alert("Error in batch apply: " + e.message);
            btnEl.innerHTML = originalHtml;
            btnEl.disabled = false;
          }
        }

        const airportBtn = list.querySelector(".batch-airport-btn");
        if (airportBtn) airportBtn.addEventListener("click", () => handleBatchAction("INSERT_AIRPORT", airportBtn, airportBtn.innerHTML));
        const fitBtn = list.querySelector(".batch-fit-btn");
        if (fitBtn) fitBtn.addEventListener("click", () => handleBatchAction("SYNTHESIZE_FIT_ACTIVITY", fitBtn, fitBtn.innerHTML));
        const dwellBtn = list.querySelector(".batch-dwell-btn");
        if (dwellBtn) dwellBtn.addEventListener("click", () => handleBatchAction("EXTEND_STATIONARY_DWELL", dwellBtn, dwellBtn.innerHTML));
        const bcBtn = list.querySelector(".batch-bc-btn");
        if (bcBtn) bcBtn.addEventListener("click", () => handleBatchAction("RECONSTRUCT_FROM_BREADCRUMBS", bcBtn, bcBtn.innerHTML));
        const hiatusBtn = list.querySelector(".batch-hiatus-btn");
        if (hiatusBtn) hiatusBtn.addEventListener("click", () => handleBatchAction("DOCUMENTED_HIATUS", hiatusBtn, hiatusBtn.innerHTML));

        const cardsWrapper = list.querySelector("#fixes-cards-wrapper");
        if (fixes.length === 0) {
          cardsWrapper.innerHTML = `
            <div style="text-align:center;padding:40px;color:var(--text-muted);background:var(--bg-card);border:1px dashed var(--border-color);border-radius:12px;">
              <i class="fa-solid fa-circle-check" style="color:var(--accent-green);font-size:28px;margin-bottom:10px;display:block;"></i>
              <strong style="font-size:14px;color:var(--text-main);">No ${currentFixesFilter.toLowerCase()} proposals.</strong>
              <p style="font-size:12px;margin-top:4px;">Timeline is fully synchronized.</p>
            </div>
          `;
          return;
        }

        fixes.forEach(f => {
          const isAccepted = f.status === "ACCEPTED";
          const isRejected = f.status === "REJECTED";
          const card = document.createElement("div");
          card.id = `fix-card-${f.id}`;
          card.className = `item-card card ${isAccepted ? 'fix-accepted' : ''}`;
          card.style.display = "flex";
          card.style.justifyContent = "space-between";
          card.style.alignItems = "center";
          card.style.padding = "14px 18px";
          card.style.marginBottom = "10px";
          card.style.transition = "all 0.25s ease";

          let icon = "fa-wand-magic-sparkles";
          let iconBg = "#e8f0fe";
          let iconColor = "#1a73e8";
          let isDupe = f.proposed_action === "MERGE_DUPLICATE_PLACES";
          if (f.proposed_action === "INSERT_ORIGIN_AIRPORT") {
            icon = "fa-plane-departure"; iconBg = "#e8f0fe"; iconColor = "#1a73e8";
          } else if (f.proposed_action === "INSERT_DESTINATION_AIRPORT") {
            icon = "fa-plane-arrival"; iconBg = "#e6f4ea"; iconColor = "#1e8e3e";
          } else if (f.proposed_action === "SYNTHESIZE_FIT_ACTIVITY") {
            icon = "fa-person-running"; iconBg = "#fef7e0"; iconColor = "#f59e0b";
          } else if (f.proposed_action === "RECONSTRUCT_FROM_BREADCRUMBS") {
            icon = "fa-satellite-dish"; iconBg = "#f3e8ff"; iconColor = "#9334e6";
          } else if (f.proposed_action === "EXTEND_STATIONARY_DWELL") {
            icon = "fa-house-user"; iconBg = "#e6f4ea"; iconColor = "#1e8e3e";
          } else if (f.proposed_action === "SYNTHESIZE_TRANSIT_LEG") {
            icon = "fa-route"; iconBg = "#e0f7fa"; iconColor = "#12b5cb";
          } else if (f.proposed_action === "DOCUMENTED_HIATUS") {
            icon = "fa-power-off"; iconBg = "#f1f3f4"; iconColor = "#5f6368";
          } else if (f.proposed_action === "MERGE_DUPLICATE_PLACES") {
            icon = "fa-code-compare"; iconBg = "#ede9fe"; iconColor = "#7c3aed";
          } else if (f.proposed_action === "RESOLVE_AUTHENTIC_PLACE_ID") {
            icon = "fa-location-dot"; iconBg = "#fee2e2"; iconColor = "#ef4444";
          } else if (f.proposed_action === "GEOCODE_MISSING_COORDINATES") {
            icon = "fa-crosshairs"; iconBg = "#fef3c7"; iconColor = "#d97706";
          }

          let isPlaceFix = f.proposed_action === "RESOLVE_AUTHENTIC_PLACE_ID" || f.proposed_action === "GEOCODE_MISSING_COORDINATES";
          let isSavedPlace = f.date === "Saved Bookmark (No Visits)" || !f.date || f.date.includes("No visits");

          card.innerHTML = `
            <div style="display:flex;gap:14px;align-items:center;flex:1;">
              <div class="item-icon" style="background:${iconBg};color:${iconColor};width:40px;height:40px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:16px;">
                <i class="fa-solid ${icon}" style="color:${iconColor} !important;"></i>
              </div>
              <div class="item-body" style="flex:1;">
                <div class="item-title-row" style="display:flex;align-items:center;gap:8px;">
                  <span class="item-title" style="font-weight:700;font-size:14px;color:var(--text-main);">${f.proposed_action.replace(/_/g, ' ')}</span>
                  <span class="tag-badge ${isSavedPlace ? 'warning' : ''}" style="font-size:10px;font-family:var(--font-mono);">${isSavedPlace ? '<i class="fa-solid fa-bookmark"></i> Saved Bookmark' : f.date}</span>
                </div>
                <div class="item-address" style="margin:4px 0;font-size:12px;color:var(--text-muted);">${escapeHtml(f.reasoning)}</div>
                <div class="item-tags" style="display:flex;gap:6px;margin-top:4px;">
                  <span class="tag-badge ${isAccepted ? 'snapped' : (isRejected ? 'danger' : '')}" id="status-badge-${f.id}" style="font-size:10px;font-weight:700;">Status: ${f.status}</span>
                </div>
              </div>
            </div>
            <div class="card-actions" style="display:flex;gap:8px;margin-left:16px;">
              ${isDupe ? `
                <button class="btn-primary compare-dupe-btn" data-id="${f.id}" style="background:#7c3aed;padding:6px 12px;font-size:12px;cursor:pointer;" title="View duplicate places side-by-side with map">
                  <i class="fa-solid fa-code-compare"></i> Side-by-Side & Map
                </button>
              ` : (isPlaceFix && isSavedPlace) ? `
                <button class="btn-primary edit-place-fix-btn" data-id="${f.id}" style="background:#d97706;padding:6px 12px;font-size:12px;cursor:pointer;" title="Manually assign Place ID, Address, and Coordinates">
                  <i class="fa-solid fa-location-pen"></i> Assign Place ID & Coords
                </button>
              ` : `
                <button class="btn-secondary jump-date-btn" style="padding:6px 12px;font-size:12px;cursor:pointer;" title="View day in timeline">
                  <i class="fa-solid fa-eye"></i> View Day
                </button>
              `}
              ${!isAccepted && !isRejected ? `
                ${isPlaceFix ? `
                  <button class="btn-secondary edit-place-fix-btn" data-id="${f.id}" style="padding:6px 12px;font-size:12px;cursor:pointer;" title="Manually edit Place ID and coordinates">
                    <i class="fa-solid fa-pen-to-square"></i> Edit Place ID
                  </button>
                ` : `
                  <button class="btn-secondary edit-fix-btn" data-id="${f.id}" style="padding:6px 12px;font-size:12px;cursor:pointer;" title="Edit and customize proposal parameters">
                    <i class="fa-solid fa-pen-to-square"></i> Edit
                  </button>
                `}
                <button class="btn-primary apply-fix-btn" data-id="${f.id}" style="padding:6px 12px;font-size:12px;cursor:pointer;background:var(--accent-green);" title="Accept and apply proposal">
                  <i class="fa-solid fa-check"></i> Accept Fix
                </button>
                <button class="btn-secondary reject-fix-btn" data-id="${f.id}" style="padding:6px 10px;font-size:12px;cursor:pointer;color:var(--accent-red);" title="Dismiss proposal">
                  <i class="fa-solid fa-xmark"></i>
                </button>
              ` : ''}
            </div>
          `;

          // Event Listeners
          card.querySelector(".compare-dupe-btn")?.addEventListener("click", () => {
            openDuplicateCompareModal(f);
          });

          card.querySelectorAll(".edit-place-fix-btn")?.forEach(b => {
            b.addEventListener("click", () => {
              openEditPlaceModal(f);
            });
          });

          card.querySelector(".jump-date-btn")?.addEventListener("click", () => {
            if (!isSavedPlace) {
              jumpToTimelineDay(f.date, true);
            }
          });

          card.querySelector(".edit-fix-btn")?.addEventListener("click", () => {
            openEditProposalModal(null, f);
          });

          card.querySelector(".apply-fix-btn")?.addEventListener("click", async () => {
            const btn = card.querySelector(".apply-fix-btn");
            btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i>';
            btn.disabled = true;
            try {
              const applyRes = await fetch("/api/fixes/apply", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ proposal_id: f.id })
              });
              const applyData = await applyRes.json();
              if (applyData.status === "SUCCESS") {
                if (currentFixesFilter === "PENDING") {
                  card.style.opacity = "0";
                  card.style.transform = "translateX(20px)";
                  setTimeout(() => {
                    card.remove();
                    loadFixProposals();
                  }, 200);
                } else {
                  const badge = document.getElementById(`status-badge-${f.id}`);
                  if (badge) {
                    badge.textContent = "Status: ACCEPTED";
                    badge.className = "tag-badge snapped";
                  }
                  card.querySelector(".apply-fix-btn")?.remove();
                  card.querySelector(".reject-fix-btn")?.remove();
                }
              } else {
                alert("Failed to apply fix proposal.");
                btn.innerHTML = '<i class="fa-solid fa-check"></i> Accept Fix';
                btn.disabled = false;
              }
            } catch (e) {
              alert("Error applying fix: " + e.message);
              btn.innerHTML = '<i class="fa-solid fa-check"></i> Accept Fix';
              btn.disabled = false;
            }
          });

          card.querySelector(".reject-fix-btn")?.addEventListener("click", async () => {
            const rejectRes = await fetch("/api/fixes/reject", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ proposal_id: f.id })
            });
            const rejectData = await rejectRes.json();
            if (rejectData.status === "SUCCESS") {
              if (currentFixesFilter === "PENDING") {
                card.style.opacity = "0";
                card.style.transform = "translateX(-20px)";
                setTimeout(() => {
                  card.remove();
                  loadFixProposals();
                }, 200);
              } else {
                card.style.opacity = "0.5";
                const badge = document.getElementById(`status-badge-${f.id}`);
                if (badge) {
                  badge.textContent = "Status: REJECTED";
                  badge.className = "tag-badge danger";
                }
                card.querySelector(".apply-fix-btn")?.remove();
                card.querySelector(".reject-fix-btn")?.remove();
              }
            }
          });

          cardsWrapper.appendChild(card);
        });
      }
    } catch (e) {
      console.error("Error loading fixes:", e);
      list.innerHTML = `<div style="text-align:center;padding:40px;color:#ef4444;">Failed to load fix proposals: ${e.message}</div>`;
    }
  }

  // --- DUPLICATE PLACE COMPARISON MODAL & MAP ---
  let dupeCompareMap = null;

  async function openDuplicateCompareModal(f) {
    const modal = document.getElementById("duplicate-compare-modal");
    if (!modal) return;

    const pdata = typeof f.patch_data_json === "string" ? JSON.parse(f.patch_data_json) : (f.patch_data_json || {});
    const canId = pdata.canonical_place_id;
    const dupIds = pdata.duplicate_place_ids || [];
    const allIds = [canId, ...dupIds].filter(Boolean);

    document.getElementById("dupe-modal-title").textContent = `Duplicate Place Comparison: ${pdata.name || 'Place'}`;
    document.getElementById("dupe-modal-subtitle").textContent = `Review side-by-side attributes, map pins, and merge duplicate records into the primary place.`;

    const colsContainer = document.getElementById("dupe-compare-columns");
    colsContainer.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:20px;color:var(--text-muted);"><i class="fa-solid fa-circle-notch fa-spin"></i> Loading full comparison data...</div>';

    modal.style.display = "flex";
    modal.classList.remove("hidden");

    // Close button handler
    const closeModal = () => {
      modal.style.display = "none";
      modal.classList.add("hidden");
      if (dupeCompareMap) {
        dupeCompareMap.remove();
        dupeCompareMap = null;
      }
    };
    document.getElementById("btn-close-dupe-modal").onclick = closeModal;
    document.getElementById("btn-cancel-dupe-modal").onclick = closeModal;

    try {
      const res = await fetch(`/api/places/compare?ids=${encodeURIComponent(allIds.join(','))}`);
      const data = await res.json();
      const places = data.places || [];

      const canonicalPlace = places.find(p => p.place_id === canId) || places[0];
      const duplicatePlaces = places.filter(p => p.place_id !== canonicalPlace?.place_id);

      if (!canonicalPlace) {
        colsContainer.innerHTML = '<div style="color:var(--accent-red);padding:20px;">Could not load place details.</div>';
        return;
      }

      // Render Left (Canonical) and Right (Duplicates)
      const renderPlaceCard = (p, isPrimary) => `
        <div style="background:var(--bg-subtle);border:1px solid ${isPrimary ? 'var(--accent-green)' : 'var(--border-color)'};border-radius:12px;padding:16px;box-shadow:var(--shadow-sm);display:flex;flex-direction:column;gap:10px;">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <span class="tag-badge ${isPrimary ? 'snapped' : 'danger'}" style="font-weight:700;font-size:11px;">
              ${isPrimary ? '<i class="fa-solid fa-star"></i> PRIMARY / CANONICAL' : '<i class="fa-solid fa-clone"></i> DUPLICATE / ALIAS'}
            </span>
            <span style="font-size:11px;font-family:var(--font-mono);color:var(--text-muted);">ID: ${(p.place_id || 'NULL').slice(0, 16)}...</span>
          </div>
          <div>
            <h4 style="margin:0 0 4px 0;font-size:15px;font-weight:700;color:var(--text-main);">${escapeHtml(p.name)}</h4>
            <div style="font-size:12px;color:var(--text-muted);"><i class="fa-solid fa-location-dot" style="margin-right:4px;"></i>${escapeHtml(p.address || 'No full address recorded')}</div>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:12px;background:var(--bg-card);padding:10px;border-radius:8px;border:1px solid var(--border-color);">
            <div><span style="color:var(--text-dim);">Category:</span> <strong style="color:var(--text-main);">${escapeHtml(p.category || 'N/A')}</strong></div>
            <div><span style="color:var(--text-dim);">City:</span> <strong style="color:var(--text-main);">${escapeHtml(p.city || 'N/A')}</strong></div>
            <div><span style="color:var(--text-dim);">Visits:</span> <strong style="color:var(--accent-blue);">${p.visit_count || 0} visits</strong></div>
            <div><span style="color:var(--text-dim);">Coords:</span> <span style="font-family:var(--font-mono);font-size:11px;">${p.latitude?.toFixed(4) || 'N/A'}, ${p.longitude?.toFixed(4) || 'N/A'}</span></div>
          </div>
          ${(p.recent_segments && p.recent_segments.length > 0) ? `
            <div style="font-size:11px;">
              <span style="color:var(--text-dim);font-weight:600;">Timeline Visits Recorded (${p.recent_segments.length}):</span>
              <div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:4px;">
                ${p.recent_segments.slice(0, 6).map(s => `<span class="tag-badge" style="cursor:pointer;" onclick="window.jumpToTimelineDay('${s.date}', true, 'fixes')"><i class="fa-solid fa-calendar-day"></i> ${s.date}</span>`).join('')}
              </div>
            </div>
          ` : '<div style="font-size:11px;color:var(--text-dim);">No associated timeline segments.</div>'}
        </div>
      `;

      colsContainer.innerHTML = `
        ${renderPlaceCard(canonicalPlace, true)}
        <div style="display:flex;flex-direction:column;gap:12px;">
          ${duplicatePlaces.map(dp => renderPlaceCard(dp, false)).join('')}
        </div>
      `;

      // Render Leaflet Map
      if (dupeCompareMap) {
        dupeCompareMap.remove();
        dupeCompareMap = null;
      }

      const mapDiv = document.getElementById("dupe-compare-map");
      const cLat = canonicalPlace.latitude || 40.73;
      const cLng = canonicalPlace.longitude || -73.99;

      dupeCompareMap = L.map(mapDiv).setView([cLat, cLng], 16);
      createBaseTileLayer().addTo(dupeCompareMap);

      const latlngs = [];

      // Primary Marker (Blue)
      const primaryIcon = L.divIcon({
        className: 'custom-div-icon',
        html: `<div style="background:#1a73e8;color:#fff;width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,0.3);font-size:14px;"><i class="fa-solid fa-star"></i></div>`,
        iconSize: [30, 30],
        iconAnchor: [15, 15]
      });
      const pMarker = L.marker([cLat, cLng], { icon: primaryIcon }).addTo(dupeCompareMap);
      pMarker.bindPopup(`<b>${escapeHtml(canonicalPlace.name)} (Primary)</b><br>${escapeHtml(canonicalPlace.address || '')}`);
      latlngs.push([cLat, cLng]);

      let maxDistMeters = 0;

      duplicatePlaces.forEach((dp) => {
        const dLat = dp.latitude || cLat;
        const dLng = dp.longitude || cLng;
        const dupeIcon = L.divIcon({
          className: 'custom-div-icon',
          html: `<div style="background:#8b5cf6;color:#fff;width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,0.3);font-size:13px;"><i class="fa-solid fa-clone"></i></div>`,
          iconSize: [28, 28],
          iconAnchor: [14, 14]
        });
        const dMarker = L.marker([dLat, dLng], { icon: dupeIcon }).addTo(dupeCompareMap);
        dMarker.bindPopup(`<b>${escapeHtml(dp.name)} (Duplicate)</b><br>${escapeHtml(dp.address || '')}`);
        latlngs.push([dLat, dLng]);

        // Draw line between primary and duplicate
        L.polyline([[cLat, cLng], [dLat, dLng]], {
          color: '#8b5cf6',
          weight: 2,
          dashArray: '4, 6',
          opacity: 0.8
        }).addTo(dupeCompareMap);

        // Compute distance
        const dMeters = pMarker.getLatLng().distanceTo(dMarker.getLatLng());
        if (dMeters > maxDistMeters) maxDistMeters = dMeters;
      });

      const distBadge = document.getElementById("dupe-map-distance-badge");
      if (distBadge) {
        distBadge.textContent = maxDistMeters < 1 ? "0m (Exact Spatial Match)" : `${maxDistMeters.toFixed(1)}m separation`;
      }

      if (latlngs.length > 1) {
        dupeCompareMap.fitBounds(L.latLngBounds(latlngs), { padding: [40, 40], maxZoom: 18 });
      }

      setTimeout(() => {
        if (dupeCompareMap) dupeCompareMap.invalidateSize();
      }, 200);

      // Merge Button Handler
      const mergeBtn = document.getElementById("btn-merge-dupe-action");
      mergeBtn.onclick = async () => {
        mergeBtn.disabled = true;
        mergeBtn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Merging duplicate places...';
        try {
          const mRes = await fetch("/api/places/merge", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              canonical_place_id: canonicalPlace.place_id,
              duplicate_place_ids: duplicatePlaces.map(p => p.place_id),
              proposal_id: f.id
            })
          });
          const mData = await mRes.json();
          if (mData.status === "SUCCESS") {
            closeModal();
            loadFixProposals();
            loadOverview();
            alert(`Successfully merged ${duplicatePlaces.length} duplicate record(s) into '${canonicalPlace.name}'!`);
          } else {
            alert("Failed to merge places: " + (mData.error || "Unknown error"));
          }
        } catch (err) {
          alert("Error merging places: " + err.message);
        } finally {
          mergeBtn.disabled = false;
          mergeBtn.innerHTML = '<i class="fa-solid fa-code-merge"></i> Merge Duplicates into Canonical Place';
        }
      };

    } catch (err) {
      console.error("Error loading dupe comparison:", err);
      colsContainer.innerHTML = `<div style="color:var(--accent-red);padding:20px;">Failed to load comparison: ${err.message}</div>`;
    }
  }

  // --- MANUAL EDIT PLACE & ASSIGN PLACE ID MODAL ---
  function openEditPlaceModal(fOrPlace) {
    const modal = document.getElementById("edit-place-modal");
    if (!modal) return;

    let pdata = {};
    let proposalId = null;

    if (fOrPlace && fOrPlace.patch_data_json) {
      proposalId = fOrPlace.id;
      pdata = typeof fOrPlace.patch_data_json === "string" ? JSON.parse(fOrPlace.patch_data_json) : (fOrPlace.patch_data_json || {});
    } else if (fOrPlace) {
      pdata = fOrPlace;
    }

    const origId = pdata.place_id || pdata.canonical_place_id || "";
    document.getElementById("edit-place-original-id").value = origId;
    document.getElementById("edit-place-proposal-id").value = proposalId || "";
    document.getElementById("edit-place-new-id").value = origId.startsWith("ChIJ") && !origId.includes("AAAA") ? origId : (pdata.place_id || "");
    document.getElementById("edit-place-name").value = pdata.name || "";
    document.getElementById("edit-place-address").value = pdata.address || "";
    document.getElementById("edit-place-lat").value = pdata.latitude || "";
    document.getElementById("edit-place-lng").value = pdata.longitude || "";
    document.getElementById("edit-place-city").value = pdata.city || "New York";

    if (pdata.category) {
      const catSelect = document.getElementById("edit-place-category");
      for (let opt of catSelect.options) {
        if (opt.value.toLowerCase() === pdata.category.toLowerCase()) {
          catSelect.value = opt.value;
          break;
        }
      }
    }

    // --- GOOGLE MAPS DEEP LINK AUTO-RESOLVER ---
    const deepLinkInput = document.getElementById("edit-place-deeplink");
    const resolveBtn = document.getElementById("btn-resolve-deeplink");
    const statusSpan = document.getElementById("deep-link-status");

    if (deepLinkInput) deepLinkInput.value = "";
    if (statusSpan) {
      statusSpan.style.display = "none";
      statusSpan.textContent = "";
    }

    const doResolveDeepLink = async () => {
      const linkVal = deepLinkInput ? deepLinkInput.value.trim() : "";
      if (!linkVal) return;

      if (resolveBtn) {
        resolveBtn.disabled = true;
        resolveBtn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Resolving...';
      }
      if (statusSpan) {
        statusSpan.style.display = "inline-block";
        statusSpan.style.color = "var(--accent-blue)";
        statusSpan.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Resolving Google Maps Link...';
      }

      try {
        const res = await fetch("/api/places/resolve-link", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            url: linkVal,
            place_id: origId,
            proposal_id: proposalId,
            apply_directly: false
          })
        });
        const data = await res.json();
        if (data.status === "SUCCESS" && data.place) {
          const pl = data.place;
          if (pl.place_id) document.getElementById("edit-place-new-id").value = pl.place_id;
          if (pl.name) document.getElementById("edit-place-name").value = pl.name;
          if (pl.address) document.getElementById("edit-place-address").value = pl.address;
          if (pl.latitude) document.getElementById("edit-place-lat").value = pl.latitude;
          if (pl.longitude) document.getElementById("edit-place-lng").value = pl.longitude;
          if (pl.city) document.getElementById("edit-place-city").value = pl.city;
          if (pl.category) {
            const catSelect = document.getElementById("edit-place-category");
            for (let opt of catSelect.options) {
              if (opt.value.toLowerCase() === pl.category.toLowerCase()) {
                catSelect.value = opt.value;
                break;
              }
            }
          }

          if (statusSpan) {
            statusSpan.style.display = "inline-block";
            statusSpan.style.color = "var(--accent-green)";
            statusSpan.innerHTML = `<i class="fa-solid fa-check-circle"></i> Resolved: <strong>${escapeHtml(pl.name || 'Place')}</strong> (${pl.place_id ? pl.place_id.slice(0, 14) + '...' : 'Coords extracted'})`;
          }
        } else {
          if (statusSpan) {
            statusSpan.style.display = "inline-block";
            statusSpan.style.color = "var(--accent-red)";
            statusSpan.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i> ${data.error || 'Could not resolve link'}`;
          }
        }
      } catch (err) {
        if (statusSpan) {
          statusSpan.style.display = "inline-block";
          statusSpan.style.color = "var(--accent-red)";
          statusSpan.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i> Error: ${err.message}`;
        }
      } finally {
        if (resolveBtn) {
          resolveBtn.disabled = false;
          resolveBtn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Auto-Fill';
        }
      }
    };

    if (resolveBtn) resolveBtn.onclick = doResolveDeepLink;
    if (deepLinkInput) {
      deepLinkInput.onpaste = () => {
        setTimeout(doResolveDeepLink, 100);
      };
      deepLinkInput.onkeydown = (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          doResolveDeepLink();
        }
      };
    }

    modal.style.display = "flex";
    modal.classList.remove("hidden");

    const closeModal = () => {
      modal.style.display = "none";
      modal.classList.add("hidden");
    };
    document.getElementById("btn-close-edit-place-modal").onclick = closeModal;
    document.getElementById("btn-cancel-edit-place-modal").onclick = closeModal;

    const saveBtn = document.getElementById("btn-save-edit-place");
    saveBtn.onclick = async (e) => {
      e.preventDefault();
      const newPid = document.getElementById("edit-place-new-id").value.trim();
      const name = document.getElementById("edit-place-name").value.trim();
      const addr = document.getElementById("edit-place-address").value.trim();
      const lat = document.getElementById("edit-place-lat").value.trim();
      const lng = document.getElementById("edit-place-lng").value.trim();
      const cat = document.getElementById("edit-place-category").value;
      const city = document.getElementById("edit-place-city").value.trim();
      const relink = document.getElementById("edit-place-relink").checked;

      if (!name) {
        alert("Please enter a place name.");
        return;
      }

      saveBtn.disabled = true;
      saveBtn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Saving...';

      try {
        const res = await fetch("/api/places/edit-place", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            place_id: origId || newPid,
            new_place_id: newPid,
            name: name,
            address: addr,
            latitude: lat ? parseFloat(lat) : null,
            longitude: lng ? parseFloat(lng) : null,
            category: cat,
            city: city,
            relink_segments: relink,
            proposal_id: proposalId
          })
        });
        const resData = await res.json();
        if (resData.status === "SUCCESS") {
          closeModal();
          loadFixProposals();
          loadOverview();
          alert(`Successfully saved '${name}' (Place ID: ${newPid || 'Saved'})!`);
        } else {
          alert("Failed to save place: " + (resData.error || "Unknown error"));
        }
      } catch (err) {
        alert("Error saving place: " + err.message);
      } finally {
        saveBtn.disabled = false;
        saveBtn.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> Save & Resolve Proposal';
      }
    };
  }

  // Edit Place Modal
  // Helpers for datetime-local minute-precision editing with local timezone awareness
  function toDateTimeLocalValue(isoStr, dateFallback, localTimeFallback) {
    if (dateFallback && localTimeFallback && localTimeFallback.includes(":") && localTimeFallback !== "--:--") {
      const hhmm = localTimeFallback.slice(0, 5);
      return `${dateFallback}T${hhmm}`;
    }
    if (!isoStr) return dateFallback ? `${dateFallback}T12:00` : "";
    
    // If isoStr is already in YYYY-MM-DDTHH:MM offset format
    const m = String(isoStr).match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::\d{2})?([+-]\d{2}:\d{2}|Z)?/);
    if (m) {
      const dPart = m[1];
      const tPart = m[2];
      const offset = m[3];
      if (!offset || offset !== "Z") {
        return `${dPart}T${tPart}`;
      }
    }
    
    try {
      const d = new Date(isoStr);
      if (!isNaN(d.getTime())) {
        const y = d.getFullYear();
        const mo = String(d.getMonth() + 1).padStart(2, "0");
        const da = String(d.getDate()).padStart(2, "0");
        const ho = String(d.getHours()).padStart(2, "0");
        const mi = String(d.getMinutes()).padStart(2, "0");
        return `${y}-${mo}-${da}T${ho}:${mi}`;
      }
    } catch (e) {}
    
    const clean = String(isoStr).slice(0, 16);
    if (clean.length === 16 && clean.includes("T")) return clean;
    return dateFallback ? `${dateFallback}T12:00` : "";
  }

  function fromDateTimeLocalValue(localVal, origIso) {
    if (!localVal) return origIso || "";
    let offset = "";
    if (origIso) {
      const match = origIso.match(/([+-]\d{2}:\d{2})$/);
      if (match) offset = match[1];
    }
    if (!offset) {
      const d = new Date(localVal);
      const offsetMin = -d.getTimezoneOffset();
      const sign = offsetMin >= 0 ? "+" : "-";
      const absMin = Math.abs(offsetMin);
      const hrs = String(Math.floor(absMin / 60)).padStart(2, "0");
      const mins = String(absMin % 60).padStart(2, "0");
      offset = `${sign}${hrs}:${mins}`;
    }
    return `${localVal}:00${offset}`;
  }

  const ALL_CATEGORIES = [
    "Home & Residence", "Food & Drink", "Travel & Transit", "Parks & Outdoors",
    "Shopping", "Culture & Arts", "Work & Office", "Hotels & Lodging", "Other / POI"
  ];

  const ALL_ACTIVITIES = [
    "WALKING", "CYCLING", "IN_SUBWAY", "IN_TRAIN", "IN_BUS", "IN_TRAM",
    "IN_PASSENGER_VEHICLE", "IN_TAXI", "FLYING", "IN_FERRY", "IN_FUNICULAR",
    "IN_GONDOLA_LIFT", "HIKING", "RUNNING", "BOATING", "SAILING", "KAYAKING",
    "SWIMMING", "SKIING", "SNOWSHOEING", "SLEDDING", "KITESURFING", "PARAGLIDING",
    "TRAVEL"
  ];

  function openEditSegmentModal(segment) {
    const modal = document.getElementById("modal-container");
    const content = document.getElementById("modal-content");
    const title = document.getElementById("modal-title");
    const isVisit = segment.segment_type === "visit";

    title.innerHTML = isVisit 
      ? `<i class="fa-solid fa-location-dot" style="color:var(--accent-blue);"></i> Edit Place Visit: ${escapeHtml(segment.place_name || 'Place')}`
      : `<i class="fa-solid fa-route" style="color:var(--accent-blue);"></i> Edit Movement Leg: ${escapeHtml((segment.activity_type || 'Activity').replace(/_/g, ' '))}`;

    let formHtml = "";
    if (isVisit) {
      const catOptions = ALL_CATEGORIES.map(c => `<option value="${c}" ${c === segment.category ? 'selected' : ''}>${c}</option>`).join("");
      formHtml = `
        <div class="form-group">
          <label>Place / Venue Name</label>
          <input type="text" id="edit-place-name" value="${escapeHtml(segment.place_name || segment.catalog_place_name || '')}" placeholder="e.g. Home (189 Ave C), Google NYC...">
        </div>
        <div class="form-group">
          <label>Category</label>
          <select id="edit-place-category">${catOptions}</select>
        </div>
        <div class="form-group">
          <label>Address</label>
          <input type="text" id="edit-place-addr" value="${escapeHtml(segment.place_address || segment.catalog_place_address || '')}" placeholder="e.g. 189 Avenue C, New York, NY">
        </div>
        <div class="form-row">
          <div class="form-group">
            <label>Start Time</label>
            <input type="datetime-local" step="60" id="edit-start-time" value="${toDateTimeLocalValue(segment.start_time, segment.date, segment.start_time_local)}">
          </div>
          <div class="form-group">
            <label>End Time</label>
            <input type="datetime-local" step="60" id="edit-end-time" value="${toDateTimeLocalValue(segment.end_time, segment.date, segment.end_time_local)}">
          </div>
        </div>
      `;
    } else {
      const actOptions = ALL_ACTIVITIES.map(a => `<option value="${a}" ${a === (segment.activity_type || 'WALKING').toUpperCase() ? 'selected' : ''}>${a.replace(/_/g, ' ')}</option>`).join("");
      const distKm = ((segment.distance_meters || 0) / 1000.0).toFixed(2);
      formHtml = `
        <div class="form-group">
          <label>Travel Mode</label>
          <select id="edit-activity-type">${actOptions}</select>
        </div>
        <div class="form-group">
          <label>Calculated Trajectory Distance</label>
          <div style="padding:10px 14px;background:#f1f5f9;border:1px solid #cbd5e1;border-radius:8px;font-family:var(--font-mono);font-size:13px;color:var(--text-main);display:flex;align-items:center;gap:8px;">
            <i class="fa-solid fa-route" style="color:var(--accent-blue);"></i> <strong>${distKm} km</strong>
          </div>
        </div>
        <div class="form-row">
          <div class="form-group">
            <label>Start Time</label>
            <input type="datetime-local" step="60" id="edit-start-time" value="${toDateTimeLocalValue(segment.start_time, segment.date)}">
          </div>
          <div class="form-group">
            <label>End Time</label>
            <input type="datetime-local" step="60" id="edit-end-time" value="${toDateTimeLocalValue(segment.end_time, segment.date)}">
          </div>
        </div>
      `;
    }

    content.innerHTML = `
      ${formHtml}
      <div class="form-actions">
        <button id="modal-delete-btn" class="btn-danger"><i class="fa-solid fa-trash"></i> Delete Segment</button>
        <button id="modal-cancel-btn" class="btn-secondary">Cancel</button>
        <button id="modal-save-btn" class="btn-primary"><i class="fa-solid fa-check"></i> Save Changes</button>
      </div>
    `;

    modal.classList.remove("hidden");

    document.getElementById("modal-cancel-btn").onclick = () => modal.classList.add("hidden");

    document.getElementById("modal-delete-btn").onclick = async () => {
      if (!confirm("Are you sure you want to delete this segment from the timeline?")) return;
      try {
        await fetch("/api/segments/delete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: segment.id })
        });
        modal.classList.add("hidden");
        loadDay(currentDate);
        loadOverview();
      } catch (err) {
        alert("Failed to delete segment: " + err.message);
      }
    };

    document.getElementById("modal-save-btn").onclick = async () => {
      const payload = { id: segment.id };
      if (isVisit) {
        payload.place_name = document.getElementById("edit-place-name").value.trim();
        payload.category = document.getElementById("edit-place-category").value;
        payload.place_address = document.getElementById("edit-place-addr").value.trim();
      } else {
        payload.activity_type = document.getElementById("edit-activity-type").value;
      }
      const stVal = document.getElementById("edit-start-time").value;
      const etVal = document.getElementById("edit-end-time").value;
      payload.start_time = fromDateTimeLocalValue(stVal, segment.start_time);
      payload.end_time = fromDateTimeLocalValue(etVal, segment.end_time);

      try {
        await fetch("/api/segments/update", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        modal.classList.add("hidden");
        loadDay(currentDate);
        loadOverview();
      } catch (err) {
        alert("Failed to update segment: " + err.message);
      }
    };
  }

  function openEditProposalModal(target, proposal) {
    const modal = document.getElementById("modal-container");
    const content = document.getElementById("modal-content");
    const title = document.getElementById("modal-title");

    title.innerHTML = `<i class="fa-solid fa-pen-to-square" style="color:var(--accent-blue);"></i> Customize Fix Proposal (#${proposal.id})`;

    const patchData = proposal.patch_data_json ? JSON.parse(proposal.patch_data_json) : {};
    const isAirport = proposal.proposed_action === "INSERT_ORIGIN_AIRPORT" || proposal.proposed_action === "INSERT_DESTINATION_AIRPORT" || proposal.target_type === "flight";

    let defaultPlace = 'Recovered Place';
    if (isAirport) {
      defaultPlace = patchData.airport_name ? (patchData.airport_iata ? `${patchData.airport_name} (${patchData.airport_iata})` : patchData.airport_name) : 'Airport';
    } else {
      defaultPlace = patchData.target_place || patchData.resolved_poi_name || patchData.resolved_name || (target && target.prev_name) || (target && target.place_name) || 'Recovered Place';
    }

    const defaultMode = patchData.activity_type || patchData.mode || 'WALKING';
    const defaultCat = patchData.category || (isAirport ? 'Travel & Transit' : 'Other / POI');
    const defaultAction = proposal.proposed_action || (isAirport ? 'INSERT_ORIGIN_AIRPORT' : 'RECONSTRUCT_FROM_BREADCRUMBS');

    const pDate = proposal.date || (target && target.date) || currentDate;
    const rawSt = patchData.start_time || (target && target.start_time) || `${pDate}T09:00:00Z`;
    const rawEt = patchData.end_time || (target && target.end_time) || `${pDate}T10:00:00Z`;

    const actOptions = [
      { val: "INSERT_ORIGIN_AIRPORT", label: "Insert Departure Origin Airport" },
      { val: "INSERT_DESTINATION_AIRPORT", label: "Insert Arrival Destination Airport" },
      { val: "SYNTHESIZE_FIT_ACTIVITY", label: "Synthesize Google Fit Workout" },
      { val: "EXTEND_STATIONARY_DWELL", label: "Extend Stationary Dwell" },
      { val: "RECONSTRUCT_FROM_BREADCRUMBS", label: "Recover Venue from GPS Breadcrumbs" },
      { val: "SYNTHESIZE_TRANSIT_LEG", label: "Synthesize Transit / Travel Movement" },
      { val: "DOCUMENTED_HIATUS", label: "Document Untracked Hiatus" }
    ].map(o => `<option value="${o.val}" ${o.val === defaultAction ? 'selected' : ''}>${o.label}</option>`).join("");

    const catOptions = ALL_CATEGORIES.map(c => `<option value="${c}" ${c === defaultCat ? 'selected' : ''}>${c}</option>`).join("");
    const modeOptions = ALL_ACTIVITIES.map(a => `<option value="${a}" ${a === defaultMode ? 'selected' : ''}>${a.replace(/_/g, ' ')}</option>`).join("");

    content.innerHTML = `
      <div class="form-group">
        <label>Fix Strategy</label>
        <select id="edit-prop-action">${actOptions}</select>
      </div>
      <div class="form-group" id="group-prop-place">
        <label id="label-prop-place">${isAirport ? 'Airport Name & Terminal' : 'Target Place / Venue Name'}</label>
        <input type="text" id="edit-prop-place" value="${escapeHtml(defaultPlace)}" placeholder="Enter name...">
      </div>
      <div class="form-group" id="group-prop-cat">
        <label>Category</label>
        <select id="edit-prop-cat">${catOptions}</select>
      </div>
      <div class="form-group" id="group-prop-mode" style="display:none;">
        <label>Travel Mode</label>
        <select id="edit-prop-mode">${modeOptions}</select>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Start Time</label>
          <input type="datetime-local" step="60" id="edit-prop-start" value="${toDateTimeLocalValue(rawSt, pDate)}">
        </div>
        <div class="form-group">
          <label>End Time</label>
          <input type="datetime-local" step="60" id="edit-prop-end" value="${toDateTimeLocalValue(rawEt, pDate)}">
        </div>
      </div>
      <div class="form-actions">
        <button id="modal-reject-btn" class="btn-danger"><i class="fa-solid fa-xmark"></i> Dismiss Proposal</button>
        <button id="modal-cancel-btn" class="btn-secondary">Cancel</button>
        <button id="modal-apply-btn" class="btn-primary"><i class="fa-solid fa-check"></i> Apply Fix</button>
      </div>
    `;

    const actionSelect = document.getElementById("edit-prop-action");
    const modeGroup = document.getElementById("group-prop-mode");
    const placeGroup = document.getElementById("group-prop-place");
    const placeLabel = document.getElementById("label-prop-place");
    const catGroup = document.getElementById("group-prop-cat");

    function updateActionFields() {
      const act = actionSelect.value;
      if (act === "SYNTHESIZE_TRANSIT_LEG" || act === "SYNTHESIZE_FIT_ACTIVITY") {
        modeGroup.style.display = "flex";
        placeGroup.style.display = "none";
        catGroup.style.display = "none";
      } else if (act.includes("AIRPORT")) {
        modeGroup.style.display = "none";
        placeGroup.style.display = "flex";
        placeLabel.textContent = "Airport Name & Terminal";
        catGroup.style.display = "flex";
        document.getElementById("edit-prop-cat").value = "Travel & Transit";
      } else {
        modeGroup.style.display = "none";
        placeGroup.style.display = "flex";
        placeLabel.textContent = "Target Place / Venue Name";
        catGroup.style.display = "flex";
      }
    }
    actionSelect.onchange = updateActionFields;
    updateActionFields();

    modal.classList.remove("hidden");

    document.getElementById("modal-cancel-btn").onclick = () => modal.classList.add("hidden");

    document.getElementById("modal-reject-btn").onclick = async () => {
      try {
        await fetch("/api/fixes/reject", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ proposal_id: proposal.id })
        });
        modal.classList.add("hidden");
        loadDay(currentDate);
        loadFixProposals();
        loadOverview();
      } catch (err) {
        alert("Failed to dismiss proposal: " + err.message);
      }
    };

    document.getElementById("modal-apply-btn").onclick = async () => {
      const stVal = document.getElementById("edit-prop-start").value;
      const etVal = document.getElementById("edit-prop-end").value;

      const payload = {
        proposal_id: proposal.id,
        gap_id: (target && target.jump_distance_km !== undefined) ? target.id : (proposal.target_type === 'gap' ? proposal.target_id : null),
        action: actionSelect.value,
        place_name: document.getElementById("edit-prop-place").value.trim(),
        category: document.getElementById("edit-prop-cat").value,
        mode: document.getElementById("edit-prop-mode").value,
        start_time: fromDateTimeLocalValue(stVal, rawSt),
        end_time: fromDateTimeLocalValue(etVal, rawEt)
      };

      try {
        const res = await fetch("/api/fixes/edit-and-apply", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        const resData = await res.json();
        if (resData.status === "SUCCESS") {
          modal.classList.add("hidden");
          loadDay(currentDate);
          loadFixProposals();
          loadOverview();
        } else {
          alert("Failed to apply fix: " + (resData.error || "Unknown error"));
        }
      } catch (err) {
        alert("Failed to apply customized fix: " + err.message);
      }
    };
  }

  function openAddSegmentModal(gap) {
    const modal = document.getElementById("modal-container");
    const content = document.getElementById("modal-content");
    const title = document.getElementById("modal-title");

    title.innerHTML = `<i class="fa-solid fa-plus-circle" style="color:var(--accent-blue);"></i> Insert Timeline Segment (${gap.date})`;

    const catOptions = ALL_CATEGORIES.map(c => `<option value="${c}">${c}</option>`).join("");
    const actOptions = ALL_ACTIVITIES.map(a => `<option value="${a}">${a.replace(/_/g, ' ')}</option>`).join("");

    content.innerHTML = `
      <div class="form-group">
        <label>Segment Type</label>
        <select id="new-seg-type">
          <option value="visit" selected>Place / Venue Visit</option>
          <option value="activity">Movement / Travel Activity</option>
        </select>
      </div>
      <div class="form-group" id="new-group-place">
        <label>Place Name</label>
        <input type="text" id="new-place-name" placeholder="e.g. Home, Hotel, Restaurant, Office...">
      </div>
      <div class="form-group" id="new-group-cat">
        <label>Category</label>
        <select id="new-place-cat">${catOptions}</select>
      </div>
      <div class="form-group" id="new-group-mode" style="display:none;">
        <label>Travel Mode</label>
        <select id="new-act-mode">${actOptions}</select>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Start Time</label>
          <input type="datetime-local" step="60" id="new-seg-start" value="${toDateTimeLocalValue(gap.start_time, gap.date, gap.local_start_time)}">
        </div>
        <div class="form-group">
          <label>End Time</label>
          <input type="datetime-local" step="60" id="new-seg-end" value="${toDateTimeLocalValue(gap.end_time, gap.date, gap.local_end_time)}">
        </div>
      </div>
      <div class="form-actions">
        <button id="modal-cancel-btn" class="btn-secondary">Cancel</button>
        <button id="modal-add-btn" class="btn-primary"><i class="fa-solid fa-plus"></i> Insert Segment</button>
      </div>
    `;

    const typeSelect = document.getElementById("new-seg-type");
    const placeGroup = document.getElementById("new-group-place");
    const catGroup = document.getElementById("new-group-cat");
    const modeGroup = document.getElementById("new-group-mode");

    typeSelect.onchange = () => {
      if (typeSelect.value === "activity") {
        modeGroup.style.display = "flex";
        placeGroup.style.display = "none";
        catGroup.style.display = "none";
      } else {
        modeGroup.style.display = "none";
        placeGroup.style.display = "flex";
        catGroup.style.display = "flex";
      }
    };

    modal.classList.remove("hidden");
    document.getElementById("modal-cancel-btn").onclick = () => modal.classList.add("hidden");

    document.getElementById("modal-add-btn").onclick = async () => {
      const stVal = document.getElementById("new-seg-start").value;
      const etVal = document.getElementById("new-seg-end").value;

      const payload = {
        gap_id: gap.id,
        date: gap.date,
        segment_type: typeSelect.value,
        start_time: fromDateTimeLocalValue(stVal, gap.start_time),
        end_time: fromDateTimeLocalValue(etVal, gap.end_time),
        latitude: gap.prev_lat || gap.next_lat,
        longitude: gap.prev_lng || gap.next_lng,
        end_lat: gap.next_lat,
        end_lng: gap.next_lng
      };
      if (typeSelect.value === "visit") {
        payload.place_name = document.getElementById("new-place-name").value.trim() || "Manual Visit";
        payload.category = document.getElementById("new-place-cat").value;
      } else {
        payload.activity_type = document.getElementById("new-act-mode").value;
      }

      try {
        await fetch("/api/segments/create", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        modal.classList.add("hidden");
        loadDay(currentDate);
        loadOverview();
      } catch (err) {
        alert("Failed to create segment: " + err.message);
      }
    };
  }

  // ==========================================================================
  // LIVE ANDROID GMM SIDE-BY-SIDE COMPARATOR & EMULATOR EMBED
  // ==========================================================================
  let gmmStreamTimer = null;
  let gmmPanelOpen = false;

  async function openGMMComparator(dateToOpen) {
    const targetDate = dateToOpen || currentDate;
    const panel = document.getElementById("gmm-side-panel");
    const layout = document.querySelector(".timeline-layout");
    if (!panel) return;

    panel.style.display = "flex";
    layout?.classList.add("gmm-open");
    gmmPanelOpen = true;
    const dateBadge = document.getElementById("gmm-active-date");
    if (dateBadge) dateBadge.textContent = targetDate;

    // 1. Refresh live screen image
    refreshGMMScreen();

    // 2. Intent device to target date
    syncGMMDate(targetDate);

    // 3. Load side-by-side comparison
    loadGMMComparison(targetDate);

    // 4. Start auto stream if enabled
    startGMMStream();
  }

  function closeGMMComparator() {
    const panel = document.getElementById("gmm-side-panel");
    const layout = document.querySelector(".timeline-layout");
    if (panel) panel.style.display = "none";
    layout?.classList.remove("gmm-open");
    gmmPanelOpen = false;
    stopGMMStream();
  }

  async function refreshGMMScreen() {
    const img = document.getElementById("gmm-screen-img");
    const spinner = document.getElementById("gmm-screen-spinner");
    if (!img) return;
    if (spinner) spinner.style.display = "block";

    const timestamp = Date.now();
    const newImg = new Image();
    newImg.onload = () => {
      img.src = newImg.src;
      if (spinner) spinner.style.display = "none";
    };
    newImg.onerror = () => {
      if (spinner) spinner.style.display = "none";
    };
    newImg.src = `/api/device/screen?t=${timestamp}`;
  }

  function startGMMStream() {
    stopGMMStream();
    const autoCheck = document.getElementById("gmm-auto-refresh");
    if (autoCheck && autoCheck.checked) {
      gmmStreamTimer = setInterval(() => {
        if (gmmPanelOpen) refreshGMMScreen();
      }, 2500);
    }
  }

  function stopGMMStream() {
    if (gmmStreamTimer) {
      clearInterval(gmmStreamTimer);
      gmmStreamTimer = null;
    }
  }

  async function syncGMMDate(dateStr) {
    try {
      const btn = document.getElementById("btn-gmm-sync-day");
      if (btn) btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Intenting...';
      const res = await fetch("/api/device/intent-day", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date: dateStr })
      });
      const data = await res.json();
      if (btn) btn.innerHTML = '<i class="fa-solid fa-bolt"></i> Intent Date';
      setTimeout(refreshGMMScreen, 1000);
    } catch (e) {
      console.error("Error intenting date:", e);
    }
  }

  async function sendGMMTouch(action, x, y, x2 = null, y2 = null) {
    try {
      await fetch("/api/device/touch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, x, y, x2, y2 })
      });
      setTimeout(refreshGMMScreen, 400);
    } catch (e) {
      console.error("Touch error:", e);
    }
  }

  async function loadGMMComparison(dateStr) {
    const listEl = document.getElementById("gmm-comparison-list");
    const badge = document.getElementById("gmm-discrepancy-badge");
    if (!listEl) return;
    listEl.innerHTML = '<div class="loading-spinner"><i class="fa-solid fa-circle-notch fa-spin"></i> Loading comparison...</div>';

    try {
      const res = await fetch(`/api/device/compare-day?date=${dateStr}`);
      const data = await res.json();

      if (badge) {
        badge.textContent = `${data.discrepancy_count || 0} Issues`;
        badge.className = (data.discrepancy_count > 0) ? "pill-badge red" : "pill-badge green";
      }

      if (!data.comparisons || data.comparisons.length === 0) {
        listEl.innerHTML = '<div style="color:#94a3b8;font-size:12px;text-align:center;padding:16px;">No recorded segments for this date on either Studio or Device.</div>';
        return;
      }

      let html = "";
      data.comparisons.forEach((comp, idx) => {
        const isDiff = comp.status !== "MATCH";
        const statusClass = isDiff ? "diff" : "match";
        const statusBadgeClass = isDiff ? "red" : "green";

        const s = comp.studio;
        const g = comp.gms;

        const sLabel = s ? (s.place_name || s.activity_type || s.segment_type) : "<i>(Missing in Studio)</i>";
        const sSub = s ? `${s.duration_minutes} min ${s.distance_meters ? `· ${(s.distance_meters/1000).toFixed(2)} km` : ''}` : "";

        const gLabel = g ? (g.segment_type === "visit" ? `Visit (fp: ${g.fprint ? g.fprint.toString().slice(0,8) : '?'})` : `Activity (${g.start_time}-${g.end_time})`) : "<i>(Missing in GMM)</i>";
        const gSub = g ? `${g.duration_minutes} min` : "";

        html += `
        <div class="gmm-comp-card ${statusClass}">
          <div class="gmm-comp-card-top">
            <span class="gmm-time-pill">${comp.start_time} - ${comp.end_time}</span>
            <span class="pill-badge ${statusBadgeClass}">${comp.status}</span>
          </div>
          <div class="gmm-comp-grid">
            <div class="gmm-comp-side">
              <h5>Studio Version</h5>
              <p>${sLabel}</p>
              <div style="font-size:10px;color:#94a3b8;">${sSub}</div>
            </div>
            <div class="gmm-comp-side">
              <h5>Device GMM Version</h5>
              <p>${gLabel}</p>
              <div style="font-size:10px;color:#94a3b8;">${gSub}</div>
            </div>
          </div>
          ${comp.diff_details.length ? `<div style="font-size:11px;color:#f87171;">⚠️ ${comp.diff_details.join('; ')}</div>` : ''}
          ${isDiff ? `
          <div class="gmm-comp-actions">
            <button class="btn btn-xs btn-primary" onclick="resolveGMMConflict('accept_studio', '${dateStr}', ${s ? s.id : 'null'})">
              <i class="fa-solid fa-check"></i> Keep Studio
            </button>
            <button class="btn btn-xs btn-secondary" onclick="resolveGMMConflict('accept_gmm', '${dateStr}', ${s ? s.id : 'null'})">
              <i class="fa-solid fa-mobile-screen"></i> Accept GMM
            </button>
            ${s ? `<button class="btn btn-xs btn-outline" onclick="openSegmentEditModal(${s.id})"><i class="fa-solid fa-pen"></i> Edit</button>` : ''}
          </div>` : ''}
        </div>`;
      });

      listEl.innerHTML = html;
    } catch (e) {
      listEl.innerHTML = `<div style="color:#ef4444;font-size:12px;">Error comparing day: ${e.message}</div>`;
    }
  }

  window.resolveGMMConflict = async function(action, dateStr, segmentId) {
    try {
      await fetch("/api/device/resolve-conflict", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, date: dateStr, segment_id: segmentId })
      });
      loadDay(dateStr);
      loadGMMComparison(dateStr);
    } catch (e) {
      alert("Error resolving conflict: " + e.message);
    }
  };


  // Toggle Exclusion of a Breadcrumb Fix
  window.toggleExcludeBreadcrumb = async function(pointId, newExcluded) {
    try {
      await fetch("/api/breadcrumbs/toggle-exclude", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: pointId, is_excluded: newExcluded })
      });
      loadDay(currentDate);
      if (document.getElementById("tab-outliers")?.classList.contains("active")) {
        loadOutliersLeaderboard();
      }
    } catch (e) {
      alert("Error toggling breadcrumb exclusion: " + e.message);
    }
  };

  // Load Outliers & GPS Anomalies Leaderboard
  let cachedOutliers = [];
  async function loadOutliersLeaderboard() {
    const tbody = document.getElementById("outliers-table-body");
    tbody.innerHTML = '<tr><td colspan="7" class="text-center"><i class="fa-solid fa-circle-notch fa-spin"></i> Loading GPS Anomalies...</td></tr>';

    try {
      const res = await fetch("/api/outliers?limit=250");
      const data = await res.json();
      if (data.status === "SUCCESS") {
        cachedOutliers = data.outliers || [];

        // Update Summary Metrics
        const sumMap = {};
        (data.summary || []).forEach(s => sumMap[s.anomaly_type] = s.cnt);
        setElText("metric-teleport", (sumMap["TELEPORTATION"] || 0).toLocaleString());
        setElText("metric-velocity", (sumMap["EXTREME_VELOCITY"] || 0).toLocaleString());
        setElText("metric-multipath", (sumMap["MULTIPATH_BOUNCE"] || 0).toLocaleString());
        setElText("metric-scatter", (sumMap["DWELL_SCATTER"] || 0).toLocaleString());
        setElText("badge-outliers", `${Math.round(data.total_anomalies / 1000)}k`);

        renderOutliersTable();
      }
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="7" class="text-center" style="color:#f87171;">Failed to load anomalies: ${e.message}</td></tr>`;
    }
  }

  function renderOutliersTable() {
    const tbody = document.getElementById("outliers-table-body");
    const filterType = document.getElementById("outlier-filter-type").value;
    
    let filtered = cachedOutliers;
    if (filterType !== "ALL") {
      filtered = cachedOutliers.filter(o => o.anomaly_type === filterType);
    }

    if (filtered.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" class="text-center">No anomalies matching current filter.</td></tr>';
      return;
    }

    tbody.innerHTML = "";
    filtered.forEach(o => {
      const tr = document.createElement("tr");
      const timeStr = new Date(o.timestamp * 1000).toISOString().slice(11, 19);

      let badgeClass = "red";
      if (o.anomaly_type === "EXTREME_VELOCITY") badgeClass = "orange";
      else if (o.anomaly_type === "MULTIPATH_BOUNCE") badgeClass = "yellow";
      else if (o.anomaly_type === "DWELL_SCATTER") badgeClass = "purple";

      tr.innerHTML = `
        <td><a href="#" class="date-jump-link" data-date="${o.date}"><strong>${o.date}</strong></a></td>
        <td>${timeStr}</td>
        <td><span class="pill-badge ${badgeClass}">${o.anomaly_type}</span></td>
        <td><strong style="color:#f87171;">${o.speed_kmh.toFixed(0)} km/h</strong></td>
        <td style="font-size:11px;color:#cbd5e1;">${o.anomaly_reason || 'Anomaly detected'}</td>
        <td style="font-family:var(--font-mono);font-size:11px;">${o.lat.toFixed(5)}, ${o.lng.toFixed(5)}</td>
        <td>
          <div style="display:flex;gap:4px;">
            <button class="btn-secondary inspect-outlier-btn" style="padding:3px 6px;font-size:10px;" title="Inspect on Day Map">
              <i class="fa-solid fa-map-location-dot"></i> Map
            </button>
            <button class="action-btn" style="padding:3px 6px;font-size:10px;background:${o.is_excluded ? '#10b981' : '#ef4444'};" onclick="toggleExcludeBreadcrumb(${o.id}, ${o.is_excluded ? 0 : 1})">
              <i class="fa-solid ${o.is_excluded ? 'fa-rotate-left' : 'fa-ban'}"></i> ${o.is_excluded ? 'Restore' : 'Exclude'}
            </button>
          </div>
        </td>
      `;

      tr.querySelector(".inspect-outlier-btn")?.addEventListener("click", () => {
        showRawSignals = true;
        document.getElementById("btn-toggle-breadcrumbs")?.classList.add("active");
        jumpToTimelineDay(o.date, true);
        setTimeout(() => {
          map.flyTo([o.lat, o.lng], 16, { duration: 0.8 });
        }, 300);
      });

      tr.querySelector(".date-jump-link")?.addEventListener("click", (e) => {
        e.preventDefault();
        jumpToTimelineDay(o.date, true);
      });

      tbody.appendChild(tr);
    });
  }

  // Local ODLH Re-Inference Engine Trigger
  async function triggerReinferDay() {
    const btn = document.getElementById("btn-reinfer-day");
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Re-Inferring...';
    btn.disabled = true;

    try {
      const res = await fetch("/api/reinfer-day", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date: currentDate, exclude_anomalies: true })
      });
      const data = await res.json();

      const modal = document.getElementById("modal-container");
      const content = document.getElementById("modal-content");
      document.getElementById("modal-title").textContent = `Local ODLH Re-Inference (${currentDate})`;

      if (data.status === "SUCCESS" && data.result) {
        const r = data.result;
        let html = `
          <div style="font-size:13px;line-height:1.6;">
            <div style="background:rgba(16,185,129,0.1);border:1px solid #10b981;padding:10px 14px;border-radius:6px;margin-bottom:12px;">
              <strong style="color:#10b981;"><i class="fa-solid fa-circle-check"></i> Spatio-Temporal Clustering Complete</strong>
              <p style="margin:4px 0 0 0;font-size:12px;color:#cbd5e1;">${r.quality_gain}</p>
            </div>

            <h4 style="margin:10px 0 6px 0;font-size:12px;color:#94a3b8;text-transform:uppercase;">Synthesized Verified Visits (${r.reinferred_visits.length})</h4>
            <div style="max-height:160px;overflow-y:auto;margin-bottom:12px;">
        `;

        if (r.reinferred_visits.length === 0) {
          html += `<p style="color:#94a3b8;font-size:12px;">No stationary dwell stays detected (user was in transit or moving).</p>`;
        } else {
          r.reinferred_visits.forEach((v, idx) => {
            const st = new Date(v.start_ts * 1000).toISOString().slice(11, 16);
            const et = new Date(v.end_ts * 1000).toISOString().slice(11, 16);
            html += `
              <div class="card" style="padding:6px 10px;margin-bottom:4px;font-size:11px;display:flex;align-items:center;justify-content:space-between;">
                <div>
                  <strong style="color:#3b82f6;">${v.place_name || 'Home/Place'}</strong>
                  <span style="color:#94a3b8;margin-left:6px;">${st} - ${et} (${v.duration_minutes}m)</span>
                </div>
                <span class="tag-badge category-tag">${v.category || 'Place'}</span>
              </div>
            `;
          });
        }

        html += `
            </div>
            <h4 style="margin:10px 0 6px 0;font-size:12px;color:#94a3b8;text-transform:uppercase;">Synthesized Clean Travel Segments (${r.reinferred_activities.length})</h4>
            <div style="max-height:120px;overflow-y:auto;margin-bottom:12px;">
        `;

        if (r.reinferred_activities.length === 0) {
          html += `<p style="color:#94a3b8;font-size:12px;">No separate travel hops between clusters.</p>`;
        } else {
          r.reinferred_activities.forEach(a => {
            const st = new Date(a.start_ts * 1000).toISOString().slice(11, 16);
            const et = new Date(a.end_ts * 1000).toISOString().slice(11, 16);
            html += `
              <div class="card" style="padding:6px 10px;margin-bottom:4px;font-size:11px;display:flex;align-items:center;justify-content:space-between;">
                <div>
                  <strong style="color:#a855f7;">${a.activity_type}</strong>
                  <span style="color:#94a3b8;margin-left:6px;">${st} - ${et} (${(a.distance_meters/1000).toFixed(1)} km at ${a.speed_kmh} km/h)</span>
                </div>
                <span class="tag-badge snapped">✓ Clean</span>
              </div>
            `;
          });
        }

        html += `
            </div>
          </div>
          <div class="form-actions">
            <button id="modal-close-reinfer" class="btn-primary">Done</button>
          </div>
        `;

        content.innerHTML = html;
        modal.classList.remove("hidden");
        document.getElementById("modal-close-reinfer").onclick = () => modal.classList.add("hidden");
      }
    } catch (e) {
      alert("Error executing re-inference: " + e.message);
    } finally {
      btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Re-Infer Day';
      btn.disabled = false;
    }
  }



  // Event Listeners
  function setupEvents() {
    document.getElementById("date-picker")?.addEventListener("change", (e) => loadDay(e.target.value));

    document.getElementById("btn-prev-day")?.addEventListener("click", () => {
      loadDay(stepDate(currentDate, -1));
    });

    document.getElementById("btn-next-day")?.addEventListener("click", () => {
      loadDay(stepDate(currentDate, 1));
    });

    // Breadcrumbs Layer Toggle
    const btnBreadcrumbs = document.getElementById("btn-toggle-breadcrumbs") || document.getElementById("btn-toggle-raw");
    if (btnBreadcrumbs) {
      btnBreadcrumbs.addEventListener("click", (e) => {
        showRawSignals = !showRawSignals;
        btnBreadcrumbs.classList.toggle("active", showRawSignals);
        loadDay(currentDate);
      });
    }

    document.getElementById("btn-jump-today")?.addEventListener("click", () => {
      loadDay(getLocalToday());
    });

    document.getElementById("btn-reinfer-day")?.addEventListener("click", triggerReinferDay);
    document.getElementById("btn-re-evaluate-outliers")?.addEventListener("click", loadOutliersLeaderboard);
    document.getElementById("outlier-filter-type")?.addEventListener("change", renderOutliersTable);

    document.getElementById("btn-sync-device")?.addEventListener("click", async () => {
      const btn = document.getElementById("btn-sync-device");
      const oldHtml = btn.innerHTML;
      btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Syncing...';
      btn.disabled = true;
      try {
        const res = await fetch("/api/sync-device", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
        const data = await res.json();
        if (data.status === "SUCCESS") {
          alert("✓ " + data.message);
          loadDay(currentDate);
          loadOverview();
        } else {
          alert("⚠ " + (data.message || data.error || "Device sync completed with warnings."));
        }
      } catch (e) {
        alert("Error connecting to ADB extraction daemon: " + e.message);
      } finally {
        btn.innerHTML = oldHtml;
        btn.disabled = false;
      }
    });

    // GMM Comparator & Live Side Panel Bindings
    document.getElementById("btn-inspect-gmm")?.addEventListener("click", () => openGMMComparator(currentDate));
    document.getElementById("btn-gmm-close")?.addEventListener("click", closeGMMComparator);
    document.getElementById("btn-gmm-sync-day")?.addEventListener("click", () => syncGMMDate(currentDate));
    document.getElementById("btn-gmm-refresh")?.addEventListener("click", refreshGMMScreen);
    document.getElementById("btn-gmm-key-back")?.addEventListener("click", () => sendGMMTouch("key", 4));
    document.getElementById("btn-gmm-key-home")?.addEventListener("click", () => sendGMMTouch("key", 3));
    document.getElementById("btn-gmm-open-cal")?.addEventListener("click", () => sendGMMTouch("tap", 480, 1315));
    document.getElementById("gmm-auto-refresh")?.addEventListener("change", startGMMStream);

    const screenBox = document.getElementById("gmm-screen-box");
    screenBox?.addEventListener("click", (e) => {
      const rect = screenBox.getBoundingClientRect();
      const clickX = e.clientX - rect.left;
      const clickY = e.clientY - rect.top;
      const devX = Math.round((clickX / rect.width) * 1080);
      const devY = Math.round((clickY / rect.height) * 2400);
      sendGMMTouch("tap", devX, devY);
    });

    document.getElementById("btn-export-day")?.addEventListener("click", () => {
      window.open(`/api/export?date=${currentDate}&format=geojson`, "_blank");
    });


    document.getElementById("btn-refresh-nuggets")?.addEventListener("click", () => {
      loadArchiveNuggets();
    });

    document.getElementById("gap-filter-duration")?.addEventListener("change", loadDiagnosticsGaps);

    function getGlobalSearchQuery() {
      return document.getElementById("global-search-input")?.value?.trim() || "";
    }

    // Category Filter Pills
    document.querySelectorAll(".cat-pill").forEach(pill => {
      pill.addEventListener("click", () => {
        document.querySelectorAll(".cat-pill").forEach(p => p.classList.remove("active"));
        pill.classList.add("active");
        currentCategory = pill.getAttribute("data-cat");
        loadPlaces(getGlobalSearchQuery());
      });
    });

    // City Selector
    document.getElementById("places-city-select")?.addEventListener("change", (e) => {
      currentCity = e.target.value;
      loadPlaces(getGlobalSearchQuery());
    });

    // Sort Selector
    document.getElementById("places-sort-select")?.addEventListener("change", (e) => {
      currentSort = e.target.value;
      loadPlaces(getGlobalSearchQuery());
    });

    // Reviewed Only Toggle
    document.getElementById("places-reviewed-only")?.addEventListener("change", (e) => {
      reviewedOnly = e.target.checked;
      loadPlaces(getGlobalSearchQuery());
    });

    const modalEl = document.getElementById("modal-container");
    document.getElementById("modal-close-btn")?.addEventListener("click", () => {
      modalEl?.classList.add("hidden");
    });
    modalEl?.addEventListener("click", (e) => {
      if (e.target === modalEl) modalEl.classList.add("hidden");
    });
  }

  // TRIPS & 3D FLYTHROUGH ENGINE
  let cachedTrips = [];
  let currentTripCountry = "ALL";
  let flyMap = null;
  let flyAnimationId = null;
  let flyCurrentIdx = 0;
  let flyTrajectory = [];
  let flyHotspots = [];
  let flyGliderMarker = null;
  let flyRoutePolyline = null;
  let isFlying = false;

  async function loadPassportStats() {
    try {
      const res = await fetch("/api/trips/stats");
      const data = await res.json();
      if (data.status === "SUCCESS") {
        setElText("stat-earth-orbits", `${data.earth_orbits}x`);
        setElText("stat-total-flights", data.total_flights);
        setElText("stat-total-countries", data.total_countries);
        setElText("stat-total-trips", data.total_trips);

        const pillsContainer = document.getElementById("country-pills-container");
        pillsContainer.innerHTML = "";

        const allPill = document.createElement("button");
        allPill.className = `country-pill ${currentTripCountry === "ALL" ? "active" : ""}`;
        allPill.innerHTML = `🌍 All Countries (${data.total_trips})`;
        allPill.addEventListener("click", () => {
          document.querySelectorAll(".country-pill").forEach(p => p.classList.remove("active"));
          allPill.classList.add("active");
          currentTripCountry = "ALL";
          loadTrips(getGlobalSearchQuery(), "ALL");
        });
        pillsContainer.appendChild(allPill);

        data.countries.forEach(c => {
          const pill = document.createElement("button");
          pill.className = `country-pill ${currentTripCountry === c.country ? "active" : ""}`;
          pill.innerHTML = `${c.flag} ${c.country} (${c.trips_count} visits · ${Math.round(c.total_days)}d)`;
          pill.addEventListener("click", () => {
            document.querySelectorAll(".country-pill").forEach(p => p.classList.remove("active"));
            pill.classList.add("active");
            currentTripCountry = c.country;
            loadTrips(getGlobalSearchQuery(), c.country);
          });
          pillsContainer.appendChild(pill);
        });
      }

      loadArchiveNuggets();
    } catch (e) {
      console.error("Error loading passport stats:", e);
    }
  }

  // -------------------------------------------------------------
  // Activity Summaries & Insights Tab Loader
  // -------------------------------------------------------------
  let currentActivityPeriod = "all";

  async function loadActivitySummaries(period = null) {
    if (period) currentActivityPeriod = period;
    const heroGrid = document.getElementById("activities-hero-grid");
    const pillsContainer = document.getElementById("activities-period-pills-container");
    const bar = document.getElementById("mode-progress-bar");
    const cardsGrid = document.getElementById("mode-cards-grid");
    const nuggetsGrid = document.getElementById("activities-nuggets-container");
    const topPlacesEl = document.getElementById("activities-top-places");
    const rareModesEl = document.getElementById("activities-rare-modes");
    const subLabel = document.getElementById("activities-period-sub");

    if (heroGrid) heroGrid.innerHTML = '<div class="loading-spinner" style="grid-column:1/-1;padding:30px;"><i class="fa-solid fa-circle-notch fa-spin"></i> Calculating Activity Summaries...</div>';

    try {
      const res = await fetch(`/api/insights/activity-summaries?period=${encodeURIComponent(currentActivityPeriod)}`);
      const data = await res.json();
      if (data.status !== "SUCCESS") return;

      if (subLabel) {
        subLabel.textContent = currentActivityPeriod === "all" ? 
          "Comprehensive lifetime movement metrics across your entire timeline" : 
          `Movement and distance breakdown for calendar year ${currentActivityPeriod}`;
      }

      // 1. Period Pills
      if (pillsContainer && data.available_periods) {
        pillsContainer.innerHTML = "";
        data.available_periods.forEach(p => {
          const btn = document.createElement("button");
          btn.className = `cat-pill ${currentActivityPeriod === p ? 'active' : ''}`;
          btn.textContent = p === "all" ? "All Time" : p;
          btn.addEventListener("click", () => {
            currentActivityPeriod = p;
            loadActivitySummaries(p);
          });
          pillsContainer.appendChild(btn);
        });
      }

      // 2. Hero Cards
      if (heroGrid) {
        const tot = data.totals || {};
        heroGrid.innerHTML = `
          <div class="stat-card card" style="padding:16px;">
            <div style="font-size:11.5px;color:var(--text-muted);text-transform:uppercase;font-weight:700;margin-bottom:4px;">Total Distance</div>
            <div style="font-size:24px;font-weight:800;color:var(--accent-blue);font-family:var(--font-mono);">${tot.total_distance_km ? tot.total_distance_km.toLocaleString() : 0} <span style="font-size:14px;font-weight:600;">km</span></div>
            <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">Across ${tot.total_activities ? tot.total_activities.toLocaleString() : 0} movements</div>
          </div>
          <div class="stat-card card" style="padding:16px;">
            <div style="font-size:11.5px;color:var(--text-muted);text-transform:uppercase;font-weight:700;margin-bottom:4px;">Time in Motion</div>
            <div style="font-size:24px;font-weight:800;color:var(--accent-green);font-family:var(--font-mono);">${tot.total_hours ? tot.total_hours.toLocaleString() : 0} <span style="font-size:14px;font-weight:600;">hrs</span></div>
            <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">Active transit & journey time</div>
          </div>
          <div class="stat-card card" style="padding:16px;">
            <div style="font-size:11.5px;color:var(--text-muted);text-transform:uppercase;font-weight:700;margin-bottom:4px;">Bicycle Travel</div>
            <div style="font-size:24px;font-weight:800;color:#f59e0b;font-family:var(--font-mono);">${tot.cycle_km ? tot.cycle_km.toLocaleString() : 0} <span style="font-size:14px;font-weight:600;">km</span></div>
            <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">${tot.transcon_cycles || 0}x Coast-to-Coast USA equivalents</div>
          </div>
          <div class="stat-card card" style="padding:16px;">
            <div style="font-size:11.5px;color:var(--text-muted);text-transform:uppercase;font-weight:700;margin-bottom:4px;">Cosmic Flight</div>
            <div style="font-size:24px;font-weight:800;color:#a855f7;font-family:var(--font-mono);">${tot.fly_km ? tot.fly_km.toLocaleString() : 0} <span style="font-size:14px;font-weight:600;">km</span></div>
            <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">${tot.earth_orbits || 0}x Earth orbits · ${tot.moon_trips || 0}x Moon distance</div>
          </div>
        `;
      }

      // 3. Mode Progress Bar
      if (bar) {
        bar.innerHTML = "";
        (data.modes || []).forEach(m => {
          if (m.pct_distance > 0.5) {
            const seg = document.createElement("div");
            seg.style.width = `${m.pct_distance}%`;
            seg.style.background = m.color;
            seg.title = `${m.label}: ${m.total_km.toLocaleString()} km (${m.pct_distance}%)`;
            bar.appendChild(seg);
          }
        });
      }

      // 4. Mode Cards Grid
      if (cardsGrid) {
        cardsGrid.innerHTML = "";
        (data.modes || []).forEach(m => {
          const card = document.createElement("div");
          card.className = "mode-summary-card card";
          card.style.padding = "14px 16px";
          card.style.display = "flex";
          card.style.alignItems = "center";
          card.style.gap = "12px";
          card.style.borderLeft = `4px solid ${m.color}`;

          card.innerHTML = `
            <div style="width:38px;height:38px;border-radius:8px;background:${m.color}20;color:${m.color};display:flex;align-items:center;justify-content:center;font-size:16px;">
              <i class="fa-solid ${m.icon}"></i>
            </div>
            <div style="flex:1;">
              <div style="display:flex;justify-content:space-between;align-items:center;">
                <strong style="font-size:13.5px;color:var(--text-main);">${escapeHtml(m.label)}</strong>
                <span class="tag-badge" style="font-size:10.5px;background:${m.color}20;color:${m.color};font-weight:700;">${m.pct_distance}%</span>
              </div>
              <div style="display:flex;gap:12px;margin-top:4px;font-size:12px;color:var(--text-muted);font-family:var(--font-mono);">
                <span><strong style="color:var(--text-main);">${m.total_km.toLocaleString()}</strong> km</span>
                <span><strong style="color:var(--text-main);">${m.total_hours.toLocaleString()}</strong> hrs</span>
                <span><strong>${m.count.toLocaleString()}</strong> legs</span>
              </div>
            </div>
          `;
          cardsGrid.appendChild(card);
        });
      }

      // 5. Curated Nuggets
      if (nuggetsGrid) {
        nuggetsGrid.innerHTML = "";
        (data.curated_nuggets || []).forEach(n => {
          const card = document.createElement("div");
          card.className = "nugget-card card";
          card.style.padding = "16px";
          card.innerHTML = `
            <div class="nugget-badge" style="background:${n.accent}20;color:${n.accent};font-size:11px;font-weight:700;display:inline-block;padding:3px 8px;border-radius:4px;margin-bottom:8px;">
              <i class="fa-solid ${n.icon}"></i> ${escapeHtml(n.badge || n.category)}
            </div>
            <div class="nugget-title" style="font-size:14px;font-weight:700;color:var(--text-main);margin-bottom:4px;">${escapeHtml(n.title)}</div>
            <div class="nugget-subtitle" style="font-size:11.5px;color:var(--text-muted);margin-bottom:8px;">
              <i class="fa-regular fa-calendar"></i> ${n.date} · ${escapeHtml(n.subtitle)}
            </div>
            <div class="nugget-why" style="font-size:12px;color:var(--text-muted);line-height:1.4;">
              ${escapeHtml(n.why)}
            </div>
          `;
          if (n.date && n.date !== "Lifetime") {
            card.style.cursor = "pointer";
            card.title = `Jump to timeline for ${n.date}`;
            card.addEventListener("click", () => jumpToTimelineDay(n.date, true));
          }
          nuggetsGrid.appendChild(card);
        });
      }

      // 6. Top Visited Venues
      if (topPlacesEl) {
        topPlacesEl.innerHTML = "";
        (data.top_places || []).forEach((p, idx) => {
          const row = document.createElement("div");
          row.style.display = "flex";
          row.style.alignItems = "center";
          row.style.justifyContent = "space-between";
          row.style.padding = "8px 12px";
          row.style.background = "var(--bg-subtle)";
          row.style.borderRadius = "8px";
          row.style.fontSize = "12px";
          row.style.cursor = "pointer";

          row.innerHTML = `
            <div style="display:flex;align-items:center;gap:8px;">
              <span style="font-weight:700;color:var(--text-muted);font-family:var(--font-mono);font-size:11px;">#${idx + 1}</span>
              <strong style="color:var(--text-main);">${escapeHtml(p.name)}</strong>
              ${p.city ? `<span style="color:var(--text-muted);font-size:11px;">(${escapeHtml(p.city)})</span>` : ''}
            </div>
            <span class="tag-badge" style="font-size:10.5px;background:rgba(59,130,246,0.15);color:var(--accent-blue);font-weight:700;">
              ${p.visit_count} visits
            </span>
          `;
          row.addEventListener("click", () => openPlaceVisitsModal(p.place_id, p.name));
          topPlacesEl.appendChild(row);
        });
      }

      // 7. Rare Micro-Adventures
      if (rareModesEl) {
        rareModesEl.innerHTML = "";
        (data.rare_modes || []).forEach(r => {
          const pill = document.createElement("div");
          pill.style.display = "flex";
          pill.style.alignItems = "center";
          pill.style.gap = "6px";
          pill.style.padding = "6px 12px";
          pill.style.background = `${r.color}18`;
          pill.style.border = `1px solid ${r.color}40`;
          pill.style.borderRadius = "20px";
          pill.style.fontSize = "11.5px";
          pill.style.color = r.color;
          pill.style.fontWeight = "600";
          pill.style.cursor = r.highlight_date ? "pointer" : "default";

          pill.innerHTML = `
            <i class="fa-solid ${r.icon}"></i>
            <span>${escapeHtml(r.title)} (${r.count}x · ${r.total_km} km)</span>
          `;
          if (r.highlight_date) {
            pill.title = `View peak session on ${r.highlight_date} (${r.highlight_dist_km} km)`;
            pill.addEventListener("click", () => jumpToTimelineDay(r.highlight_date, true));
          }
          rareModesEl.appendChild(pill);
        });
      }

    } catch (e) {
      console.error("Error loading activity summaries:", e);
      if (heroGrid) heroGrid.innerHTML = `<div class="empty-state">Error loading activity summaries: ${escapeHtml(e.message)}</div>`;
    }
  }

  document.getElementById("btn-refresh-activity-nuggets")?.addEventListener("click", () => {
    loadActivitySummaries(currentActivityPeriod);
  });

  // -------------------------------------------------------------
  // Archive Nuggets & Curiosities Loader
  // -------------------------------------------------------------
  async function loadArchiveNuggets() {
    const grid = document.getElementById("nuggets-grid-container");
    const rareContainer = document.getElementById("rare-modes-container");
    if (!grid) return;

    try {
      const res = await fetch("/api/insights/nuggets");
      const data = await res.json();
      if (data.status !== "SUCCESS") return;

      grid.innerHTML = "";
      (data.nuggets || []).forEach(n => {
        const card = document.createElement("div");
        card.className = "nugget-card";
        card.innerHTML = `
          <div class="nugget-badge" style="background:${n.accent}20;color:${n.accent};">
            <i class="fa-solid ${n.icon}"></i> ${escapeHtml(n.badge)}
          </div>
          <div class="nugget-title">${escapeHtml(n.title)}</div>
          <div class="nugget-subtitle">
            <i class="fa-solid fa-calendar-day" style="color:var(--text-muted);"></i> ${escapeHtml(n.date)} · ${escapeHtml(n.subtitle)}
          </div>
          <div class="nugget-why">
            <strong>Why:</strong> ${escapeHtml(n.why)}
          </div>
        `;
        if (n.date && n.date !== "Lifetime") {
          card.title = `Jump to timeline for ${n.date}`;
          card.addEventListener("click", () => {
            jumpToTimelineDay(n.date, true);
          });
        }
        grid.appendChild(card);
      });

      if (rareContainer && data.rare_modes) {
        rareContainer.innerHTML = "";
        data.rare_modes.forEach(rm => {
          const pill = document.createElement("div");
          pill.className = "rare-mode-pill";
          pill.innerHTML = `
            <i class="fa-solid ${rm.icon}" style="color:${rm.color};font-size:13px;"></i>
            <span><strong>${rm.title}:</strong> ${rm.count} outing${rm.count > 1 ? 's' : ''} (${rm.total_km} km · ${rm.total_hours}h)</span>
          `;
          if (rm.highlight_date) {
            pill.title = `View peak session on ${rm.highlight_date} (${rm.highlight_dist_km} km)`;
            pill.addEventListener("click", () => {
              jumpToTimelineDay(rm.highlight_date, true);
            });
          }
          rareContainer.appendChild(pill);
        });
      }
    } catch (e) {
      console.error("Error loading archive nuggets:", e);
    }
  }

  async function loadTrips(searchQuery = "", country = currentTripCountry) {
    currentTripCountry = country;
    const container = document.getElementById("trips-grid-container");
    container.innerHTML = '<div class="loading-spinner"><i class="fa-solid fa-circle-notch fa-spin"></i> Loading Trips & Expeditions...</div>';

    try {
      const url = country && country !== "ALL" 
        ? `/api/trips?limit=150&country=${encodeURIComponent(country)}`
        : `/api/trips?limit=150`;
      const res = await fetch(url);
      const data = await res.json();
      if (data.status === "SUCCESS") {
        cachedTrips = data.trips;
        document.getElementById("badge-trips").textContent = data.count || cachedTrips.length;
        document.getElementById("trips-count-sub").textContent = `Showing ${cachedTrips.length} trips ${country !== "ALL" ? `in ${country}` : 'worldwide'} with 3D Flythrough and Night Walk mode`;
      }
    } catch (e) {
      console.error("Error loading trips:", e);
      container.innerHTML = '<div class="empty-state"><p>Failed to load trips.</p></div>';
      return;
    }

    let filtered = cachedTrips;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      filtered = cachedTrips.filter(t => 
        t.title.toLowerCase().includes(q) ||
        t.start_date.includes(q) ||
        t.end_date.includes(q) ||
        (t.country && t.country.toLowerCase().includes(q)) ||
        (t.highlights && t.highlights.some(h => h.name.toLowerCase().includes(q)))
      );
    }

    renderTripsGrid(filtered);
  }

  function renderTripsGrid(trips) {
    const container = document.getElementById("trips-grid-container");
    container.innerHTML = "";

    if (!trips || trips.length === 0) {
      container.innerHTML = '<div class="empty-state" style="grid-column: 1 / -1;"><p>No matching trips or expeditions found.</p></div>';
      return;
    }

    trips.forEach(t => {
      const card = document.createElement("div");
      card.className = "trip-card";

      const themeClass = t.theme || "world";
      const flightsBadge = t.flights_count > 0 ? `<span style="color:#ec4899;font-size:11px;font-weight:600;"><i class="fa-solid fa-plane"></i> ${t.flights_count} Flights</span>` : '';

      let highlightsHtml = '';
      if (t.highlights && t.highlights.length > 0) {
        highlightsHtml = `
          <div class="trip-highlights-list">
            ${t.highlights.slice(0, 3).map(h => `
              <div class="trip-highlight-item">
                <i class="fa-solid fa-location-dot"></i>
                <span style="font-weight:500;">${h.name}</span>
                ${h.rating ? `<span style="color:#fbbf24;font-size:10px;margin-left:auto;"><i class="fa-solid fa-star"></i> ${h.rating}</span>` : ''}
              </div>
            `).join('')}
          </div>
        `;
      }

      card.innerHTML = `
        <div class="trip-hero-row">
          <span class="trip-badge-theme ${themeClass}">${t.country_flag || '🌍'} ${t.country || 'USA'}</span>
          ${flightsBadge}
        </div>
        <div>
          <h3 class="trip-dest-title">${t.title}</h3>
          <span class="trip-dates"><i class="fa-solid fa-calendar"></i> ${t.start_date} → ${t.end_date} (${t.duration_days} days)</span>
        </div>

        <div class="trip-metrics-row">
          <div class="trip-metric-item">
            <span class="trip-metric-val">${(t.total_distance_km).toLocaleString()} km</span>
            <span class="trip-metric-lbl">Distance</span>
          </div>
          <div class="trip-metric-item">
            <span class="trip-metric-val">${t.visits_count}</span>
            <span class="trip-metric-lbl">Stops</span>
          </div>
          <div class="trip-metric-item">
            <span class="trip-metric-val">${t.activities_count}</span>
            <span class="trip-metric-lbl">Activities</span>
          </div>
        </div>

        ${highlightsHtml}

        <div class="trip-actions-row">
          <button class="btn-primary btn-open-flythrough" data-trip="${t.trip_id}" style="flex:1;padding:8px;font-size:12px;display:flex;align-items:center;justify-content:center;gap:6px;">
            <i class="fa-solid fa-person-walking-arrow-right"></i> 3D Flythrough / Night Walk
          </button>
          <button class="action-btn btn-view-trip-day" data-date="${t.start_date}" title="View Daily Timeline" style="padding:8px 12px;">
            <i class="fa-solid fa-calendar-day"></i>
          </button>
        </div>
      `;

      card.querySelector(".btn-open-flythrough").addEventListener("click", () => openFlythroughPlayer(t.trip_id, t.title));
      card.querySelector(".btn-view-trip-day").addEventListener("click", () => {
        jumpToTimelineDay(t.start_date, true);
      });

      container.appendChild(card);
    });
  }

  // -------------------------------------------------------------
  // Google Earth 3D Route Ride-Along & Tour Studio
  // -------------------------------------------------------------
  let earthMap = null;
  let earthTrajectory = [];
  let earthHotspots = [];
  let earthCurrentIdx = 0;
  let isRiding = false;
  let earthAnimationId = null;
  let earthActiveSegmentId = null;
  let earthActiveTripId = null;
  let earthRiderMarker = null;

  async function openFlythroughPlayer(tripId, tripTitle) {
    return openEarthRidePlayer(tripId, true, tripTitle);
  }

  async function openEarthRidePlayer(targetId, isTrip = false, tripTitle = null) {
    const modal = document.getElementById("flythrough-modal");
    modal.classList.remove("hidden");
    document.getElementById("floating-hotspot-card")?.classList.add("hidden");

    earthActiveSegmentId = !isTrip ? targetId : null;
    earthActiveTripId = isTrip ? targetId : null;

    try {
      const url = isTrip 
        ? `/api/trips/flythrough?trip_id=${targetId}`
        : `/api/segments/3d-tour?segment_id=${targetId}`;
      const res = await fetch(url);
      const data = await res.json();
      if (data.status !== "SUCCESS") return;

      earthTrajectory = data.trajectory || [];
      earthHotspots = data.hotspots || [];
      earthCurrentIdx = 0;
      isRiding = false;

      // Update Top Bar & KML Export link
      const locTitle = isTrip 
        ? `${tripTitle || data.title} (${data.start_date || ''})`
        : `Location history from ${data.date || currentDate}`;
      document.getElementById("earth-tour-location-title").textContent = locTitle;

      const kmlBtn = document.getElementById("btn-export-earth-kml");
      if (kmlBtn) {
        kmlBtn.onclick = () => {
          window.location.href = isTrip
            ? `/api/trips/flythrough?trip_id=${targetId}`
            : `/api/segments/export-kml?segment_id=${targetId}`;
        };
      }

      // Populate Google Earth HUD Card (exact replica of Google Earth mock-up)
      const mode = data.mode || data.title || "Movement";
      document.getElementById("hud-activity-title").textContent = mode;
      document.getElementById("hud-activity-desc").textContent = data.description || `${mode} trajectory`;
      
      const iconWrap = document.getElementById("hud-mode-icon");
      if (iconWrap) {
        let mIcon = "fa-person-walking";
        const upMode = mode.toUpperCase();
        if (upMode.includes("CYCLE") || upMode.includes("BIKE")) mIcon = "fa-bicycle";
        else if (upMode.includes("TAXI") || upMode.includes("CAB")) mIcon = "fa-taxi";
        else if (upMode.includes("DRIVE") || upMode.includes("VEHICLE") || upMode.includes("CAR")) mIcon = "fa-car";
        else if (upMode.includes("FLY") || upMode.includes("FLIGHT")) mIcon = "fa-plane";
        else if (upMode.includes("TRAIN") || upMode.includes("SUBWAY")) mIcon = "fa-train-subway";
        iconWrap.innerHTML = `<i class="fa-solid ${mIcon}"></i>`;
      }

      const distKm = ((data.distance_meters || 0) / 1000.0).toFixed(1);
      document.getElementById("hud-progress-val").innerHTML = `0.0 / ${distKm} <small>km</small>`;
      document.getElementById("hud-speed-val").innerHTML = `${data.avg_speed_kmh || 0.0} <small>km/h</small>`;
      document.getElementById("hud-origin-name").textContent = data.origin_name || "Origin";
      document.getElementById("hud-dest-name").textContent = data.dest_name || "Destination";

      document.getElementById("btn-fly-play").innerHTML = '<i class="fa-solid fa-play"></i> Play Ride';
      document.getElementById("fly-scrubber-range").value = 0;
      document.getElementById("fly-progress-text").textContent = "0%";

      if (!earthTrajectory.length) return;

      const firstPt = earthTrajectory[0];
      const initialLng = firstPt.lng;
      const initialLat = firstPt.lat;
      const initialBearing = firstPt.bearing || 0;

      // Initialize MapLibre GL 3D Engine with Satellite Tiles
      const container = document.getElementById("earth-tour-map");
      container.innerHTML = "";

      if (window.maplibregl) {
        earthMap = new maplibregl.Map({
          container: "earth-tour-map",
          style: {
            version: 8,
            sources: {
              satellite: {
                type: "raster",
                tiles: [
                  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
                ],
                tileSize: 256
              }
            },
            layers: [
              {
                id: "satellite-layer",
                type: "raster",
                source: "satellite",
                minzoom: 0,
                maxzoom: 20
              }
            ]
          },
          center: [initialLng, initialLat],
          zoom: 17.2,
          pitch: 62,
          bearing: initialBearing,
          attributionControl: false
        });

        earthMap.on("load", () => {
          const routeCoords = earthTrajectory.map(pt => [pt.lng, pt.lat]);

          earthMap.addSource("route-source", {
            type: "geojson",
            data: {
              type: "Feature",
              properties: {},
              geometry: {
                type: "LineString",
                coordinates: routeCoords
              }
            }
          });

          // Route Casing
          earthMap.addLayer({
            id: "route-casing",
            type: "line",
            source: "route-source",
            layout: { "line-join": "round", "line-cap": "round" },
            paint: {
              "line-color": "#7f1d1d",
              "line-width": 8,
              "line-opacity": 0.85
            }
          });

          // Red Route Core (Vibrant Crimson)
          earthMap.addLayer({
            id: "route-core",
            type: "line",
            source: "route-source",
            layout: { "line-join": "round", "line-cap": "round" },
            paint: {
              "line-color": "#ef4444",
              "line-width": 5,
              "line-opacity": 0.98
            }
          });

          // Add Rider Beacon Marker
          const el = document.createElement("div");
          el.className = "rider-3d-beacon";
          el.innerHTML = `
            <div style="width:22px;height:22px;border-radius:50%;background:#ef4444;border:3px solid #ffffff;box-shadow:0 0 14px rgba(239,68,68,0.95),0 4px 10px rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;color:#fff;font-size:11px;">
              <i class="fa-solid fa-location-arrow" id="rider-beacon-arrow" style="transform:rotate(${initialBearing}deg);"></i>
            </div>
          `;
          earthRiderMarker = new maplibregl.Marker({ element: el })
            .setLngLat([initialLng, initialLat])
            .addTo(earthMap);

          // Add Start & End Markers
          if (routeCoords.length >= 2) {
            new maplibregl.Marker({ color: "#ef4444" })
              .setLngLat(routeCoords[0])
              .setPopup(new maplibregl.Popup({ offset: 25 }).setText(data.origin_name || "Origin"))
              .addTo(earthMap);

            new maplibregl.Marker({ color: "#22c55e" })
              .setLngLat(routeCoords[routeCoords.length - 1])
              .setPopup(new maplibregl.Popup({ offset: 25 }).setText(data.dest_name || "Destination"))
              .addTo(earthMap);
          }
        });
      }

    } catch (e) {
      console.error("Error opening 3D Earth ride:", e);
    }
  }

  function stepEarthRide() {
    if (!isRiding || !earthTrajectory.length || !earthMap) return;

    const speed = parseInt(document.getElementById("fly-speed-select")?.value, 10) || 3;
    earthCurrentIdx = Math.min(earthTrajectory.length - 1, earthCurrentIdx + speed);

    const pt = earthTrajectory[earthCurrentIdx];
    if (pt) {
      const cameraMode = document.getElementById("fly-camera-mode")?.value || "chase";
      let targetPitch = 65;
      let targetZoom = 17.5;
      let targetBearing = pt.bearing || 0;

      if (cameraMode === "oblique") {
        targetPitch = 45;
        targetZoom = 16.2;
        targetBearing = (pt.bearing || 0) - 25;
      } else if (cameraMode === "cockpit") {
        targetPitch = 75;
        targetZoom = 18.5;
        targetBearing = pt.bearing || 0;
      } else if (cameraMode === "topdown") {
        targetPitch = 0;
        targetZoom = 15.5;
        targetBearing = 0;
      }

      earthMap.easeTo({
        center: [pt.lng, pt.lat],
        bearing: targetBearing,
        pitch: targetPitch,
        zoom: targetZoom,
        duration: 250,
        easing: (t) => t
      });

      if (earthRiderMarker) {
        earthRiderMarker.setLngLat([pt.lng, pt.lat]);
        const arrow = document.getElementById("rider-beacon-arrow");
        if (arrow) arrow.style.transform = `rotate(${pt.bearing || 0}deg)`;
      }

      const pct = Math.round((earthCurrentIdx / (earthTrajectory.length - 1)) * 100);
      const rangeEl = document.getElementById("fly-scrubber-range");
      if (rangeEl) rangeEl.value = pct;
      const progEl = document.getElementById("fly-progress-text");
      if (progEl) progEl.textContent = `${pct}%`;

      const totalKmStr = document.getElementById("hud-activity-desc")?.textContent.match(/Distance (\d+)m/);
      const totalDistM = totalKmStr ? parseInt(totalKmStr[1], 10) : 2500;
      const covKm = ((earthCurrentIdx / (earthTrajectory.length - 1)) * (totalDistM / 1000.0)).toFixed(1);
      const totKm = (totalDistM / 1000.0).toFixed(1);
      const progVal = document.getElementById("hud-progress-val");
      if (progVal) progVal.innerHTML = `${covKm} / ${totKm} <small>km</small>`;
      
      const deg = Math.round(pt.bearing || 0);
      const compassDirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
      const compStr = compassDirs[Math.round(deg / 45) % 8];
      const bearVal = document.getElementById("hud-bearing-val");
      if (bearVal) bearVal.innerHTML = `${String(deg).padStart(3, '0')}° <small>${compStr}</small>`;
    }

    if (earthCurrentIdx >= earthTrajectory.length - 1) {
      isRiding = false;
      document.getElementById("btn-fly-play").innerHTML = '<i class="fa-solid fa-rotate-left"></i> Replay Ride';
      return;
    }

    earthAnimationId = requestAnimationFrame(stepEarthRide);
  }

  // Playback Controls
  document.getElementById("btn-fly-play")?.addEventListener("click", () => {
    if (!isRiding) {
      if (earthCurrentIdx >= earthTrajectory.length - 1) earthCurrentIdx = 0;
      isRiding = true;
      document.getElementById("btn-fly-play").innerHTML = '<i class="fa-solid fa-pause"></i> Pause';
      stepEarthRide();
    } else {
      isRiding = false;
      document.getElementById("btn-fly-play").innerHTML = '<i class="fa-solid fa-play"></i> Play Ride';
      if (earthAnimationId) cancelAnimationFrame(earthAnimationId);
    }
  });

  document.getElementById("btn-hud-replay")?.addEventListener("click", () => {
    earthCurrentIdx = 0;
    isRiding = true;
    document.getElementById("btn-fly-play").innerHTML = '<i class="fa-solid fa-pause"></i> Pause';
    stepEarthRide();
  });

  document.getElementById("fly-scrubber-range")?.addEventListener("input", (e) => {
    if (!earthTrajectory.length) return;
    const pct = parseInt(e.target.value, 10);
    earthCurrentIdx = Math.round((pct / 100) * (earthTrajectory.length - 1));
    const pt = earthTrajectory[earthCurrentIdx];
    if (pt && earthMap) {
      earthMap.setCenter([pt.lng, pt.lat]);
      if (earthRiderMarker) earthRiderMarker.setLngLat([pt.lng, pt.lat]);
      document.getElementById("fly-progress-text").textContent = `${pct}%`;
    }
  });

  function close3DModal() {
    isRiding = false;
    if (earthAnimationId) {
      cancelAnimationFrame(earthAnimationId);
      earthAnimationId = null;
    }
    const modal = document.getElementById("flythrough-modal");
    if (modal) modal.classList.add("hidden");
  }

  document.getElementById("btn-fly-close")?.addEventListener("click", close3DModal);
  document.getElementById("btn-hud-close")?.addEventListener("click", close3DModal);

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      const flyModal = document.getElementById("flythrough-modal");
      if (flyModal && !flyModal.classList.contains("hidden")) {
        close3DModal();
      }
      const genericModal = document.getElementById("modal-container");
      if (genericModal && !genericModal.classList.contains("hidden")) {
        genericModal.classList.add("hidden");
      }
    }
  });

  window.addEventListener("popstate", (e) => {
    const params = new URLSearchParams(window.location.search);
    const tabFromUrl = params.get("tab") || (e.state && e.state.tab) || "timeline";
    const dateFromUrl = params.get("date") || (e.state && e.state.date) || getLocalToday();

    if (tabFromUrl !== "timeline") {
      navOriginTab = null;
    } else if (e.state && e.state.fromTab) {
      navOriginTab = e.state.fromTab;
    }

    switchTab(tabFromUrl, false);
    if (tabFromUrl === "timeline") {
      loadDay(dateFromUrl, false);
      updateOriginBanner();
    }
  });

  // -------------------------------------------------------------
  // Universal Global Search Handler (Always Available)
  // -------------------------------------------------------------
  function initGlobalSearch() {
    const input = document.getElementById("global-search-input");
    const dropdown = document.getElementById("global-search-dropdown");
    const clearBtn = document.getElementById("global-search-clear");
    if (!input || !dropdown) return;

    let debounceTimer = null;
    let selectedIdx = -1;
    let currentResults = [];

    // Global Shortcuts: Cmd+K / Ctrl+K / '/' to focus search input
    window.addEventListener("keydown", (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        input.focus();
        input.select();
      } else if (e.key === "/" && document.activeElement.tagName !== "INPUT" && document.activeElement.tagName !== "TEXTAREA") {
        e.preventDefault();
        input.focus();
        input.select();
      }
    });

    let tabLiveSearchTimer = null;
    input.addEventListener("input", () => {
      const q = input.value.trim();
      if (clearBtn) clearBtn.style.display = q ? "block" : "none";

      const activeTab = document.querySelector(".tab-btn.active")?.getAttribute("data-tab") || "";

      if (!q) {
        dropdown.style.display = "none";
        dropdown.innerHTML = "";
        currentResults = [];
        if (activeTab === "places") loadPlaces("");
        else if (activeTab === "trips") loadTrips("", currentTripCountry);
        return;
      }

      if (activeTab === "places") {
        clearTimeout(tabLiveSearchTimer);
        tabLiveSearchTimer = setTimeout(() => loadPlaces(q), 250);
      } else if (activeTab === "trips") {
        clearTimeout(tabLiveSearchTimer);
        tabLiveSearchTimer = setTimeout(() => loadTrips(q, currentTripCountry), 250);
      }

      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(async () => {
        try {
          const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&limit=15`);
          const data = await res.json();
          if (data.status === "SUCCESS") {
            renderSearchDropdown(data.results, q);
          }
        } catch (err) {
          console.error("Search fetch error:", err);
        }
      }, 150);
    });

    async function executeSearchNow(q) {
      if (!q) return;
      clearTimeout(debounceTimer);
      try {
        const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&limit=15`);
        const data = await res.json();
        if (data.status === "SUCCESS" && data.results && data.results.length > 0) {
          selectSearchResult(data.results[0]);
        } else {
          // Direct date parse fallback (e.g. 2015-03-28, 3/28/15)
          const dMatch = q.match(/(\d{4})[/-](\d{1,2})[/-](\d{1,2})/);
          if (dMatch) {
            const dt = `${dMatch[1]}-${dMatch[2].padStart(2, '0')}-${dMatch[3].padStart(2, '0')}`;
            currentDate = dt;
            switchTab("timeline");
            loadDay(currentDate);
          }
        }
      } catch (err) {
        console.error("Execute search error:", err);
      }
    }

    input.addEventListener("keydown", async (e) => {
      const items = dropdown.querySelectorAll(".search-result-item");

      if (e.key === "ArrowDown") {
        e.preventDefault();
        if (items.length > 0) {
          selectedIdx = (selectedIdx + 1) % items.length;
          updateSelected(items);
        }
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        if (items.length > 0) {
          selectedIdx = (selectedIdx - 1 + items.length) % items.length;
          updateSelected(items);
        }
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (selectedIdx >= 0 && selectedIdx < currentResults.length) {
          selectSearchResult(currentResults[selectedIdx]);
        } else if (currentResults.length > 0) {
          selectSearchResult(currentResults[0]);
        } else {
          await executeSearchNow(input.value.trim());
        }
      } else if (e.key === "Escape") {
        dropdown.style.display = "none";
        input.blur();
      }
    });

    clearBtn?.addEventListener("click", () => {
      input.value = "";
      clearBtn.style.display = "none";
      dropdown.style.display = "none";
      dropdown.innerHTML = "";
      input.focus();
      const activeTab = document.querySelector(".tab-btn.active")?.getAttribute("data-tab") || "";
      if (activeTab === "places") loadPlaces("");
      else if (activeTab === "trips") loadTrips("", currentTripCountry);
    });

    document.addEventListener("click", (e) => {
      if (!input.contains(e.target) && !dropdown.contains(e.target)) {
        dropdown.style.display = "none";
      }
    });

    input.addEventListener("focus", () => {
      if (input.value.trim() && dropdown.children.length > 0) {
        dropdown.style.display = "block";
      }
    });

    function updateSelected(items) {
      items.forEach((it, idx) => {
        if (idx === selectedIdx) {
          it.classList.add("selected");
          it.scrollIntoView({ block: "nearest" });
        } else {
          it.classList.remove("selected");
        }
      });
    }

    function renderSearchDropdown(results, query) {
      currentResults = results || [];
      selectedIdx = -1;

      if (!results || results.length === 0) {
        dropdown.innerHTML = `<div class="search-empty-state"><i class="fa-solid fa-magnifying-glass" style="margin-bottom:6px;font-size:16px;"></i><p>No matching places, days, or categories found for "<strong>${escapeHtml(query)}</strong>"</p></div>`;
        dropdown.style.display = "block";
        return;
      }

      dropdown.innerHTML = "";
      const dates = results.filter(r => r.type === "DATE");
      const months = results.filter(r => r.type === "MONTH");
      const photoVisits = results.filter(r => r.type === "PHOTO_VISIT");
      const places = results.filter(r => r.type === "PLACE");
      const locations = results.filter(r => r.type === "LOCATION");
      const categories = results.filter(r => r.type === "CATEGORY");

      function appendGroup(title, items, icon) {
        if (!items.length) return;
        const header = document.createElement("div");
        header.className = "search-group-header";
        header.innerHTML = `<i class="fa-solid ${icon}"></i> ${title} (${items.length})`;
        dropdown.appendChild(header);

        items.forEach(it => {
          const itemEl = document.createElement("div");
          itemEl.className = "search-result-item";
          const catIcon = getPlaceIcon(it.title, it.category) || it.icon || "fa-location-dot";
          const hasThumb = it.preview_url || it.sha256;
          const thumbHtml = hasThumb
            ? `<div class="search-item-thumb-wrapper"><img src="${it.preview_url || ('/api/photo?sha256=' + it.sha256)}" class="search-item-thumb" alt="Photo" onerror="this.parentElement.innerHTML='<div class=\\'search-item-icon\\'><i class=\\'fa-solid ${catIcon}\\'></i></div>'"></div>`
            : `<div class="search-item-icon"><i class="fa-solid ${catIcon}"></i></div>`;

          const scorePill = it.score
            ? `<span class="search-score-pill" title="Semantic Match: ${(it.score * 100).toFixed(0)}%"><i class="fa-solid fa-sparkles"></i> ${(it.score * 100).toFixed(0)}%</span>`
            : '';

          itemEl.innerHTML = `
            ${thumbHtml}
            <div class="search-item-content">
              <div class="search-item-title" style="display:flex;align-items:center;gap:6px;">
                <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(it.title)}</span>
                ${scorePill}
              </div>
              <div class="search-item-subtitle">${escapeHtml(it.subtitle)}</div>
            </div>
            <div class="search-item-meta">
              ${it.date ? `<span class="search-date-badge">${it.date}</span>` : ''}
              ${it.visit_count ? `<div style="font-size:10px;color:var(--text-dim);margin-top:2px;">${it.visit_count} visits</div>` : ''}
              ${it.photo_count ? `<div style="font-size:10px;color:var(--accent-blue);margin-top:2px;font-weight:600;"><i class="fa-solid fa-camera"></i> ${it.photo_count}</div>` : ''}
            </div>
          `;

          itemEl.addEventListener("click", () => {
            selectSearchResult(it);
          });

          dropdown.appendChild(itemEl);
        });
      }

      appendGroup("Photo Moments & Visits", photoVisits, "fa-camera-retro");
      appendGroup("Days & Dates", dates, "fa-calendar-day");
      appendGroup("Months & Years", months, "fa-calendar-days");
      appendGroup("Places & POIs", places, "fa-location-dot");
      appendGroup("Countries & Cities", locations, "fa-globe");
      appendGroup("Categories", categories, "fa-tag");

      dropdown.style.display = "block";
    }

    function selectSearchResult(it) {
      dropdown.style.display = "none";
      if (!it) return;

      if (it.type === "PHOTO_VISIT" || it.segment_id) {
        if (it.date) {
          jumpToTimelineDay(it.date, true, "search", it.segment_id);
          if (it.latitude && it.longitude && typeof map !== "undefined" && map) {
            setTimeout(() => {
              if (map && map.flyTo) {
                map.flyTo([it.latitude, it.longitude], 16.5, { duration: 0.8 });
              }
            }, 350);
          }
        }
        return;
      }

      if (it.type === "PLACE" || it.place_id) {
        switchTab("places");
        if (it.place_id) {
          openPlaceVisitsModal(it.place_id, it.title);
        } else {
          loadPlaces(it.title);
        }
        if (it.latitude && it.longitude && typeof placesMap !== "undefined" && placesMap) {
          setTimeout(() => {
            placesMap.flyTo([it.latitude, it.longitude], 16, { duration: 0.8 });
          }, 350);
        }
        return;
      }

      if (it.type === "CATEGORY") {
        switchTab("places");
        currentCategory = it.title.replace("Category: ", "").trim();
        loadPlaces();
        return;
      }

      if (it.type === "LOCATION") {
        switchTab("trips");
        loadTrips(it.title, "ALL");
        return;
      }

      const targetDate = it.date;
      if (targetDate) {
        jumpToTimelineDay(targetDate, true, "search");
        if (it.latitude && it.longitude && typeof map !== "undefined" && map) {
          setTimeout(() => {
            map.flyTo([it.latitude, it.longitude], 16, { duration: 0.8 });
          }, 350);
        }
      }
    }
  }

// ==========================================
// Photo Lightbox Viewer
// ==========================================
let currentLightboxPhotos = [];
let currentLightboxIndex = 0;

window.openPhotoLightbox = function(photoUrls, initialIdx = 0, placeTitle = "", reviewText = "") {
  if (!photoUrls || !photoUrls.length) return;
  currentLightboxPhotos = photoUrls;
  currentLightboxIndex = Math.max(0, Math.min(initialIdx, photoUrls.length - 1));

  const modal = document.getElementById("photo-lightbox-modal");
  if (!modal) return;

  modal.dataset.placeTitle = placeTitle || "Place";
  modal.dataset.reviewText = reviewText || "";

  updateLightboxView();
  modal.style.display = "flex";
  modal.classList.remove("hidden");
};

window.closePhotoLightbox = function(e) {
  if (e && e.target && e.target.closest && e.target.closest('.lightbox-content-wrapper') && !e.target.closest('.lightbox-close-btn')) {
    return;
  }
  const modal = document.getElementById("photo-lightbox-modal");
  if (modal) {
    modal.style.display = "none";
    modal.classList.add("hidden");
  }
};

window.lightboxPrev = function() {
  if (!currentLightboxPhotos.length) return;
  currentLightboxIndex = (currentLightboxIndex - 1 + currentLightboxPhotos.length) % currentLightboxPhotos.length;
  updateLightboxView();
};

window.lightboxNext = function() {
  if (!currentLightboxPhotos.length) return;
  currentLightboxIndex = (currentLightboxIndex + 1) % currentLightboxPhotos.length;
  updateLightboxView();
};

function updateLightboxView() {
  const modal = document.getElementById("photo-lightbox-modal");
  if (!modal || !currentLightboxPhotos.length) return;

  const img = document.getElementById("lightbox-img");
  const titleEl = document.getElementById("lightbox-place-title");
  const textEl = document.getElementById("lightbox-review-text");
  const counterEl = document.getElementById("lightbox-counter");
  const prevBtn = document.getElementById("lightbox-prev-btn");
  const nextBtn = document.getElementById("lightbox-next-btn");

  const url = currentLightboxPhotos[currentLightboxIndex];
  if (img) {
    img.src = window.getPhotoUrl ? window.getPhotoUrl(url, 'orig') : url;
    img.setAttribute('referrerpolicy', 'no-referrer');
  }

  if (titleEl) titleEl.textContent = modal.dataset.placeTitle || "Place";
  if (textEl) {
    const txt = modal.dataset.reviewText || "";
    textEl.textContent = txt ? `"${txt}"` : "";
    textEl.style.display = txt ? "block" : "none";
  }
  if (counterEl) {
    counterEl.textContent = `${currentLightboxIndex + 1} / ${currentLightboxPhotos.length}`;
  }

  if (prevBtn) prevBtn.style.display = currentLightboxPhotos.length > 1 ? "flex" : "none";
  if (nextBtn) nextBtn.style.display = currentLightboxPhotos.length > 1 ? "flex" : "none";
}

// Keyboard navigation for Lightbox
window.addEventListener("keydown", (e) => {
  const modal = document.getElementById("photo-lightbox-modal");
  if (!modal || modal.classList.contains("hidden")) return;

  if (e.key === "Escape") {
    window.closePhotoLightbox(null);
  } else if (e.key === "ArrowLeft") {
    window.lightboxPrev();
  } else if (e.key === "ArrowRight") {
    window.lightboxNext();
  }
});

/* ==========================================================================
   MULTI-DAY CALENDAR MATRIX VIEW ENGINE
   ========================================================================== */
let calFocusDate = null;

function getWeekDateRange(dateStr) {
  const d = new Date(dateStr + "T12:00:00Z");
  const day = d.getUTCDay(); // 0 = Sun, 1 = Mon ...
  const diffToMon = (day === 0 ? -6 : 1) - day;
  
  const monday = new Date(d);
  monday.setUTCDate(d.getUTCDate() + diffToMon);
  
  const sunday = new Date(monday);
  sunday.setUTCDate(monday.getUTCDate() + 6);
  
  return {
    startDate: monday.toISOString().slice(0, 10),
    endDate: sunday.toISOString().slice(0, 10)
  };
}

async function loadCalendarMatrix(customDate = null) {
  if (customDate) {
    calFocusDate = customDate;
  } else if (!calFocusDate) {
    calFocusDate = (typeof currentDate !== 'undefined' && currentDate) ? currentDate : getLocalToday();
  }
  
  const datePicker = document.getElementById("cal-date-picker");
  if (datePicker) datePicker.value = calFocusDate;
  
  const { startDate, endDate } = getWeekDateRange(calFocusDate);
  const rangeLabel = document.getElementById("cal-range-label");
  if (rangeLabel) {
    rangeLabel.textContent = `Week of ${startDate} to ${endDate}`;
  }
  
  // Render 24-Hour Time Axis
  const timeAxis = document.getElementById("cal-time-axis");
  if (timeAxis) {
    let axisHtml = "";
    for (let h = 0; h < 24; h++) {
      const hStr = h < 10 ? `0${h}:00` : `${h}:00`;
      axisHtml += `<div class="time-hour-label">${hStr}</div>`;
    }
    timeAxis.innerHTML = axisHtml;
  }
  
  const gridContainer = document.getElementById("cal-days-grid");
  if (gridContainer) {
    gridContainer.innerHTML = '<div class="loading-spinner" style="padding:40px;margin:auto;"><i class="fa-solid fa-circle-notch fa-spin"></i> Rendering Calendar Matrix...</div>';
  }
  
  try {
    const res = await fetch(`/api/calendar-range?start_date=${startDate}&end_date=${endDate}`);
    const data = await res.json();
    
    if (data.status !== "SUCCESS" || !data.days) {
      if (gridContainer) gridContainer.innerHTML = '<div class="empty-state">Failed to load calendar data.</div>';
      return;
    }
    
    renderCalendarGrid(data.days);
  } catch (err) {
    console.error("Error loading calendar matrix:", err);
    if (gridContainer) gridContainer.innerHTML = `<div class="empty-state">Error loading calendar matrix: ${escapeHtml(err.message)}</div>`;
  }
}

function renderCalendarGrid(daysMap) {
  const gridContainer = document.getElementById("cal-days-grid");
  if (!gridContainer) return;
  
  let gridHtml = "";
  const dates = Object.keys(daysMap).sort();
  
  for (const dStr of dates) {
    const dayData = daysMap[dStr];
    const dObj = new Date(dStr + "T12:00:00Z");
    const dow = dObj.toLocaleDateString("en-US", { weekday: "short", timeZone: "UTC" });
    const monthDay = dObj.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
    
    const anomalyCount = (dayData.anomalies || []).length;
    const gapCount = (dayData.gaps || []).length;
    
    let badgeHtml = "";
    if (anomalyCount > 0) {
      badgeHtml += `<span class="pill-badge red" style="font-size:9.5px;padding:2px 5px;" title="${anomalyCount} anomalies detected">🚨 ${anomalyCount}</span> `;
    }
    if (gapCount > 0) {
      badgeHtml += `<span class="pill-badge yellow" style="font-size:9.5px;padding:2px 5px;" title="${gapCount} unaccounted gaps">⚠️ ${gapCount} gaps</span>`;
    }
    
    gridHtml += `
      <div class="day-column" data-date="${dStr}">
        <div class="day-column-header">
          <div class="day-header-dow">${dow}</div>
          <div class="day-header-date">${monthDay}</div>
          <div style="margin-top:2px;">${badgeHtml}</div>
        </div>
        <div class="day-column-body">
    `;
    
    // 1. Render Gaps
    for (const g of (dayData.gaps || [])) {
      if (!g.start_time || !g.end_time) continue;
      const sMin = getMinutesFromTimeStr(g.start_time);
      const topPct = ((sMin / 1440.0) * 100).toFixed(2);
      const durPct = Math.max(0.6, (g.duration_minutes / 1440.0) * 100).toFixed(2);
      
      gridHtml += `
        <div class="cal-gap-block" style="top:${topPct}%;height:${durPct}%;" title="Unaccounted Gap: ${g.duration_minutes} min (${g.start_time.slice(11,16)} - ${g.end_time.slice(11,16)})">
          ${g.duration_minutes >= 30 ? `⚠️ GAP: ${g.duration_minutes}m` : (g.duration_minutes >= 15 ? `⚠️ ${g.duration_minutes}m` : '')}
        </div>
      `;
    }
    
    // 2. Render Segments
    for (const s of (dayData.segments || [])) {
      if (!s.start_time) continue;
      const sMin = getMinutesFromTimeStr(s.start_time);
      const topPct = ((sMin / 1440.0) * 100).toFixed(2);
      const durPct = Math.max(1.0, ((s.duration_minutes || 15) / 1440.0) * 100).toFixed(2);
      
      let typeClass = "poi";
      let icon = "fa-location-dot";
      let title = s.place_name || "Place Visit";
      
      if (s.segment_type === "visit") {
        if (title.toLowerCase().includes("home") || (s.category && s.category.includes("Home"))) {
          typeClass = "home";
          icon = "fa-house";
        } else if (title.toLowerCase().includes("google") || title.toLowerCase().includes("digitas") || title.toLowerCase().includes("kpmg") || title.toLowerCase().includes("school") || title.toLowerCase().includes("gymnasium") || title.toLowerCase().includes("uni")) {
          typeClass = "work";
          icon = "fa-briefcase";
        }
      } else if (s.segment_type === "activity") {
        typeClass = "activity";
        const act = s.activity_type || "TRAVEL";
        title = formatActivityName(act);
        if (act.includes("WALK") || act.includes("FOOT")) icon = "fa-person-walking";
        else if (act.includes("CYCL")) icon = "fa-bicycle";
        else if (act.includes("SUBWAY") || act.includes("METRO")) icon = "fa-train-subway";
        else if (act.includes("TRAM")) icon = "fa-train-tram";
        else if (act.includes("TRAIN")) icon = "fa-train";
        else if (act.includes("FLY")) icon = "fa-plane";
        else icon = "fa-car";
      }
      
      // Check if segment has an anomaly
      const isAnomaly = (dayData.anomalies || []).some(a => a.segment_id === s.id);
      const anomalyClass = isAnomaly ? "anomaly" : "";
      const timeStr = `${(s.start_time || "").slice(11, 16)} – ${(s.end_time || "").slice(11, 16)}`;
      const showSubtitle = (s.duration_minutes || 0) >= 35;
      
      gridHtml += `
        <div class="cal-event-block ${typeClass} ${anomalyClass}" style="top:${topPct}%;height:${durPct}%;" 
             data-seg-id="${s.id}" data-date="${dStr}"
             title="${escapeHtml(title)} (${timeStr}, ${s.duration_minutes || 0}m)">
          ${showSubtitle ? `<div class="cal-event-time">${timeStr}</div>` : ''}
          <div class="cal-event-title">
            <i class="fa-solid ${icon}"></i>
            <span>${isAnomaly ? "🚨 " : ""}${escapeHtml(title)}</span>
          </div>
        </div>
      `;
    }
    
    gridHtml += `
        </div>
      </div>
    `;
  }
  
  gridContainer.innerHTML = gridHtml;
  
  // Attach Click Listeners
  gridContainer.querySelectorAll(".cal-event-block").forEach(el => {
    el.addEventListener("click", () => {
      const segId = el.getAttribute("data-seg-id");
      const targetDate = el.getAttribute("data-date");
      if (targetDate) {
        jumpToTimelineDay(targetDate, true, "calendar");
      }
    });
  });
  
  gridContainer.querySelectorAll(".day-column-header").forEach(el => {
    el.style.cursor = "pointer";
    el.addEventListener("click", () => {
      const parentCol = el.closest(".day-column");
      const targetDate = parentCol?.getAttribute("data-date");
      if (targetDate) {
        jumpToTimelineDay(targetDate, true, "calendar");
      }
    });
  });
}

function getMinutesFromTimeStr(isoStr) {
  if (!isoStr || isoStr.length < 16) return 0;
  const h = parseInt(isoStr.slice(11, 13), 10) || 0;
  const m = parseInt(isoStr.slice(14, 16), 10) || 0;
  return h * 60 + m;
}

function formatActivityName(actType) {
  if (!actType) return "Travel";
  return actType.replace("IN_", "").replace("_", " ").toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}

// Setup Calendar UI Controls
function initCalendarMatrixEvents() {
  const prevBtn = document.getElementById("btn-cal-prev-week");
  const nextBtn = document.getElementById("btn-cal-next-week");
  const datePicker = document.getElementById("cal-date-picker");
  
  if (prevBtn) {
    prevBtn.addEventListener("click", () => {
      const d = new Date(calFocusDate + "T12:00:00Z");
      d.setUTCDate(d.getUTCDate() - 7);
      calFocusDate = d.toISOString().slice(0, 10);
      loadCalendarMatrix();
    });
  }
  
  if (nextBtn) {
    nextBtn.addEventListener("click", () => {
      const d = new Date(calFocusDate + "T12:00:00Z");
      d.setUTCDate(d.getUTCDate() + 7);
      calFocusDate = d.toISOString().slice(0, 10);
      loadCalendarMatrix();
    });
  }
  
  if (datePicker) {
    datePicker.addEventListener("change", (e) => {
      if (e.target.value) {
        calFocusDate = e.target.value;
        loadCalendarMatrix();
      }
    });
  }
  
  document.querySelectorAll(".cal-jump-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".cal-jump-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      if (btn.id === "cal-jump-today-btn") {
        calFocusDate = getLocalToday();
        loadCalendarMatrix(calFocusDate);
        return;
      }
      const targetDate = btn.getAttribute("data-date");
      if (targetDate) {
        calFocusDate = targetDate;
        loadCalendarMatrix(calFocusDate);
      }
    });
  });
}

  // Initialize calendar event listeners on page load
  initCalendarMatrixEvents();
  window.loadCalendarMatrix = loadCalendarMatrix;
  window.renderCalendarGrid = renderCalendarGrid;

  // Boot Application
  initMaps();
  setupTabs();
  setupEvents();
  initGlobalSearch();

  const initialParams = new URLSearchParams(window.location.search);
  const initialTab = initialParams.get("tab") || "timeline";
  const initialDate = initialParams.get("date") || currentDate;
  currentDate = initialDate;

  // Replace initial history state so browser Back/Forward operates smoothly
  const initialSearch = window.location.search || `?tab=${initialTab}&date=${initialDate}`;
  window.history.replaceState({ tab: initialTab, date: initialDate }, "", initialSearch);

  switchTab(initialTab, false);
  loadDay(initialDate, false);

  // Defer non-critical background statistics to idle
  setTimeout(() => {
    loadOverview();
  }, 150);
});
