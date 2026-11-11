import { getLocalToday } from "./time.js";

export const safeStorage = {
  getItem(key) {
    try {
      return window.localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  setItem(key, val) {
    try {
      window.localStorage.setItem(key, val);
    } catch {
      // Storage unavailable in restricted browsing contexts
    }
  },
};

export const ORIGIN_LABELS = {
  places: "Places Catalog",
  trips: "Trips & Passport",
  activities: "Activities & Movement",
  diagnostics: "Diagnostics & Gaps",
  fixes: "Fix Proposals",
  heatmap: "World Heatmap",
  calendar: "Calendar Matrix",
  search: "Search Results",
};

const initialParams = new URLSearchParams(window.location.search);

export const state = {
  currentDate: initialParams.get("date") || getLocalToday(),
  dayLoadedOnce: false,
  activeTab: initialParams.get("tab") || "timeline",
  navOriginTab: null,
  pendingHighlightSegmentId: null,
  showRawSignals: false,
  currentMapStyle: safeStorage.getItem("mapStyle") || "google_roads",
  gmmPanelOpen: false,

  currentCategory: "ALL",
  currentCity: "ALL",
  currentEra: "ALL",
  currentCadence: "ALL",
  currentDwell: "ALL",
  currentSort: "visits_desc",
  reviewedOnly: false,
  currentPlacesQuery: initialParams.get("q") || "",
  currentPlacesSubtab: "list",

  currentFixesFilter: "pending",
  currentFixesSource: "ALL",
  selectedFixProposal: null,

  currentTripCountry: "ALL",
  currentActivityPeriod: "all",
  calFocusDate: null,
};

export const appNav = {
  switchTab: () => {},
  jumpToTimelineDay: () => {},
  loadDay: async () => {},
  loadOverview: async () => {},
  loadPlaces: async () => {},
  loadTrips: async () => {},
  loadFixProposals: async () => {},
  openPlaceVisitsModal: async () => {},
  openPersonVisitsModal: async () => {},
  openEditSegmentModal: () => {},
  openAddSegmentModal: () => {},
  openEarthRidePlayer: async () => {},
  openFlythroughPlayer: async () => {},
  openPhotoLightbox: () => {},
  openDuplicateComparison: async () => {},
  openEditPlaceModal: () => {},
  updateOriginBanner: () => {},
};

export function registerNavigator(handlers) {
  Object.assign(appNav, handlers);
}

export function getGlobalSearchQuery() {
  return document.getElementById("global-search-input")?.value?.trim() || "";
}

export function updateUrlQuery(q) {
  try {
    const url = new URL(window.location.href);
    const trimmed = q ? String(q).trim() : "";
    if (trimmed) {
      url.searchParams.set("q", trimmed);
    } else {
      url.searchParams.delete("q");
    }
    window.history.replaceState({ ...(window.history.state || {}), q: trimmed }, "", url.toString());
  } catch (err) {
    console.warn("Could not update URL query:", err);
  }
}

const cacheInvalidators = new Set();

export function registerCacheInvalidator(fn) {
  if (typeof fn === "function") {
    cacheInvalidators.add(fn);
  }
}

export function invalidateClientCaches() {
  for (const fn of cacheInvalidators) {
    try {
      fn();
    } catch (err) {
      console.warn("Cache invalidator error:", err);
    }
  }
}
