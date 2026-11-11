import { fetchSlotJson } from "../api.js";
import { escapeHtml, setElText } from "../dom.js";
import { appNav, getGlobalSearchQuery, state } from "../state.js";

let cachedTrips = [];

export async function loadPassportStats() {
  try {
    const { aborted, data } = await fetchSlotJson("trips-stats", "/api/trips/stats");
    if (aborted || !data || data.status !== "SUCCESS") return;

    setElText("stat-earth-orbits", `${data.earth_orbits}x`);
    setElText("stat-total-flights", data.total_flights);
    setElText("stat-total-countries", data.total_countries);
    setElText("stat-total-trips", data.total_trips);

    const pillsContainer = document.getElementById("country-pills-container");
    if (!pillsContainer) return;
    pillsContainer.innerHTML = "";

    const allPill = document.createElement("button");
    allPill.type = "button";
    allPill.className = `country-pill ${state.currentTripCountry === "ALL" ? "active" : ""}`;
    allPill.textContent = `🌍 All Countries (${data.total_trips})`;
    allPill.addEventListener("click", () => {
      pillsContainer.querySelectorAll(".country-pill").forEach((p) => p.classList.remove("active"));
      allPill.classList.add("active");
      state.currentTripCountry = "ALL";
      loadTrips(getGlobalSearchQuery(), "ALL");
    });
    pillsContainer.appendChild(allPill);

    (data.countries || []).forEach((c) => {
      const pill = document.createElement("button");
      pill.type = "button";
      pill.className = `country-pill ${state.currentTripCountry === c.country ? "active" : ""}`;
      pill.textContent = `${c.flag || "🌍"} ${c.country} (${c.trips_count} visits · ${Math.round(c.total_days)}d)`;
      pill.addEventListener("click", () => {
        pillsContainer.querySelectorAll(".country-pill").forEach((p) => p.classList.remove("active"));
        pill.classList.add("active");
        state.currentTripCountry = c.country;
        loadTrips(getGlobalSearchQuery(), c.country);
      });
      pillsContainer.appendChild(pill);
    });
  } catch (err) {
    console.error("Error loading passport stats:", err);
  }
}

export async function loadArchiveNuggets() {
  const grid = document.getElementById("nuggets-grid-container");
  const rareContainer = document.getElementById("rare-modes-container");
  if (!grid) return;

  try {
    const { aborted, data } = await fetchSlotJson("archive-nuggets", "/api/insights/nuggets");
    if (aborted || !data || data.status !== "SUCCESS") return;

    grid.innerHTML = "";
    (data.nuggets || []).forEach((n) => {
      const card = document.createElement("div");
      card.className = "nugget-card";
      const accent = n.accent || "#2563eb";
      card.innerHTML = `
        <div class="nugget-badge" style="background:${escapeHtml(accent)}20;color:${escapeHtml(accent)};">
          <i class="fa-solid ${escapeHtml(n.icon || "fa-gem")}"></i> ${escapeHtml(n.badge || "Highlight")}
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
          appNav.jumpToTimelineDay(n.date, true, "trips");
        });
      }
      grid.appendChild(card);
    });

    if (rareContainer && Array.isArray(data.rare_modes)) {
      rareContainer.innerHTML = "";
      data.rare_modes.forEach((rm) => {
        const pill = document.createElement("div");
        pill.className = "rare-mode-pill";
        pill.innerHTML = `
          <i class="fa-solid ${escapeHtml(rm.icon || "fa-compass")}" style="color:${escapeHtml(rm.color || "#7e22ce")};font-size:13px;"></i>
          <span><strong>${escapeHtml(rm.title)}:</strong> ${Number(rm.count) || 0} outing${rm.count > 1 ? "s" : ""} (${escapeHtml(rm.total_km)} km · ${escapeHtml(rm.total_hours)}h)</span>
        `;
        if (rm.highlight_date) {
          pill.title = `View peak session on ${rm.highlight_date} (${rm.highlight_dist_km} km)`;
          pill.addEventListener("click", () => {
            appNav.jumpToTimelineDay(rm.highlight_date, true, "trips");
          });
        }
        rareContainer.appendChild(pill);
      });
    }
  } catch (err) {
    console.error("Error loading archive nuggets:", err);
  }
}

function renderTripsGrid(trips) {
  const container = document.getElementById("trips-grid-container");
  if (!container) return;
  container.innerHTML = "";

  if (!trips || trips.length === 0) {
    container.innerHTML =
      '<div class="empty-state" style="grid-column: 1 / -1;"><p>No matching trips or expeditions found.</p></div>';
    return;
  }

  trips.forEach((t) => {
    const card = document.createElement("article");
    card.className = "trip-card";

    const themeClass = escapeHtml(t.theme || "world");
    const flightsBadge =
      t.flights_count > 0
        ? `<span style="color:#be185d;font-size:11px;font-weight:600;"><i class="fa-solid fa-plane"></i> ${Number(t.flights_count)} Flights</span>`
        : "";

    let highlightsHtml = "";
    if (Array.isArray(t.highlights) && t.highlights.length > 0) {
      highlightsHtml = `
        <div class="trip-highlights-list">
          ${t.highlights
            .slice(0, 3)
            .map(
              (h) => `
            <div class="trip-highlight-item">
              <i class="fa-solid fa-location-dot"></i>
              <span style="font-weight:500;">${escapeHtml(h.name)}</span>
              ${h.rating ? `<span style="color:#b45309;font-size:10.5px;font-weight:700;margin-left:auto;"><i class="fa-solid fa-star"></i> ${escapeHtml(h.rating)}</span>` : ""}
            </div>
          `
            )
            .join("")}
        </div>
      `;
    }

    card.innerHTML = `
      <div class="trip-hero-row">
        <span class="trip-badge-theme ${themeClass}">${escapeHtml(t.country_flag || "🌍")} ${escapeHtml(t.country || "Region")}</span>
        ${flightsBadge}
      </div>
      <div>
        <h3 class="trip-dest-title">${escapeHtml(t.title)}</h3>
        <span class="trip-dates"><i class="fa-solid fa-calendar"></i> ${escapeHtml(t.start_date)} → ${escapeHtml(t.end_date)} (${Number(t.duration_days) || 1} days)</span>
      </div>

      <div class="trip-metrics-row">
        <div class="trip-metric-item">
          <span class="trip-metric-val">${Number(t.total_distance_km || 0).toLocaleString()} km</span>
          <span class="trip-metric-lbl">Distance</span>
        </div>
        <div class="trip-metric-item">
          <span class="trip-metric-val">${Number(t.visits_count) || 0}</span>
          <span class="trip-metric-lbl">Stops</span>
        </div>
        <div class="trip-metric-item">
          <span class="trip-metric-val">${Number(t.activities_count) || 0}</span>
          <span class="trip-metric-lbl">Activities</span>
        </div>
      </div>

      ${highlightsHtml}

      <div class="trip-actions-row">
        <button type="button" class="btn-primary btn-open-flythrough" style="flex:1;padding:8px;font-size:12px;display:flex;align-items:center;justify-content:center;gap:6px;">
          <i class="fa-solid fa-person-walking-arrow-right"></i> 3D Flythrough / Night Walk
        </button>
        <button type="button" class="action-btn btn-view-trip-day" title="View Daily Timeline" style="padding:8px 12px;">
          <i class="fa-solid fa-calendar-day"></i>
        </button>
      </div>
    `;

    card.querySelector(".btn-open-flythrough")?.addEventListener("click", () => {
      appNav.openFlythroughPlayer(t.trip_id, t.title);
    });
    card.querySelector(".btn-view-trip-day")?.addEventListener("click", () => {
      appNav.jumpToTimelineDay(t.start_date, true, "trips");
    });

    container.appendChild(card);
  });
}

export async function loadTrips(searchQuery = "", country = state.currentTripCountry) {
  state.currentTripCountry = country || "ALL";
  const container = document.getElementById("trips-grid-container");
  if (container) {
    container.innerHTML =
      '<div class="loading-spinner"><i class="fa-solid fa-circle-notch fa-spin"></i> Loading Trips &amp; Expeditions...</div>';
  }

  try {
    const url =
      state.currentTripCountry && state.currentTripCountry !== "ALL"
        ? `/api/trips?limit=150&country=${encodeURIComponent(state.currentTripCountry)}`
        : `/api/trips?limit=150`;
    const { aborted, data } = await fetchSlotJson("trips-list", url);
    if (aborted) return;
    if (data && data.status === "SUCCESS") {
      cachedTrips = data.trips || [];
      setElText("badge-trips", data.count || cachedTrips.length);
      setElText(
        "trips-count-sub",
        `Showing ${cachedTrips.length} trips${state.currentTripCountry !== "ALL" ? ` in ${state.currentTripCountry}` : ""}`
      );
    }
  } catch (err) {
    console.error("Error loading trips:", err);
    if (container) {
      container.innerHTML = '<div class="empty-state"><p>Failed to load trips.</p></div>';
    }
    return;
  }

  let filtered = cachedTrips;
  if (searchQuery) {
    const q = searchQuery.toLowerCase();
    filtered = cachedTrips.filter(
      (t) =>
        String(t.title || "").toLowerCase().includes(q) ||
        String(t.start_date || "").includes(q) ||
        String(t.end_date || "").includes(q) ||
        String(t.country || "").toLowerCase().includes(q) ||
        (Array.isArray(t.highlights) &&
          t.highlights.some((h) => String(h.name || "").toLowerCase().includes(q)))
    );
  }

  renderTripsGrid(filtered);
}

export function initTripsEvents() {
  document.getElementById("btn-refresh-nuggets")?.addEventListener("click", () => {
    loadArchiveNuggets();
  });
}
