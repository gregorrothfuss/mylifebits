import { fetchSlotJson } from "./api.js";
import {
  closeDialog,
  loadExternalScriptOnce,
  loadStylesheetOnce,
  openDialog,
  setElText,
} from "./dom.js";
import { state } from "./state.js";

let earthMap = null;
let earthTrajectory = [];
let earthCurrentIdx = 0;
let earthTotalDistanceMeters = 0;
let isRiding = false;
let earthAnimationId = null;
let earthRiderMarker = null;

function disposeEarthMap() {
  isRiding = false;
  if (earthAnimationId) {
    cancelAnimationFrame(earthAnimationId);
    earthAnimationId = null;
  }
  earthRiderMarker = null;
  if (earthMap) {
    try {
      earthMap.remove();
    } catch (err) {
      console.warn("MapLibre disposal warning:", err);
    }
    earthMap = null;
  }
}

export function close3DModal() {
  disposeEarthMap();
  const modal = document.getElementById("flythrough-modal");
  closeDialog(modal);
}

export async function openFlythroughPlayer(tripId, tripTitle) {
  return openEarthRidePlayer(tripId, true, tripTitle);
}

export async function openEarthRidePlayer(targetId, isTrip = false, tripTitle = null) {
  const modal = document.getElementById("flythrough-modal");
  disposeEarthMap();
  openDialog(modal);
  document.getElementById("floating-hotspot-card")?.classList.add("hidden");

  try {
    await Promise.all([
      loadStylesheetOnce("/vendor/maplibre-gl/maplibre-gl.css"),
      loadExternalScriptOnce("/vendor/maplibre-gl/maplibre-gl.js"),
    ]);

    const encodedId = encodeURIComponent(String(targetId));
    const url = isTrip
      ? `/api/trips/flythrough?trip_id=${encodedId}`
      : `/api/segments/3d-tour?segment_id=${encodedId}`;

    const { aborted, data } = await fetchSlotJson("earth-tour", url);
    if (aborted || !data || data.status !== "SUCCESS") return;

    earthTrajectory = data.trajectory || [];
    earthCurrentIdx = 0;
    earthTotalDistanceMeters = Number(data.distance_meters) || 0;
    isRiding = false;

    const locTitle = isTrip
      ? `${tripTitle || data.title || "Trip"}${data.start_date ? ` (${data.start_date})` : ""}`
      : `Location history from ${data.date || state.currentDate}`;
    setElText("earth-tour-location-title", locTitle);

    const kmlBtn = document.getElementById("btn-export-earth-kml");
    if (kmlBtn) {
      kmlBtn.onclick = () => {
        window.location.href = isTrip
          ? `/api/trips/export.kml?trip_id=${encodedId}`
          : `/api/segments/export-kml?segment_id=${encodedId}`;
      };
    }

    const mode = data.mode || data.title || "Movement";
    setElText("hud-activity-title", mode);
    setElText("hud-activity-desc", data.description || `${mode} trajectory`);

    const iconWrap = document.getElementById("hud-mode-icon");
    if (iconWrap) {
      let mIcon = "fa-person-walking";
      const upMode = String(mode).toUpperCase();
      if (upMode.includes("CYCLE") || upMode.includes("BIKE")) mIcon = "fa-bicycle";
      else if (upMode.includes("TAXI") || upMode.includes("CAB")) mIcon = "fa-taxi";
      else if (upMode.includes("DRIVE") || upMode.includes("VEHICLE") || upMode.includes("CAR")) mIcon = "fa-car";
      else if (upMode.includes("FLY") || upMode.includes("FLIGHT")) mIcon = "fa-plane";
      else if (upMode.includes("TRAIN") || upMode.includes("SUBWAY")) mIcon = "fa-train-subway";
      iconWrap.innerHTML = `<i class="fa-solid ${mIcon}"></i>`;
    }

    const distKm = (earthTotalDistanceMeters / 1000.0).toFixed(1);
    const progVal = document.getElementById("hud-progress-val");
    if (progVal) progVal.innerHTML = `0.0 / ${distKm} <small>km</small>`;
    const speedVal = document.getElementById("hud-speed-val");
    if (speedVal) speedVal.innerHTML = `${Number(data.avg_speed_kmh || 0).toFixed(1)} <small>km/h</small>`;
    setElText("hud-origin-name", data.origin_name || "Origin");
    setElText("hud-dest-name", data.dest_name || "Destination");

    const playBtn = document.getElementById("btn-fly-play");
    if (playBtn) playBtn.innerHTML = '<i class="fa-solid fa-play"></i> Play Ride';
    const rangeEl = document.getElementById("fly-scrubber-range");
    if (rangeEl) rangeEl.value = "0";
    setElText("fly-progress-text", "0%");

    if (!earthTrajectory.length) return;

    const firstPt = earthTrajectory[0];
    const initialLng = Number(firstPt.lng);
    const initialLat = Number(firstPt.lat);
    const initialBearing = Number(firstPt.bearing) || 0;

    const container = document.getElementById("earth-tour-map");
    if (container) container.innerHTML = "";

    const maplibregl = window.maplibregl;
    if (!maplibregl) return;

    earthMap = new maplibregl.Map({
      container: "earth-tour-map",
      style: {
        version: 8,
        sources: {
          satellite: {
            type: "raster",
            tiles: [
              "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            ],
            tileSize: 256,
          },
        },
        layers: [
          {
            id: "satellite-layer",
            type: "raster",
            source: "satellite",
            minzoom: 0,
            maxzoom: 20,
          },
        ],
      },
      center: [initialLng, initialLat],
      zoom: 17.2,
      pitch: 62,
      bearing: initialBearing,
      attributionControl: false,
    });

    earthMap.on("load", () => {
      if (!earthMap) return;
      const routeCoords = earthTrajectory.map((pt) => [Number(pt.lng), Number(pt.lat)]);

      earthMap.addSource("route-source", {
        type: "geojson",
        data: {
          type: "Feature",
          properties: {},
          geometry: {
            type: "LineString",
            coordinates: routeCoords,
          },
        },
      });

      earthMap.addLayer({
        id: "route-casing",
        type: "line",
        source: "route-source",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: {
          "line-color": "#7f1d1d",
          "line-width": 8,
          "line-opacity": 0.85,
        },
      });

      earthMap.addLayer({
        id: "route-core",
        type: "line",
        source: "route-source",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: {
          "line-color": "#ef4444",
          "line-width": 5,
          "line-opacity": 0.98,
        },
      });

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
  } catch (err) {
    console.error("Error opening 3D Earth ride:", err);
  }
}

function stepEarthRide() {
  if (!isRiding || !earthTrajectory.length || !earthMap) return;

  const speed = parseInt(document.getElementById("fly-speed-select")?.value || "3", 10) || 3;
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
      easing: (t) => t,
    });

    if (earthRiderMarker) {
      earthRiderMarker.setLngLat([pt.lng, pt.lat]);
      const arrow = document.getElementById("rider-beacon-arrow");
      if (arrow) arrow.style.transform = `rotate(${pt.bearing || 0}deg)`;
    }

    const denom = Math.max(1, earthTrajectory.length - 1);
    const pct = Math.round((earthCurrentIdx / denom) * 100);
    const rangeEl = document.getElementById("fly-scrubber-range");
    if (rangeEl) rangeEl.value = String(pct);
    setElText("fly-progress-text", `${pct}%`);

    const totalDistM = earthTotalDistanceMeters || 2500;
    const covKm = ((earthCurrentIdx / denom) * (totalDistM / 1000.0)).toFixed(1);
    const totKm = (totalDistM / 1000.0).toFixed(1);
    const progVal = document.getElementById("hud-progress-val");
    if (progVal) progVal.innerHTML = `${covKm} / ${totKm} <small>km</small>`;

    const deg = ((Math.round(pt.bearing || 0) % 360) + 360) % 360;
    const compassDirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
    const compStr = compassDirs[Math.round(deg / 45) % 8];
    const bearVal = document.getElementById("hud-bearing-val");
    if (bearVal) bearVal.innerHTML = `${String(deg).padStart(3, "0")}° <small>${compStr}</small>`;
  }

  if (earthCurrentIdx >= earthTrajectory.length - 1) {
    isRiding = false;
    const playBtn = document.getElementById("btn-fly-play");
    if (playBtn) playBtn.innerHTML = '<i class="fa-solid fa-rotate-left"></i> Replay Ride';
    return;
  }

  earthAnimationId = requestAnimationFrame(stepEarthRide);
}

export function initEarthPlayerEvents() {
  const modal = document.getElementById("flythrough-modal");
  modal?.addEventListener("close", () => {
    disposeEarthMap();
  });

  document.getElementById("btn-fly-play")?.addEventListener("click", () => {
    const playBtn = document.getElementById("btn-fly-play");
    if (!isRiding) {
      if (earthCurrentIdx >= earthTrajectory.length - 1) earthCurrentIdx = 0;
      isRiding = true;
      if (playBtn) playBtn.innerHTML = '<i class="fa-solid fa-pause"></i> Pause';
      stepEarthRide();
    } else {
      isRiding = false;
      if (playBtn) playBtn.innerHTML = '<i class="fa-solid fa-play"></i> Play Ride';
      if (earthAnimationId) cancelAnimationFrame(earthAnimationId);
    }
  });

  document.getElementById("btn-hud-replay")?.addEventListener("click", () => {
    earthCurrentIdx = 0;
    isRiding = true;
    const playBtn = document.getElementById("btn-fly-play");
    if (playBtn) playBtn.innerHTML = '<i class="fa-solid fa-pause"></i> Pause';
    stepEarthRide();
  });

  document.getElementById("fly-scrubber-range")?.addEventListener("input", (e) => {
    if (!earthTrajectory.length) return;
    const pct = parseInt(e.target.value, 10) || 0;
    earthCurrentIdx = Math.round((pct / 100) * Math.max(0, earthTrajectory.length - 1));
    const pt = earthTrajectory[earthCurrentIdx];
    if (pt && earthMap) {
      earthMap.setCenter([pt.lng, pt.lat]);
      if (earthRiderMarker) earthRiderMarker.setLngLat([pt.lng, pt.lat]);
      setElText("fly-progress-text", `${pct}%`);
    }
  });

  document.getElementById("btn-fly-close")?.addEventListener("click", close3DModal);
  document.getElementById("btn-hud-close")?.addEventListener("click", close3DModal);
}
