import { fetchSlotJson, postJson } from "./api.js";
import { escapeHtml, loadExternalScriptOnce } from "./dom.js";
import { appNav, registerCacheInvalidator, safeStorage, state } from "./state.js";
import { format24hTime, formatActivityName } from "./time.js";

export const MAP_STYLES = {
  google_roads: {
    url: "https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}",
    options: { maxZoom: 20, attribution: "&copy; Google Maps" },
  },
  google_terrain: {
    url: "https://mt1.google.com/vt/lyrs=p&x={x}&y={y}&z={z}",
    options: { maxZoom: 20, attribution: "&copy; Google Maps" },
  },
  google_hybrid: {
    url: "https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
    options: { maxZoom: 20, attribution: "&copy; Google Maps" },
  },
  google_satellite: {
    url: "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
    options: { maxZoom: 20, attribution: "&copy; Google Maps" },
  },
  esri_street: {
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
    options: { maxZoom: 19, attribution: "Tiles &copy; Esri" },
  },
  osm: {
    url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    options: { maxZoom: 19, attribution: "&copy; OpenStreetMap contributors" },
  },
};

export const ACTIVITY_COLORS = {
  WALKING: "#10b981",
  ON_FOOT: "#10b981",
  RUNNING: "#059669",
  HIKING: "#047857",
  CYCLING: "#f59e0b",
  ON_BICYCLE: "#f59e0b",
  IN_PASSENGER_VEHICLE: "#2563eb",
  DRIVING: "#2563eb",
  IN_TAXI: "#eab308",
  MOTORCYCLING: "#ea580c",
  IN_BUS: "#0284c7",
  IN_SUBWAY: "#7c3aed",
  IN_TRAIN: "#6366f1",
  IN_TRAM: "#8b5cf6",
  IN_FERRY: "#0891b2",
  BOATING: "#0891b2",
  SAILING: "#0e7490",
  KAYAKING: "#06b6d4",
  FLYING: "#ec4899",
  SKIING: "#3b82f6",
  SNOWBOARDING: "#60a5fa",
  UNKNOWN_ACTIVITY_TYPE: "#64748b",
};

export const ACTIVITY_ICONS = {
  WALKING: "fa-person-walking",
  ON_FOOT: "fa-person-walking",
  RUNNING: "fa-person-running",
  HIKING: "fa-person-hiking",
  CYCLING: "fa-bicycle",
  ON_BICYCLE: "fa-bicycle",
  IN_PASSENGER_VEHICLE: "fa-car",
  DRIVING: "fa-car",
  IN_TAXI: "fa-taxi",
  MOTORCYCLING: "fa-motorcycle",
  IN_BUS: "fa-bus",
  IN_SUBWAY: "fa-train-subway",
  IN_TRAIN: "fa-train",
  IN_TRAM: "fa-train-tram",
  IN_FERRY: "fa-ferry",
  BOATING: "fa-ship",
  SAILING: "fa-sailboat",
  KAYAKING: "fa-water",
  FLYING: "fa-plane",
  SKIING: "fa-person-skiing",
  SNOWBOARDING: "fa-person-snowboarding",
  UNKNOWN_ACTIVITY_TYPE: "fa-route",
};

export const CATEGORY_ICONS = {
  "Food & Drink": "fa-utensils",
  "Shopping & Retail": "fa-bag-shopping",
  Shopping: "fa-bag-shopping",
  "Travel & Transit": "fa-plane-departure",
  "Arts & Entertainment": "fa-masks-theater",
  "Parks & Outdoors": "fa-tree",
  "Outdoors & Nature": "fa-tree",
  "Health & Wellness": "fa-heart-pulse",
  "Work & Education": "fa-briefcase",
  "Work & Office": "fa-briefcase",
  Education: "fa-graduation-cap",
  "Home & Residence": "fa-house",
  "Nightlife & Bars": "fa-martini-glass-citrus",
  "Cafe & Bakery": "fa-mug-hot",
  "Lodging & Hotels": "fa-bed",
  "Services & Civic": "fa-building-columns",
};

export const CATEGORY_MAP_COLORS = {
  "Food & Drink": "#ef4444",
  "Cafe & Bakery": "#d97706",
  "Nightlife & Bars": "#a855f7",
  "Shopping & Retail": "#ec4899",
  Shopping: "#ec4899",
  "Travel & Transit": "#2563eb",
  "Lodging & Hotels": "#0891b2",
  "Arts & Entertainment": "#8b5cf6",
  "Parks & Outdoors": "#16a34a",
  "Outdoors & Nature": "#16a34a",
  "Health & Wellness": "#e11d48",
  "Work & Education": "#4f46e5",
  "Work & Office": "#4f46e5",
  Education: "#6366f1",
  "Home & Residence": "#0d9488",
  "Services & Civic": "#64748b",
};

export function getPlaceIcon(name = "", category = "") {
  if (category && CATEGORY_ICONS[category]) {
    return CATEGORY_ICONS[category];
  }
  const combined = `${String(name || "").toLowerCase()} ${String(category || "").toLowerCase()}`;

  if (/\b(airport|terminal|airlines|jfk|lga|ewr|sfo|lax|zrh)\b/.test(combined)) return "fa-plane-departure";
  if (/\b(station|subway|train|transit|dock|citi bike|citibike|ferry|pier)\b/.test(combined)) return "fa-train-subway";
  if (/\b(coffee|cafe|espresso|bakery|roasters|bagel)\b/.test(combined)) return "fa-mug-hot";
  if (/\b(bar|pub|brewery|tavern|lounge|cocktail|wine)\b/.test(combined)) return "fa-martini-glass-citrus";
  if (/\b(restaurant|bistro|pizza|sushi|taco|diner|grill|kitchen|ramen|thai|food)\b/.test(combined)) return "fa-utensils";
  if (/\b(hotel|inn|resort|hostel|motel|lodging)\b/.test(combined)) return "fa-bed";
  if (/\b(park|trail|beach|garden|woods|mountain|lake|island|plaza|square)\b/.test(combined)) return "fa-tree";
  if (/\b(museum|gallery|theater|cinema|concert|arena|stadium|arts|club)\b/.test(combined)) return "fa-masks-theater";
  if (/\b(market|grocery|shop|store|mall|pharmacy|book)\b/.test(combined)) return "fa-bag-shopping";
  if (/\b(gym|fitness|hospital|clinic|doctor|dental|spa)\b/.test(combined)) return "fa-heart-pulse";
  if (/\b(home|residence|apartment)\b/.test(combined)) return "fa-house";
  if (/\b(office|work|university|college|school|campus|lab)\b/.test(combined)) return "fa-briefcase";
  return "fa-location-dot";
}

let dayMap = null;
let dayLayerGroup = null;
let placesMap = null;
let placesLayerGroup = null;
let placesCanvasRenderer = null;
let heatmapInstance = null;
let heatLayer = null;
let heatmapLoaded = false;

const activeTileLayers = new Map();
const auxiliaryMaps = new Map();
const segmentMarkersById = new Map();

let scrubberTrackPoints = [];
let scrubberBeaconMarker = null;

registerCacheInvalidator(() => {
  heatmapLoaded = false;
});

export function getDayMap() {
  return dayMap;
}

export function getPlacesMap() {
  return placesMap;
}

export function registerAuxiliaryMap(containerId, mapInstance) {
  if (!containerId || !mapInstance) return;
  auxiliaryMaps.set(containerId, mapInstance);
  applyBaseTileLayerToMap(mapInstance, containerId, state.currentMapStyle);
}

export function unregisterAuxiliaryMap(containerId) {
  activeTileLayers.delete(containerId);
  auxiliaryMaps.delete(containerId);
}

export function applyBaseTileLayerToMap(targetMap, containerId, styleKey) {
  if (!targetMap || typeof L === "undefined") return;
  const resolvedKey = MAP_STYLES[styleKey] ? styleKey : "google_roads";
  const cfg = MAP_STYLES[resolvedKey];

  const existing = activeTileLayers.get(containerId);
  if (existing && targetMap.hasLayer(existing)) {
    targetMap.removeLayer(existing);
  }

  const nextLayer = L.tileLayer(cfg.url, cfg.options);
  nextLayer.addTo(targetMap);
  if (typeof nextLayer.bringToBack === "function") {
    nextLayer.bringToBack();
  }
  activeTileLayers.set(containerId, nextLayer);
}

export function setGlobalMapStyle(styleKey) {
  const resolved = MAP_STYLES[styleKey] ? styleKey : "google_roads";
  state.currentMapStyle = resolved;
  safeStorage.setItem("mapStyle", resolved);

  document.querySelectorAll(".map-style-select").forEach((sel) => {
    if (sel.value !== resolved) sel.value = resolved;
  });

  if (dayMap) applyBaseTileLayerToMap(dayMap, "map", resolved);
  if (placesMap) applyBaseTileLayerToMap(placesMap, "places-map", resolved);
  if (heatmapInstance) applyBaseTileLayerToMap(heatmapInstance, "heatmap-map", resolved);
  for (const [cid, auxMap] of auxiliaryMaps.entries()) {
    applyBaseTileLayerToMap(auxMap, cid, resolved);
  }
}

export function initMaps() {
  if (typeof L === "undefined") return;

  if (L.Icon && L.Icon.Default) {
    L.Icon.Default.imagePath = "/vendor/leaflet/images/";
  }

  const dayEl = document.getElementById("map");
  if (dayEl && !dayMap) {
    dayMap = L.map("map", {
      zoomControl: true,
      preferCanvas: true,
    }).setView([40.728, -73.995], 12);
    applyBaseTileLayerToMap(dayMap, "map", state.currentMapStyle);
    dayLayerGroup = L.layerGroup().addTo(dayMap);

    dayEl.addEventListener("click", async (e) => {
      const toggleBtn = e.target.closest("[data-breadcrumb-toggle-id]");
      if (!toggleBtn) return;
      e.preventDefault();
      const bcId = Number(toggleBtn.getAttribute("data-breadcrumb-toggle-id"));
      if (!bcId) return;
      toggleBtn.disabled = true;
      try {
        await postJson("/api/breadcrumbs/toggle-exclude", { id: bcId });
        await appNav.loadDay(state.currentDate, false);
      } catch (err) {
        console.error("Failed toggling breadcrumb exclusion:", err);
      } finally {
        toggleBtn.disabled = false;
      }
    });
  }

  const placesEl = document.getElementById("places-map");
  if (placesEl && !placesMap) {
    placesCanvasRenderer = L.canvas({ padding: 0.5 });
    placesMap = L.map("places-map", {
      zoomControl: true,
      preferCanvas: true,
      renderer: placesCanvasRenderer,
    }).setView([30.0, -20.0], 2);
    applyBaseTileLayerToMap(placesMap, "places-map", state.currentMapStyle);
    placesLayerGroup = L.layerGroup().addTo(placesMap);

    placesEl.addEventListener("click", (e) => {
      const visitsBtn = e.target.closest("[data-open-place-visits-id]");
      if (visitsBtn) {
        e.preventDefault();
        const pid = visitsBtn.getAttribute("data-open-place-visits-id");
        const pname = visitsBtn.getAttribute("data-open-place-visits-name") || "Place";
        if (pid) appNav.openPlaceVisitsModal(pid, pname);
        return;
      }
      const jumpBtn = e.target.closest("[data-jump-timeline-date]");
      if (jumpBtn) {
        e.preventDefault();
        const dt = jumpBtn.getAttribute("data-jump-timeline-date");
        if (dt) appNav.jumpToTimelineDay(dt, true, "places");
      }
    });
  }

  const heatEl = document.getElementById("heatmap-map");
  if (heatEl && !heatmapInstance) {
    heatmapInstance = L.map("heatmap-map", {
      zoomControl: true,
      preferCanvas: true,
    }).setView([35.0, -35.0], 3);
    applyBaseTileLayerToMap(heatmapInstance, "heatmap-map", state.currentMapStyle);
  }

  document.querySelectorAll(".map-style-select").forEach((sel) => {
    const validKey = MAP_STYLES[state.currentMapStyle] ? state.currentMapStyle : "google_roads";
    sel.value = validKey;
    sel.addEventListener("change", (e) => {
      setGlobalMapStyle(e.target.value);
    });
  });

  document.getElementById("btn-places-map-reset")?.addEventListener("click", () => {
    placesMap?.setView([25.0, -10.0], 2);
  });
  document.getElementById("btn-places-map-nyc")?.addEventListener("click", () => {
    placesMap?.setView([40.73, -73.99], 12);
  });
  document.getElementById("btn-places-map-ch")?.addEventListener("click", () => {
    placesMap?.setView([46.82, 8.23], 8);
  });
  document.getElementById("btn-places-map-ca")?.addEventListener("click", () => {
    placesMap?.setView([37.77, -122.42], 9);
  });
  document.getElementById("btn-toggle-places-map")?.addEventListener("click", () => {
    const sec = document.getElementById("places-map-section");
    if (!sec) return;
    const isHidden = sec.hidden || sec.style.display === "none";
    sec.hidden = !isHidden;
    sec.style.display = isHidden ? "" : "none";
    if (isHidden && placesMap) {
      setTimeout(() => placesMap.invalidateSize(true), 60);
    }
  });
}

export function invalidateActiveTabMap(tabName) {
  setTimeout(() => {
    try {
      if (tabName === "timeline" && dayMap) dayMap.invalidateSize(true);
      else if (tabName === "places" && placesMap) placesMap.invalidateSize(true);
      else if (tabName === "heatmap" && heatmapInstance) heatmapInstance.invalidateSize(true);
    } catch (err) {
      console.warn("Map resize warning:", err);
    }
  }, 60);
}

function buildGreatCircleArc(lat1, lng1, lat2, lng2, steps = 48) {
  const toRad = (deg) => (deg * Math.PI) / 180;
  const toDeg = (rad) => (rad * 180) / Math.PI;
  const phi1 = toRad(lat1);
  const lam1 = toRad(lng1);
  const phi2 = toRad(lat2);
  const lam2 = toRad(lng2);

  const d =
    2 *
    Math.asin(
      Math.min(
        1,
        Math.sqrt(
          Math.sin((phi2 - phi1) / 2) ** 2 +
            Math.cos(phi1) * Math.cos(phi2) * Math.sin((lam2 - lam1) / 2) ** 2
        )
      )
    );
  if (!Number.isFinite(d) || d < 1e-5) {
    return [
      [lat1, lng1],
      [lat2, lng2],
    ];
  }

  const pts = [];
  for (let i = 0; i <= steps; i++) {
    const f = i / steps;
    const A = Math.sin((1 - f) * d) / Math.sin(d);
    const B = Math.sin(f * d) / Math.sin(d);
    const x = A * Math.cos(phi1) * Math.cos(lam1) + B * Math.cos(phi2) * Math.cos(lam2);
    const y = A * Math.cos(phi1) * Math.sin(lam1) + B * Math.cos(phi2) * Math.sin(lam2);
    const z = A * Math.sin(phi1) + B * Math.sin(phi2);
    const lat = toDeg(Math.atan2(z, Math.sqrt(x * x + y * y)));
    const lng = toDeg(Math.atan2(y, x));
    pts.push([lat, lng]);
  }
  return pts;
}

function parsePolylineCoords(rawPoly) {
  if (!rawPoly) return [];
  let arr = rawPoly;
  if (typeof rawPoly === "string") {
    try {
      arr = JSON.parse(rawPoly);
    } catch {
      return [];
    }
  }
  if (!Array.isArray(arr)) return [];
  const coords = [];
  for (const item of arr) {
    if (Array.isArray(item) && item.length >= 2) {
      const lat = Number(item[0]);
      const lng = Number(item[1]);
      if (Number.isFinite(lat) && Number.isFinite(lng)) coords.push([lat, lng]);
    } else if (item && typeof item === "object") {
      const lat = Number(item.lat ?? item.latitude);
      const lng = Number(item.lng ?? item.lon ?? item.longitude);
      if (Number.isFinite(lat) && Number.isFinite(lng)) coords.push([lat, lng]);
    }
  }
  return coords;
}

export function renderDayMap(dayData) {
  if (!dayMap || !dayLayerGroup || typeof L === "undefined") return;

  dayLayerGroup.clearLayers();
  segmentMarkersById.clear();
  scrubberTrackPoints = [];
  if (scrubberBeaconMarker && dayMap.hasLayer(scrubberBeaconMarker)) {
    dayMap.removeLayer(scrubberBeaconMarker);
  }
  scrubberBeaconMarker = null;

  const boundsPts = [];
  const segments = dayData?.segments || [];

  if (state.showRawSignals && Array.isArray(dayData?.breadcrumbs)) {
    for (const bc of dayData.breadcrumbs) {
      const lat = Number(bc.latitude ?? bc.lat);
      const lng = Number(bc.longitude ?? bc.lng);
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) continue;
      const isExcluded = Boolean(bc.is_excluded || bc.is_outlier);
      const marker = L.circleMarker([lat, lng], {
        radius: isExcluded ? 4 : 3.5,
        color: isExcluded ? "#b91c1c" : "#0284c7",
        fillColor: isExcluded ? "#ef4444" : "#38bdf8",
        fillOpacity: isExcluded ? 0.45 : 0.8,
        weight: 1,
      });
      const tsStr = escapeHtml(format24hTime(bc.timestamp || ""));
      const accStr = bc.accuracy_meters ? `${Math.round(bc.accuracy_meters)}m` : "n/a";
      const srcStr = escapeHtml(bc.source || "GPS");
      const btnLabel = isExcluded ? "Restore Signal" : "Exclude Outlier";
      marker.bindPopup(`
        <div style="font-size:12px;color:#0f172a;min-width:170px;">
          <div style="font-weight:700;margin-bottom:3px;">Raw Signal · ${tsStr}</div>
          <div style="color:#475569;font-size:11px;">Source: ${srcStr} · Acc: ${accStr}</div>
          ${
            bc.id
              ? `<button type="button" data-breadcrumb-toggle-id="${Number(bc.id)}" style="margin-top:6px;padding:4px 8px;border-radius:4px;border:1px solid #cbd5e1;background:#f8fafc;color:#0f172a;font-size:11px;cursor:pointer;font-weight:600;">${btnLabel}</button>`
              : ""
          }
        </div>
      `);
      marker.addTo(dayLayerGroup);
      if (!isExcluded) boundsPts.push([lat, lng]);
    }
  }

  let visitIndex = 0;

  for (const s of segments) {
    const tStart = s.start_time ? Date.parse(s.start_time) / 1000.0 : null;
    const tEnd = s.end_time ? Date.parse(s.end_time) / 1000.0 : null;

    if (s.segment_type === "activity") {
      const actType = s.activity_type || "UNKNOWN_ACTIVITY_TYPE";
      const strokeColor = ACTIVITY_COLORS[actType] || "#2563eb";
      let polyCoords = parsePolylineCoords(s.polyline_json);

      if (polyCoords.length < 2) {
        const sLat = Number(s.start_lat ?? s.latitude);
        const sLng = Number(s.start_lng ?? s.longitude);
        const eLat = Number(s.end_lat);
        const eLng = Number(s.end_lng);
        if (Number.isFinite(sLat) && Number.isFinite(sLng) && Number.isFinite(eLat) && Number.isFinite(eLng)) {
          if (actType === "FLYING") {
            polyCoords = buildGreatCircleArc(sLat, sLng, eLat, eLng, 48);
          } else {
            polyCoords = [
              [sLat, sLng],
              [eLat, eLng],
            ];
          }
        }
      } else if (actType === "FLYING" && polyCoords.length === 2) {
        polyCoords = buildGreatCircleArc(
          polyCoords[0][0],
          polyCoords[0][1],
          polyCoords[1][0],
          polyCoords[1][1],
          48
        );
      }

      if (polyCoords.length >= 2) {
        const isDashed = actType === "FLYING" || (!s.has_snapped_path && polyCoords.length <= 2);
        const casing = L.polyline(polyCoords, {
          color: "#ffffff",
          weight: 6.5,
          opacity: 0.82,
          interactive: false,
        });
        const line = L.polyline(polyCoords, {
          color: strokeColor,
          weight: 4,
          opacity: 0.94,
          dashArray: isDashed ? "7, 7" : null,
        });

        const distKm = s.distance_meters ? `${(s.distance_meters / 1000).toFixed(1)} km` : "";
        const durMin = s.duration_minutes ? `${Math.round(s.duration_minutes)} min` : "";
        line.bindPopup(`
          <div style="font-size:12.5px;color:#0f172a;min-width:180px;">
            <div style="font-weight:700;color:${strokeColor};margin-bottom:2px;">${escapeHtml(formatActivityName(actType))}</div>
            <div style="font-size:11.5px;color:#334155;">${escapeHtml(format24hTime(s.start_time))} – ${escapeHtml(format24hTime(s.end_time))}</div>
            <div style="font-size:11px;color:#475569;margin-top:2px;">${escapeHtml([distKm, durMin].filter(Boolean).join(" · "))}</div>
          </div>
        `);

        casing.addTo(dayLayerGroup);
        line.addTo(dayLayerGroup);
        segmentMarkersById.set(Number(s.id), line);

        for (let i = 0; i < polyCoords.length; i++) {
          boundsPts.push(polyCoords[i]);
          if (tStart && tEnd && polyCoords.length > 1) {
            const frac = i / (polyCoords.length - 1);
            scrubberTrackPoints.push({
              ts: tStart + frac * (tEnd - tStart),
              lat: polyCoords[i][0],
              lng: polyCoords[i][1],
            });
          }
        }
      }
    } else if (s.segment_type === "visit") {
      const lat = Number(s.latitude ?? s.start_lat);
      const lng = Number(s.longitude ?? s.start_lng);
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) continue;

      visitIndex += 1;
      const placeName = s.place_name || "Place Visit";
      const iconCls = getPlaceIcon(placeName, s.category);
      const pinColor = CATEGORY_MAP_COLORS[s.category] || "#1a73e8";

      const divIcon = L.divIcon({
        className: "timeline-visit-map-pin",
        html: `<div style="width:28px;height:28px;border-radius:50%;background:${pinColor};color:#ffffff;border:2.5px solid #ffffff;box-shadow:0 2px 6px rgba(15,23,42,0.35);display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;" title="${escapeHtml(placeName)}"><i class="fa-solid ${iconCls}"></i></div>`,
        iconSize: [28, 28],
        iconAnchor: [14, 14],
        popupAnchor: [0, -14],
      });

      const marker = L.marker([lat, lng], { icon: divIcon });
      const addrHtml = s.address
        ? `<div style="font-size:11px;color:#475569;margin-top:2px;">${escapeHtml(s.address)}</div>`
        : "";
      const catBadge = s.category
        ? `<div style="display:inline-block;margin-top:4px;padding:2px 6px;border-radius:4px;background:#eff6ff;color:#1d4ed8;font-size:10.5px;font-weight:600;">${escapeHtml(s.category)}</div>`
        : "";

      marker.bindPopup(`
        <div style="font-size:12.5px;color:#0f172a;min-width:190px;max-width:260px;">
          <div style="font-weight:700;color:#0f172a;">#${visitIndex} · ${escapeHtml(placeName)}</div>
          <div style="font-size:11.5px;color:#334155;margin-top:2px;">${escapeHtml(format24hTime(s.start_time))} – ${escapeHtml(format24hTime(s.end_time))}${s.duration_minutes ? ` (${Math.round(s.duration_minutes)}m)` : ""}</div>
          ${addrHtml}
          ${catBadge}
        </div>
      `);

      marker.addTo(dayLayerGroup);
      segmentMarkersById.set(Number(s.id), marker);
      boundsPts.push([lat, lng]);

      if (tStart) scrubberTrackPoints.push({ ts: tStart, lat, lng });
      if (tEnd) scrubberTrackPoints.push({ ts: tEnd, lat, lng });
    }
  }

  for (const g of dayData?.gaps || []) {
    const lat1 = Number(g.prev_lat);
    const lng1 = Number(g.prev_lng);
    const lat2 = Number(g.next_lat);
    const lng2 = Number(g.next_lng);
    if (Number.isFinite(lat1) && Number.isFinite(lng1) && Number.isFinite(lat2) && Number.isFinite(lng2)) {
      const gapLine = L.polyline(
        [
          [lat1, lng1],
          [lat2, lng2],
        ],
        {
          color: "#dc2626",
          weight: 2.5,
          opacity: 0.75,
          dashArray: "4, 8",
        }
      );
      gapLine.bindPopup(`
        <div style="font-size:12px;color:#0f172a;min-width:180px;">
          <div style="font-weight:700;color:#b91c1c;">Unrecorded Gap (${Math.round(g.duration_minutes || 0)} min)</div>
          <div style="font-size:11px;color:#334155;margin-top:2px;">${escapeHtml(format24hTime(g.start_time))} – ${escapeHtml(format24hTime(g.end_time))}</div>
          <div style="font-size:11px;color:#475569;margin-top:2px;">${escapeHtml(g.prev_place_name || "Origin")} → ${escapeHtml(g.next_place_name || "Destination")}</div>
        </div>
      `);
      gapLine.addTo(dayLayerGroup);
    }
  }

  scrubberTrackPoints.sort((a, b) => a.ts - b.ts);

  if (boundsPts.length === 1) {
    dayMap.setView(boundsPts[0], 15);
  } else if (boundsPts.length > 1) {
    dayMap.fitBounds(boundsPts, { padding: [36, 36], maxZoom: 16 });
  }
}

export function focusSegmentOnDayMap(segId) {
  if (!dayMap) return;
  const layer = segmentMarkersById.get(Number(segId));
  if (!layer) return;
  if (typeof layer.getLatLng === "function") {
    dayMap.panTo(layer.getLatLng(), { animate: true });
    layer.openPopup();
  } else if (typeof layer.getBounds === "function") {
    dayMap.fitBounds(layer.getBounds(), { padding: [48, 48], maxZoom: 16 });
    layer.openPopup();
  }
}

export function panDayMapTo(lat, lng, zoom = 16) {
  if (!dayMap || !Number.isFinite(lat) || !Number.isFinite(lng)) return;
  setTimeout(() => {
    try {
      dayMap.invalidateSize(true);
      const size = dayMap.getSize();
      if (size && size.x > 0 && size.y > 0) {
        dayMap.setView([lat, lng], zoom);
      }
    } catch (err) {
      console.warn("Map pan warning:", err);
    }
  }, 180);
}

export function panPlacesMapTo(lat, lng, zoom = 16) {
  if (!placesMap || !Number.isFinite(lat) || !Number.isFinite(lng)) return;
  setTimeout(() => {
    try {
      placesMap.invalidateSize(true);
      const size = placesMap.getSize();
      if (size && size.x > 0 && size.y > 0) {
        placesMap.setView([lat, lng], zoom);
      }
    } catch (err) {
      console.warn("PlacesMap pan warning:", err);
    }
  }, 180);
}

export function updateScrubberBeacon(epochSec) {
  if (!dayMap || !scrubberTrackPoints.length || typeof L === "undefined") return;

  let chosen = scrubberTrackPoints[0];
  for (let i = 0; i < scrubberTrackPoints.length; i++) {
    const pt = scrubberTrackPoints[i];
    if (pt.ts <= epochSec) {
      chosen = pt;
      const next = scrubberTrackPoints[i + 1];
      if (next && next.ts > epochSec && next.ts > pt.ts) {
        const frac = (epochSec - pt.ts) / (next.ts - pt.ts);
        chosen = {
          ts: epochSec,
          lat: pt.lat + frac * (next.lat - pt.lat),
          lng: pt.lng + frac * (next.lng - pt.lng),
        };
        break;
      }
    } else {
      break;
    }
  }

  if (!scrubberBeaconMarker) {
    const icon = L.divIcon({
      className: "scrubber-live-beacon",
      html: `<div style="width:16px;height:16px;border-radius:50%;background:#2563eb;border:3px solid #ffffff;box-shadow:0 0 0 4px rgba(37,99,235,0.28),0 2px 6px rgba(0,0,0,0.35);"></div>`,
      iconSize: [16, 16],
      iconAnchor: [8, 8],
    });
    scrubberBeaconMarker = L.marker([chosen.lat, chosen.lng], {
      icon,
      zIndexOffset: 1000,
    }).addTo(dayMap);
  } else {
    scrubberBeaconMarker.setLatLng([chosen.lat, chosen.lng]);
  }
}

export async function loadAllPlacesMap(query = "") {
  if (!placesMap || !placesLayerGroup || typeof L === "undefined") return;

  const countBadge = document.getElementById("places-map-count-label");
  if (countBadge) countBadge.textContent = "Loading map points...";

  const params = new URLSearchParams();
  if (query) params.set("q", query);
  if (state.currentCategory && state.currentCategory !== "ALL") params.set("category", state.currentCategory);
  if (state.currentCity && state.currentCity !== "ALL") params.set("city", state.currentCity);
  if (state.currentEra && state.currentEra !== "ALL") params.set("era", state.currentEra);
  if (state.currentCadence && state.currentCadence !== "ALL") params.set("cadence", state.currentCadence);
  if (state.currentDwell && state.currentDwell !== "ALL") params.set("dwell", state.currentDwell);
  if (state.reviewedOnly) params.set("reviewed_only", "true");

  try {
    const { aborted, data } = await fetchSlotJson("places-map", `/api/places/map-points?${params.toString()}`);
    if (aborted || !data || data.status !== "SUCCESS") return;

    const points = data.points || [];
    placesLayerGroup.clearLayers();
    placesMap.invalidateSize(true);

    if (countBadge) {
      countBadge.textContent = `${points.length.toLocaleString()} places plotted`;
    }

    const bounds = [];
    for (const p of points) {
      const lat = Number(p.latitude);
      const lng = Number(p.longitude);
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) continue;

      const color = CATEGORY_MAP_COLORS[p.category] || "#2563eb";
      const visits = Number(p.visit_count) || 1;
      const radius = Math.min(11, Math.max(4.5, 3.8 + Math.log2(visits + 1) * 1.4));

      const marker = L.circleMarker([lat, lng], {
        renderer: placesCanvasRenderer,
        radius,
        color: "#ffffff",
        weight: 1.2,
        fillColor: color,
        fillOpacity: 0.86,
      });

      const lastVisitDate = p.last_visited ? String(p.last_visited).slice(0, 10) : "";
      marker.bindPopup(`
        <div style="font-size:12.5px;color:#0f172a;min-width:200px;max-width:260px;">
          <div style="font-weight:700;color:#0f172a;">${escapeHtml(p.name || "Place")}</div>
          ${p.address ? `<div style="font-size:11px;color:#475569;margin-top:2px;">${escapeHtml(p.address)}</div>` : ""}
          <div style="display:flex;align-items:center;gap:6px;margin-top:5px;font-size:11px;color:#334155;">
            <span style="padding:1px 6px;border-radius:4px;background:${color}1f;color:${color};font-weight:700;">${escapeHtml(p.category || "Place")}</span>
            <strong>${visits} visit${visits === 1 ? "" : "s"}</strong>
          </div>
          <div style="display:flex;gap:6px;margin-top:8px;">
            <button type="button" data-open-place-visits-id="${escapeHtml(p.place_id)}" data-open-place-visits-name="${escapeHtml(p.name || "Place")}" style="flex:1;padding:5px 8px;border-radius:5px;border:1px solid #cbd5e1;background:#f8fafc;color:#0f172a;font-size:11px;font-weight:600;cursor:pointer;">All ${visits} Visits</button>
            ${
              lastVisitDate
                ? `<button type="button" data-jump-timeline-date="${escapeHtml(lastVisitDate)}" style="padding:5px 8px;border-radius:5px;border:none;background:#1a73e8;color:#ffffff;font-size:11px;font-weight:600;cursor:pointer;">Last Day</button>`
                : ""
            }
          </div>
        </div>
      `);

      marker.addTo(placesLayerGroup);
      bounds.push([lat, lng]);
    }

    if (bounds.length === 1) {
      placesMap.setView(bounds[0], 15);
    } else if (bounds.length > 1) {
      placesMap.fitBounds(bounds, { padding: [30, 30], maxZoom: 15 });
    }
  } catch (err) {
    console.error("Error loading all places map:", err);
    if (countBadge) countBadge.textContent = "Failed to load map points";
  }
}

export async function loadWorldHeatmap(forceReload = false) {
  if (!heatmapInstance || typeof L === "undefined") return;
  heatmapInstance.invalidateSize(true);
  if (heatmapLoaded && !forceReload) return;

  try {
    if (typeof L.heatLayer !== "function") {
      await loadExternalScriptOnce("/vendor/leaflet-heat/leaflet-heat.js");
    }
    const { aborted, data } = await fetchSlotJson("heatmap", "/api/heatmap");
    if (aborted || !data || data.status !== "SUCCESS") return;

    const pts = (data.points || [])
      .map((pt) => {
        if (Array.isArray(pt)) return [Number(pt[0]), Number(pt[1]), Number(pt[2] ?? 0.6)];
        return [Number(pt.latitude ?? pt.lat), Number(pt.longitude ?? pt.lng), Number(pt.weight ?? 0.6)];
      })
      .filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]));

    if (heatLayer && heatmapInstance.hasLayer(heatLayer)) {
      heatmapInstance.removeLayer(heatLayer);
    }

    if (typeof L.heatLayer === "function" && pts.length > 0) {
      heatLayer = L.heatLayer(pts, {
        radius: 16,
        blur: 18,
        maxZoom: 13,
      }).addTo(heatmapInstance);
    }
    heatmapLoaded = true;
  } catch (err) {
    console.error("Error loading world heatmap:", err);
  }
}
