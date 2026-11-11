import { fetchSlotJson, postJson } from "../api.js";
import { escapeHtml, formatPeopleList, getPhotoUrl, safeHref, setElText } from "../dom.js";
import {
  ACTIVITY_COLORS,
  ACTIVITY_ICONS,
  focusSegmentOnDayMap,
  getPlaceIcon,
  renderDayMap,
  updateScrubberBeacon,
} from "../maps.js";
import { ORIGIN_LABELS, appNav, invalidateClientCaches, state } from "../state.js";
import {
  format24hTime,
  formatActivityName,
  getDayStartEpoch,
  getLocalToday,
  stepDate,
} from "../time.js";

export function updateOriginBanner() {
  const banner = document.getElementById("timeline-origin-banner");
  if (!banner) return;

  if (!state.navOriginTab || state.navOriginTab === "timeline") {
    banner.hidden = true;
    banner.style.display = "none";
    banner.innerHTML = "";
    return;
  }

  const originLabel = ORIGIN_LABELS[state.navOriginTab] || "Previous View";
  banner.hidden = false;
  banner.style.display = "flex";
  banner.innerHTML = `
    <span style="font-size:12px;color:var(--text-main);">
      <i class="fa-solid fa-compass" style="color:var(--accent-blue);margin-right:4px;"></i>
      Navigated from <strong>${escapeHtml(originLabel)}</strong>
    </span>
    <button type="button" id="btn-return-origin-tab" class="btn btn-xs btn-secondary" style="padding:3px 10px;font-size:11.5px;">
      <i class="fa-solid fa-arrow-left"></i> Back to ${escapeHtml(originLabel)}
    </button>
  `;
  document.getElementById("btn-return-origin-tab")?.addEventListener("click", () => {
    const dest = state.navOriginTab;
    state.navOriginTab = null;
    updateOriginBanner();
    if (dest && dest !== "search") {
      appNav.switchTab(dest, true);
    }
  });
}

function setup24hScrubber(dayData) {
  const bar = document.getElementById("scrubber-bar");
  if (!bar) return;

  bar.innerHTML = "";
  const dayStartTs = getDayStartEpoch(dayData);
  const daySpanSec = 86400.0;

  for (const g of dayData.gaps || []) {
    const sTs = g.start_time ? Date.parse(g.start_time) / 1000.0 : NaN;
    const eTs = g.end_time ? Date.parse(g.end_time) / 1000.0 : NaN;
    if (!Number.isFinite(sTs) || !Number.isFinite(eTs)) continue;
    const leftPct = Math.max(0, Math.min(100, ((sTs - dayStartTs) / daySpanSec) * 100));
    const widthPct = Math.max(0.5, Math.min(100 - leftPct, ((eTs - sTs) / daySpanSec) * 100));
    const block = document.createElement("div");
    block.style.cssText = `position:absolute;top:0;bottom:0;left:${leftPct.toFixed(2)}%;width:${widthPct.toFixed(2)}%;background:rgba(220,38,38,0.45);`;
    block.title = `Gap: ${Math.round(g.duration_minutes || 0)} min`;
    bar.appendChild(block);
  }

  for (const s of dayData.segments || []) {
    const sTs = s.start_time ? Date.parse(s.start_time) / 1000.0 : NaN;
    const eTs = s.end_time ? Date.parse(s.end_time) / 1000.0 : NaN;
    if (!Number.isFinite(sTs) || !Number.isFinite(eTs)) continue;
    const leftPct = Math.max(0, Math.min(100, ((sTs - dayStartTs) / daySpanSec) * 100));
    const widthPct = Math.max(0.6, Math.min(100 - leftPct, ((eTs - sTs) / daySpanSec) * 100));
    const isVisit = s.segment_type === "visit";
    const bgColor = isVisit
      ? "#1a73e8"
      : ACTIVITY_COLORS[s.activity_type] || "#10b981";
    const block = document.createElement("div");
    block.style.cssText = `position:absolute;top:0;bottom:0;left:${leftPct.toFixed(2)}%;width:${widthPct.toFixed(2)}%;background:${bgColor};opacity:${isVisit ? "0.9" : "0.75"};`;
    block.title = `${isVisit ? s.place_name || "Visit" : formatActivityName(s.activity_type)} (${format24hTime(s.start_time)} – ${format24hTime(s.end_time)})`;
    bar.appendChild(block);
  }

  const cursorEl = document.createElement("div");
  cursorEl.style.cssText =
    "position:absolute;top:-2px;bottom:-2px;width:2px;background:#0f172a;pointer-events:none;display:none;";
  bar.appendChild(cursorEl);

  const scrubAtClientX = (clientX) => {
    const rect = bar.getBoundingClientRect();
    if (!rect.width) return;
    const frac = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    cursorEl.style.display = "block";
    cursorEl.style.left = `${(frac * 100).toFixed(2)}%`;
    updateScrubberBeacon(dayStartTs + frac * daySpanSec);
  };

  bar.onpointerdown = (e) => {
    bar.setPointerCapture(e.pointerId);
    scrubAtClientX(e.clientX);
    bar.onpointermove = (ev) => scrubAtClientX(ev.clientX);
    bar.onpointerup = () => {
      bar.onpointermove = null;
      bar.onpointerup = null;
    };
  };
}

function renderTimelineToolbar(dayData) {
  const toolbar = document.createElement("div");
  toolbar.style.cssText =
    "display:flex;align-items:center;justify-content:space-between;gap:6px;flex-wrap:wrap;padding:6px 4px 10px 4px;";

  const rawCount = Array.isArray(dayData.breadcrumbs) ? dayData.breadcrumbs.length : Number(dayData.breadcrumb_count || 0);

  toolbar.innerHTML = `
    <div style="display:flex;gap:6px;flex-wrap:wrap;">
      <button type="button" class="btn btn-xs btn-secondary" id="tl-btn-add-seg" title="Add visit or movement segment">
        <i class="fa-solid fa-plus"></i> Add
      </button>
      <button type="button" class="btn btn-xs btn-secondary ${state.showRawSignals ? "active" : ""}" id="tl-btn-raw-signals" title="Toggle raw GPS breadcrumbs on map">
        <i class="fa-solid fa-satellite-dish"></i> Raw${rawCount ? ` (${rawCount})` : ""}
      </button>
      <button type="button" class="btn btn-xs btn-secondary" id="tl-btn-reinfer" title="Run multi-source re-inference on this day">
        <i class="fa-solid fa-wand-magic-sparkles"></i> Re-Infer
      </button>
      <button type="button" class="btn btn-xs btn-secondary" id="tl-btn-gmm-comp" title="Open Android Device Comparator">
        <i class="fa-solid fa-mobile-screen"></i> Device Diff
      </button>
      <button type="button" class="btn btn-xs btn-secondary" id="tl-btn-export-geojson" title="Export day as GeoJSON">
        <i class="fa-solid fa-download"></i> GeoJSON
      </button>
    </div>
  `;

  toolbar.querySelector("#tl-btn-add-seg")?.addEventListener("click", () => {
    appNav.openAddSegmentModal(state.currentDate);
  });
  toolbar.querySelector("#tl-btn-raw-signals")?.addEventListener("click", () => {
    state.showRawSignals = !state.showRawSignals;
    loadDay(state.currentDate, false);
  });
  toolbar.querySelector("#tl-btn-reinfer")?.addEventListener("click", () => {
    appNav.triggerReinferDay?.();
  });
  toolbar.querySelector("#tl-btn-gmm-comp")?.addEventListener("click", () => {
    appNav.openGMMComparator?.(state.currentDate);
  });
  toolbar.querySelector("#tl-btn-export-geojson")?.addEventListener("click", () => {
    window.open(`/api/export?date=${encodeURIComponent(state.currentDate)}&format=geojson`, "_blank", "noopener");
  });

  return toolbar;
}

function renderItineraryCards(dayData) {
  const container = document.getElementById("itinerary-container");
  if (!container) return;
  container.innerHTML = "";

  container.appendChild(renderTimelineToolbar(dayData));

  const segments = dayData.segments || [];
  const calendarEvents = dayData.calendar_events || [];
  const proposals = dayData.proposals || dayData.fixes || [];
  const anomaliesBySegId = new Map();
  for (const a of dayData.anomalies || []) {
    if (a.segment_id) anomaliesBySegId.set(Number(a.segment_id), a);
  }

  for (const ev of calendarEvents) {
    const evBox = document.createElement("div");
    evBox.className = "calendar-event-box card";
    evBox.style.cssText =
      "padding:10px 12px;margin-bottom:8px;border-left:4px solid #7e22ce;background:#faf5ff;color:#3b0764;";
    evBox.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">
        <span style="font-size:11px;font-weight:700;color:#6b21a8;text-transform:uppercase;">
          <i class="fa-regular fa-calendar-check"></i> Calendar Event
        </span>
        <span style="font-size:11px;color:#475569;font-family:var(--font-mono);flex-shrink:0;">
          ${escapeHtml(format24hTime(ev.start_time))} – ${escapeHtml(format24hTime(ev.end_time))}
        </span>
      </div>
      <div style="font-size:13px;font-weight:700;color:#1e1b4b;margin-top:3px;">${escapeHtml(ev.summary || ev.title || "Event")}</div>
      ${ev.location ? `<div style="font-size:11.5px;color:#475569;margin-top:2px;"><i class="fa-solid fa-location-dot"></i> ${escapeHtml(ev.location)}</div>` : ""}
    `;
    container.appendChild(evBox);
  }

  for (const prop of proposals) {
    const pBox = document.createElement("div");
    pBox.className = "proposal-box card";
    pBox.style.cssText =
      "padding:10px 12px;margin-bottom:8px;border-left:4px solid #2563eb;background:#eff6ff;color:#0f172a;";
    pBox.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">
        <span style="font-size:11px;font-weight:700;color:#1d4ed8;">
          <i class="fa-solid fa-wand-magic-sparkles"></i> Candidate Fix Proposal
        </span>
        <button type="button" class="btn btn-xs btn-primary btn-review-day-fix" style="padding:2px 8px;font-size:11px;">Review</button>
      </div>
      <div style="font-size:12.5px;font-weight:600;color:#0f172a;margin-top:3px;">${escapeHtml(prop.description || prop.proposed_place_name || "Suggested repair")}</div>
    `;
    pBox.querySelector(".btn-review-day-fix")?.addEventListener("click", () => {
      appNav.switchTab("fixes", true);
    });
    container.appendChild(pBox);
  }

  if (!segments.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.style.padding = "32px 16px";
    empty.innerHTML = `
      <i class="fa-regular fa-calendar-xmark" style="font-size:24px;color:var(--text-muted);margin-bottom:8px;"></i>
      <p style="margin:0;color:var(--text-muted);font-size:13px;">No recorded timeline segments on ${escapeHtml(dayData.date)}.</p>
    `;
    container.appendChild(empty);
    return;
  }

  let visitCounter = 0;

  segments.forEach((s) => {
    const isVisit = s.segment_type === "visit";
    const card = document.createElement("article");
    card.className = `segment-card card ${isVisit ? "visit-card" : "activity-card"}`;
    card.dataset.segmentId = String(s.id);

    const anomaly = anomaliesBySegId.get(Number(s.id));
    const timeRange = `${format24hTime(s.start_time)} – ${format24hTime(s.end_time)}`;
    const durMin = Math.round(Number(s.duration_minutes) || 0);
    const durLabel = durMin >= 60 ? `${Math.floor(durMin / 60)}h ${durMin % 60}m` : `${durMin}m`;

    if (isVisit) {
      visitCounter += 1;
      const placeName = s.place_name || "Place Visit";
      const iconCls = getPlaceIcon(placeName, s.category);
      const photos = Array.isArray(s.photos) ? s.photos : [];
      const photoStripHtml = photos.length
        ? `<div class="segment-photo-strip" style="display:flex;gap:6px;overflow-x:auto;margin-top:8px;padding-bottom:2px;">
            ${photos
              .slice(0, 8)
              .map((ph, idx) => {
                const rawUrl = ph.preview_url || (ph.sha256 ? `/api/photo?sha256=${encodeURIComponent(ph.sha256)}` : ph.url || "");
                const thumbUrl = escapeHtml(getPhotoUrl(rawUrl, "thumb"));
                return `<img src="${thumbUrl}" alt="${escapeHtml(placeName)} photo ${idx + 1}" loading="lazy" decoding="async" data-hide-on-error="self" data-photo-idx="${idx}" style="width:56px;height:56px;object-fit:cover;border-radius:6px;cursor:pointer;border:1px solid var(--border-color);flex-shrink:0;">`;
              })
              .join("")}
          </div>`
        : "";

      card.innerHTML = `
        <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:10px;">
          <div style="display:flex;align-items:flex-start;gap:10px;min-width:0;flex:1;">
            <div style="width:32px;height:32px;border-radius:50%;background:rgba(26,115,232,0.12);color:#1a73e8;display:flex;align-items:center;justify-content:center;font-size:13px;flex-shrink:0;">
              <i class="fa-solid ${iconCls}"></i>
            </div>
            <div style="min-width:0;flex:1;">
              <div style="display:flex;align-items:center;gap:6px;">
                <span style="font-size:11px;font-weight:700;color:var(--text-muted);font-family:var(--font-mono);flex-shrink:0;">#${visitCounter}</span>
                <h4 class="seg-title-link" style="margin:0;font-size:14px;font-weight:700;color:var(--text-main);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0;flex:1;cursor:pointer;" title="${escapeHtml(placeName)}">${escapeHtml(placeName)}</h4>
              </div>
              ${s.address ? `<div style="font-size:11.5px;color:var(--text-muted);margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escapeHtml(s.address)}">${escapeHtml(s.address)}</div>` : ""}
              <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-top:5px;">
                ${s.category ? `<span class="tag-badge" style="font-size:10.5px;">${escapeHtml(s.category)}</span>` : ""}
                ${formatPeopleList(s.with_people) ? `<span class="tag-badge" style="font-size:10.5px;background:#f3e8ff;color:#6b21a8;"><i class="fa-solid fa-user-group"></i> ${escapeHtml(formatPeopleList(s.with_people))}</span>` : ""}
                ${anomaly ? `<span class="tag-badge" style="font-size:10.5px;background:#fef2f2;color:#b91c1c;"><i class="fa-solid fa-triangle-exclamation"></i> ${escapeHtml(anomaly.anomaly_type || "Anomaly")}</span>` : ""}
              </div>
              ${s.notes ? `<div style="font-size:12px;color:#334155;margin-top:6px;line-height:1.4;">${escapeHtml(s.notes)}</div>` : ""}
              ${photoStripHtml}
            </div>
          </div>
          <div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px;flex-shrink:0;">
            <span style="font-size:11.5px;font-weight:600;color:#334155;font-family:var(--font-mono);flex-shrink:0;">${escapeHtml(timeRange)}</span>
            <span style="font-size:11px;color:var(--text-muted);">${escapeHtml(durLabel)}</span>
            <div style="display:flex;gap:4px;margin-top:2px;">
              ${s.place_id ? `<button type="button" class="icon-btn btn-seg-history" title="All visits to this place" style="width:26px;height:26px;font-size:11px;"><i class="fa-solid fa-clock-rotate-left"></i></button>` : ""}
              ${s.google_maps_url ? `<a href="${safeHref(s.google_maps_url)}" target="_blank" rel="noopener noreferrer" class="icon-btn" title="Open in Google Maps" style="width:26px;height:26px;font-size:11px;text-decoration:none;"><i class="fa-solid fa-arrow-up-right-from-square"></i></a>` : ""}
              <button type="button" class="icon-btn btn-seg-edit" title="Edit visit" style="width:26px;height:26px;font-size:11px;"><i class="fa-solid fa-pen"></i></button>
            </div>
          </div>
        </div>
      `;

      card.querySelector(".seg-title-link")?.addEventListener("click", () => {
        focusSegmentOnDayMap(s.id);
      });
      card.querySelector(".btn-seg-history")?.addEventListener("click", (e) => {
        e.stopPropagation();
        appNav.openPlaceVisitsModal(s.place_id, placeName);
      });
      card.querySelector(".btn-seg-edit")?.addEventListener("click", (e) => {
        e.stopPropagation();
        appNav.openEditSegmentModal(s);
      });

      if (photos.length) {
        const allUrls = photos
          .map((ph) => getPhotoUrl(ph.preview_url || (ph.sha256 ? `/api/photo?sha256=${encodeURIComponent(ph.sha256)}` : ph.url || ""), "orig"))
          .filter(Boolean);
        card.querySelectorAll("img[data-photo-idx]").forEach((imgEl) => {
          imgEl.addEventListener("click", (e) => {
            e.stopPropagation();
            const idx = Number(imgEl.dataset.photoIdx) || 0;
            appNav.openPhotoLightbox(allUrls, idx, placeName, s.notes || "");
          });
        });
      }
    } else {
      const actType = s.activity_type || "UNKNOWN_ACTIVITY_TYPE";
      const actColor = ACTIVITY_COLORS[actType] || "#2563eb";
      const actIcon = ACTIVITY_ICONS[actType] || "fa-route";
      const distKm = s.distance_meters ? `${(s.distance_meters / 1000).toFixed(1)} km` : "";

      card.style.borderLeft = `3px solid ${actColor}`;
      card.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;">
          <div style="display:flex;align-items:center;gap:10px;min-width:0;flex:1;">
            <div style="width:28px;height:28px;border-radius:8px;background:${actColor}1f;color:${actColor};display:flex;align-items:center;justify-content:center;font-size:12.5px;flex-shrink:0;">
              <i class="fa-solid ${actIcon}"></i>
            </div>
            <div style="min-width:0;flex:1;">
              <div style="display:flex;align-items:center;gap:6px;">
                <strong class="seg-act-focus" style="font-size:13px;color:var(--text-main);cursor:pointer;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(formatActivityName(actType))}</strong>
                ${distKm ? `<span style="font-size:11.5px;font-weight:600;color:${actColor};font-family:var(--font-mono);flex-shrink:0;">${escapeHtml(distKm)}</span>` : ""}
                ${anomaly ? `<span class="tag-badge" style="font-size:10px;background:#fef2f2;color:#b91c1c;">🚨 ${escapeHtml(anomaly.anomaly_type || "Outlier")}</span>` : ""}
              </div>
              ${s.notes ? `<div style="font-size:11.5px;color:var(--text-muted);margin-top:2px;">${escapeHtml(s.notes)}</div>` : ""}
            </div>
          </div>
          <div style="display:flex;align-items:center;gap:6px;flex-shrink:0;">
            <div style="text-align:right;">
              <div style="font-size:11px;font-weight:600;color:#334155;font-family:var(--font-mono);">${escapeHtml(timeRange)}</div>
              <div style="font-size:10.5px;color:var(--text-muted);">${escapeHtml(durLabel)}</div>
            </div>
            <button type="button" class="icon-btn btn-seg-3d" title="3D Route Ride-Along" style="width:26px;height:26px;font-size:11px;color:${actColor};"><i class="fa-solid fa-cube"></i></button>
            <button type="button" class="icon-btn btn-seg-edit" title="Edit movement" style="width:26px;height:26px;font-size:11px;"><i class="fa-solid fa-pen"></i></button>
          </div>
        </div>
      `;

      card.querySelector(".seg-act-focus")?.addEventListener("click", () => {
        focusSegmentOnDayMap(s.id);
      });
      card.querySelector(".btn-seg-3d")?.addEventListener("click", (e) => {
        e.stopPropagation();
        appNav.openEarthRidePlayer(s.id, false);
      });
      card.querySelector(".btn-seg-edit")?.addEventListener("click", (e) => {
        e.stopPropagation();
        appNav.openEditSegmentModal(s);
      });
    }

    container.appendChild(card);
  });

  if (state.pendingHighlightSegmentId) {
    const targetId = String(state.pendingHighlightSegmentId);
    state.pendingHighlightSegmentId = null;
    const targetCard = container.querySelector(`[data-segment-id="${CSS.escape(targetId)}"]`);
    if (targetCard) {
      targetCard.scrollIntoView({ behavior: "smooth", block: "center" });
      targetCard.classList.add("highlight-pulse");
      focusSegmentOnDayMap(Number(targetId));
    }
  }
}

export async function loadDay(dateStr, pushHistory = true) {
  const resolvedDate = dateStr || state.currentDate || getLocalToday();
  state.currentDate = resolvedDate;

  const picker = document.getElementById("date-picker");
  if (picker && picker.value !== resolvedDate) {
    picker.value = resolvedDate;
  }

  if (pushHistory) {
    const url = new URL(window.location.href);
    url.searchParams.set("tab", "timeline");
    url.searchParams.set("date", resolvedDate);
    window.history.pushState(
      { tab: "timeline", date: resolvedDate, fromTab: state.navOriginTab, q: url.searchParams.get("q") || "" },
      "",
      url.toString()
    );
  }

  const container = document.getElementById("itinerary-container");
  if (container && !state.dayLoadedOnce) {
    container.innerHTML = `<div class="loading-spinner"><i class="fa-solid fa-circle-notch fa-spin"></i> Loading Itinerary...</div>`;
  }

  try {
    const query = `/api/day?date=${encodeURIComponent(resolvedDate)}${state.showRawSignals ? "&include_breadcrumbs=true" : ""}`;
    const { aborted, data } = await fetchSlotJson("day", query);
    if (aborted || !data || data.status !== "SUCCESS") return;

    state.dayLoadedOnce = true;
    const segments = data.segments || [];
    const visitsCount = segments.filter((s) => s.segment_type === "visit").length;
    const actsCount = segments.filter((s) => s.segment_type === "activity").length;
    const totalDistKm = (
      segments.reduce((acc, s) => acc + (Number(s.distance_meters) || 0), 0) / 1000.0
    ).toFixed(1);

    setElText(
      "day-summary-text",
      `${resolvedDate} · ${visitsCount} visit${visitsCount === 1 ? "" : "s"} · ${actsCount} move${actsCount === 1 ? "" : "s"} · ${totalDistKm} km`
    );

    renderDayMap(data);
    setup24hScrubber(data);
    renderItineraryCards(data);

    if (state.gmmPanelOpen) {
      appNav.loadGMMComparison?.(resolvedDate);
    }
  } catch (err) {
    console.error("Error loading day:", err);
    if (container) {
      container.innerHTML = `<div class="empty-state">Failed to load itinerary for ${escapeHtml(resolvedDate)}: ${escapeHtml(err.message)}</div>`;
    }
  }
}

export function initTimelineEvents() {
  const picker = document.getElementById("date-picker");
  if (picker) {
    picker.value = state.currentDate;
    picker.addEventListener("change", (e) => {
      if (e.target.value) {
        loadDay(e.target.value, true);
      }
    });
  }

  document.getElementById("btn-prev-day")?.addEventListener("click", () => {
    loadDay(stepDate(state.currentDate, -1), true);
  });

  document.getElementById("btn-next-day")?.addEventListener("click", () => {
    loadDay(stepDate(state.currentDate, 1), true);
  });

  document.getElementById("btn-jump-today")?.addEventListener("click", () => {
    loadDay(getLocalToday(), true);
  });

  document.getElementById("btn-sync-device")?.addEventListener("click", async () => {
    const btn = document.getElementById("btn-sync-device");
    const oldHtml = btn ? btn.innerHTML : "";
    if (btn) {
      btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Syncing...';
      btn.disabled = true;
    }
    try {
      const { data } = await postJson("/api/sync-device", {});
      if (data.status === "SUCCESS") {
        invalidateClientCaches();
        await loadDay(state.currentDate, false);
        appNav.loadOverview();
      } else {
        alert(data.message || data.error || "Device sync completed with warnings.");
      }
    } catch (err) {
      alert(`Error connecting to ADB extraction daemon: ${err.message}`);
    } finally {
      if (btn) {
        btn.innerHTML = oldHtml;
        btn.disabled = false;
      }
    }
  });
}
