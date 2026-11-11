/**
 * Timeline Studio — Modular ES Module Coordinator
 * Coordinates accessible WAI-ARIA tabs, URL history state, maps, modals, and background overview telemetry.
 */

import { fetchSlotJson } from "./js/api.js";
import {
  hidePopoverSafe,
  initDialogLightDismissFallback,
  initImageErrorDelegation,
  setElText,
} from "./js/dom.js";
import {
  initEarthPlayerEvents,
  openEarthRidePlayer,
  openFlythroughPlayer,
} from "./js/earth-player.js";
import { initMaps, invalidateActiveTabMap, loadWorldHeatmap } from "./js/maps.js";
import { getGlobalSearchQuery, registerNavigator, state } from "./js/state.js";
import { getLocalToday } from "./js/time.js";
import { initActivitiesEvents, loadActivitySummaries } from "./js/views/activities.js";
import { initCalendarMatrixEvents, loadCalendarMatrix } from "./js/views/calendar.js";
import {
  initDiagnosticsEvents,
  loadDiagnosticsGaps,
  loadOutliersLeaderboard,
} from "./js/views/diagnostics.js";
import { initFixesEvents, loadFixProposals } from "./js/views/fixes.js";
import {
  initGMMPanelEvents,
  loadGMMComparison,
  openGMMComparator,
  pauseGMMStream,
  resumeGMMStreamIfEligible,
} from "./js/views/gmm-panel.js";
import {
  initModalsEvents,
  openAddSegmentModal,
  openDuplicateComparison,
  openEditPlaceModal,
  openEditSegmentModal,
  openPersonVisitsModal,
  openPhotoLightbox,
  openPlaceVisitsModal,
  triggerReinferDay,
} from "./js/views/modals.js";
import { initPlacesEvents, loadPlaces } from "./js/views/places.js";
import { initGlobalSearch } from "./js/views/search.js";
import { initTimelineEvents, loadDay, updateOriginBanner } from "./js/views/timeline.js";
import {
  initTripsEvents,
  loadArchiveNuggets,
  loadPassportStats,
  loadTrips,
} from "./js/views/trips.js";

async function loadOverview() {
  try {
    const { aborted, data } = await fetchSlotJson("overview", "/api/overview", {
      priority: "low",
    });
    if (aborted || !data || data.status !== "SUCCESS") return;

    const sc = data.scorecard || data;
    const fmtBadge = (n) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));
    if (sc.total_trips !== undefined) {
      setElText("badge-trips", fmtBadge(Number(sc.total_trips)));
    }
    const placesCount = sc.visited_places_count ?? sc.total_places ?? sc.total_places_catalog;
    if (placesCount !== undefined) {
      setElText("badge-places", fmtBadge(Number(placesCount)));
    }
    if (sc.pending_fixes !== undefined) {
      setElText("badge-fixes", fmtBadge(Number(sc.pending_fixes)));
    }
  } catch (err) {
    console.warn("Overview load warning:", err);
  }
}

export function switchTab(tabName, pushHistory = true) {
  const targetTab = tabName || "timeline";
  state.activeTab = targetTab;

  const tabs = Array.from(document.querySelectorAll(".nav-tabs [role='tab'], .nav-tabs .tab-btn"));
  tabs.forEach((btn) => {
    const isTarget = btn.getAttribute("data-tab") === targetTab;
    btn.classList.toggle("active", isTarget);
    btn.setAttribute("aria-selected", isTarget ? "true" : "false");
    btn.setAttribute("tabindex", isTarget ? "0" : "-1");
  });

  document.querySelectorAll(".tab-panel").forEach((panel) => {
    const isTarget = panel.id === `tab-${targetTab}`;
    panel.classList.toggle("active", isTarget);
    panel.hidden = !isTarget;
  });

  if (targetTab !== "timeline") {
    pauseGMMStream();
  } else {
    resumeGMMStreamIfEligible();
  }

  if (pushHistory) {
    const url = new URL(window.location.href);
    url.searchParams.set("tab", targetTab);
    url.searchParams.set("date", state.currentDate);
    window.history.pushState(
      {
        tab: targetTab,
        date: state.currentDate,
        fromTab: state.navOriginTab,
        q: url.searchParams.get("q") || "",
      },
      "",
      url.toString()
    );
  }

  invalidateActiveTabMap(targetTab);
  const activeSearchQuery = getGlobalSearchQuery();

  if (targetTab === "timeline") {
    if (!state.dayLoadedOnce) {
      loadDay(state.currentDate, false);
    }
  } else if (targetTab === "calendar") {
    loadCalendarMatrix(state.currentDate);
  } else if (targetTab === "activities") {
    loadActivitySummaries(state.currentActivityPeriod);
  } else if (targetTab === "trips") {
    loadPassportStats();
    loadArchiveNuggets();
    loadTrips(activeSearchQuery, state.currentTripCountry);
  } else if (targetTab === "places") {
    loadPlaces(activeSearchQuery);
  } else if (targetTab === "heatmap") {
    loadWorldHeatmap();
  } else if (targetTab === "fixes") {
    loadFixProposals(activeSearchQuery);
  } else if (targetTab === "diagnostics") {
    loadDiagnosticsGaps();
  } else if (targetTab === "outliers") {
    loadOutliersLeaderboard();
  }
}

export function jumpToTimelineDay(dateStr, pushHistory = true, originOverride = null, highlightSegId = null) {
  if (!dateStr) return;
  const searchDropdown = document.getElementById("global-search-dropdown");
  hidePopoverSafe(searchDropdown);

  const origin = originOverride || (state.activeTab !== "timeline" ? state.activeTab : state.navOriginTab);
  if (origin && origin !== "timeline") {
    state.navOriginTab = origin;
  }
  if (highlightSegId) {
    state.pendingHighlightSegmentId = highlightSegId;
  }

  state.currentDate = dateStr;
  switchTab("timeline", false);
  updateOriginBanner();
  loadDay(dateStr, pushHistory);
}

function setupAccessibleTabs() {
  const tablist = document.querySelector(".nav-tabs");
  if (!tablist) return;

  const tabs = Array.from(tablist.querySelectorAll("[role='tab'], .tab-btn"));
  tabs.forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetTab = btn.getAttribute("data-tab");
      if (targetTab === "timeline") {
        state.navOriginTab = null;
        updateOriginBanner();
      }
      switchTab(targetTab, true);
    });
  });

  tablist.addEventListener("keydown", (e) => {
    const currentIdx = tabs.indexOf(document.activeElement);
    if (currentIdx === -1) return;

    let nextIdx = -1;
    if (e.key === "ArrowRight") {
      nextIdx = (currentIdx + 1) % tabs.length;
    } else if (e.key === "ArrowLeft") {
      nextIdx = (currentIdx - 1 + tabs.length) % tabs.length;
    } else if (e.key === "Home") {
      nextIdx = 0;
    } else if (e.key === "End") {
      nextIdx = tabs.length - 1;
    }

    if (nextIdx !== -1) {
      e.preventDefault();
      tabs.forEach((t, idx) => t.setAttribute("tabindex", idx === nextIdx ? "0" : "-1"));
      tabs[nextIdx].focus();
    }
  });
}

function bootStudio() {
  initImageErrorDelegation();
  initDialogLightDismissFallback();

  registerNavigator({
    switchTab,
    jumpToTimelineDay,
    loadDay,
    loadOverview,
    loadPlaces,
    loadTrips,
    loadFixProposals,
    openPlaceVisitsModal,
    openPersonVisitsModal,
    openEditSegmentModal,
    openAddSegmentModal,
    openEarthRidePlayer,
    openFlythroughPlayer,
    openPhotoLightbox,
    openDuplicateComparison,
    openEditPlaceModal,
    triggerReinferDay,
    openGMMComparator,
    loadGMMComparison,
    updateOriginBanner,
  });

  initMaps();
  setupAccessibleTabs();
  initTimelineEvents();
  initGMMPanelEvents();
  initCalendarMatrixEvents();
  initActivitiesEvents();
  initTripsEvents();
  initPlacesEvents();
  initDiagnosticsEvents();
  initFixesEvents();
  initModalsEvents();
  initEarthPlayerEvents();
  initGlobalSearch();

  window.addEventListener("popstate", (e) => {
    const params = new URLSearchParams(window.location.search);
    const tabFromUrl = params.get("tab") || e.state?.tab || "timeline";
    const dateFromUrl = params.get("date") || e.state?.date || getLocalToday();
    const qFromUrl = params.get("q") || e.state?.q || "";

    const searchInput = document.getElementById("global-search-input");
    const clearBtn = document.getElementById("global-search-clear");
    if (searchInput) {
      searchInput.value = qFromUrl;
      if (clearBtn) clearBtn.style.display = qFromUrl ? "block" : "none";
    }

    if (tabFromUrl !== "timeline") {
      state.navOriginTab = null;
    } else if (e.state?.fromTab) {
      state.navOriginTab = e.state.fromTab;
    }

    state.currentDate = dateFromUrl;
    switchTab(tabFromUrl, false);
    if (tabFromUrl === "timeline") {
      loadDay(dateFromUrl, false);
      updateOriginBanner();
    }
  });

  const initialParams = new URLSearchParams(window.location.search);
  const initialTab = initialParams.get("tab") || "timeline";
  const initialDate = initialParams.get("date") || state.currentDate || getLocalToday();
  const initialQ = initialParams.get("q") || "";
  state.currentDate = initialDate;

  const initialSearch =
    window.location.search ||
    `?tab=${encodeURIComponent(initialTab)}&date=${encodeURIComponent(initialDate)}${initialQ ? `&q=${encodeURIComponent(initialQ)}` : ""}`;
  window.history.replaceState({ tab: initialTab, date: initialDate, q: initialQ }, "", initialSearch);

  switchTab(initialTab, false);

  if (initialQ) {
    const searchInput = document.getElementById("global-search-input");
    const clearBtn = document.getElementById("global-search-clear");
    if (searchInput) {
      searchInput.value = initialQ;
      if (clearBtn) clearBtn.style.display = "block";
      if (initialTab === "timeline") {
        setTimeout(() => {
          window.executeGlobalSearchNow?.(initialQ);
        }, 180);
      }
    }
  }

  if (initialParams.get("device") === "true" || initialParams.get("vm") === "true") {
    setTimeout(() => {
      openGMMComparator(initialDate);
    }, 350);
  }

  const runLowPriorityOverview = () => loadOverview();
  if (typeof window.requestIdleCallback === "function") {
    window.requestIdleCallback(runLowPriorityOverview, { timeout: 1200 });
  } else {
    setTimeout(runLowPriorityOverview, 150);
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bootStudio, { once: true });
} else {
  bootStudio();
}
