import { fetchSlotJson } from "../api.js";
import { escapeHtml, getPhotoUrl, renderStars, safeHref, setElText } from "../dom.js";
import { CATEGORY_MAP_COLORS, getPlaceIcon, loadAllPlacesMap, panPlacesMapTo } from "../maps.js";
import { appNav, getGlobalSearchQuery, registerCacheInvalidator, state } from "../state.js";

let lifePeriodsLoaded = false;

registerCacheInvalidator(() => {
  lifePeriodsLoaded = false;
});

function renderCategoryPills(categories = []) {
  const container = document.getElementById("category-pills-container");
  if (!container) return;

  container.innerHTML = "";

  const makePill = (catKey, labelText) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `cat-pill ${state.currentCategory === catKey ? "active" : ""}`;
    btn.dataset.cat = catKey;
    btn.textContent = labelText;
    btn.addEventListener("click", () => {
      state.currentCategory = catKey;
      container.querySelectorAll(".cat-pill").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      loadPlaces(getGlobalSearchQuery());
    });
    return btn;
  };

  container.appendChild(makePill("ALL", "All Categories"));
  categories.forEach((c) => {
    const catName = typeof c === "string" ? c : c.category;
    if (!catName) return;
    const countSuffix = typeof c === "object" && c.count ? ` (${c.count})` : "";
    container.appendChild(makePill(catName, `${catName}${countSuffix}`));
  });
}

function populateCitiesDropdown(cities = []) {
  const select = document.getElementById("places-city-select");
  if (!select || !Array.isArray(cities) || !cities.length) return;

  const prevVal = state.currentCity || "ALL";
  select.innerHTML = `<option value="ALL">All Cities &amp; Regions</option>`;
  cities.forEach((c) => {
    const cityName = typeof c === "string" ? c : c.city;
    if (!cityName) return;
    const opt = document.createElement("option");
    opt.value = cityName;
    opt.textContent = typeof c === "object" && c.count ? `${cityName} (${c.count})` : cityName;
    if (cityName === prevVal) opt.selected = true;
    select.appendChild(opt);
  });
}

export async function loadLifePeriods() {
  const container = document.getElementById("life-periods-track-container");
  if (!container || lifePeriodsLoaded) return;

  try {
    const { aborted, data } = await fetchSlotJson("life-periods", "/api/life-periods");
    if (aborted || !data || data.status !== "SUCCESS") return;

    const periods = data.periods || data.life_periods || [];
    lifePeriodsLoaded = true;

    if (!periods.length) {
      const sec = document.getElementById("life-periods-section");
      if (sec) sec.hidden = true;
      return;
    }

    container.innerHTML = "";
    periods.forEach((p) => {
      const card = document.createElement("div");
      card.className = "life-period-card card";
      card.style.cssText =
        "padding:12px 14px;border-radius:10px;border:1px solid var(--border-color);background:var(--bg-subtle);min-width:230px;";
      const startStr = p.start_date || p.start_year || "";
      const endStr = p.end_date || p.end_year || "Present";
      card.innerHTML = `
        <div style="font-size:11px;font-weight:700;color:#7e22ce;text-transform:uppercase;">${escapeHtml(p.period_type || "Chapter")}</div>
        <div style="font-size:13.5px;font-weight:700;color:var(--text-main);margin-top:2px;">${escapeHtml(p.name || p.city || "Location")}</div>
        ${p.role_title ? `<div style="font-size:12px;color:#334155;margin-top:2px;">${escapeHtml(p.role_title)}</div>` : ""}
        ${p.address ? `<div style="font-size:11px;color:var(--text-muted);margin-top:2px;">${escapeHtml(p.address)}</div>` : ""}
        <div style="font-size:11px;color:var(--text-muted);font-family:var(--font-mono);margin-top:5px;">${escapeHtml(String(startStr))} – ${escapeHtml(String(endStr))}</div>
      `;
      if (p.start_date && /^\d{4}-\d{2}-\d{2}/.test(String(p.start_date))) {
        card.style.cursor = "pointer";
        card.addEventListener("click", () => {
          appNav.jumpToTimelineDay(String(p.start_date).slice(0, 10), true, "places");
        });
      }
      container.appendChild(card);
    });
  } catch (err) {
    console.warn("Could not load life periods:", err);
  }
}

export async function loadPlaces(searchQuery = null) {
  const query = searchQuery !== null ? String(searchQuery).trim() : getGlobalSearchQuery();
  state.currentPlacesQuery = query;

  const grid = document.getElementById("places-grid-container");
  if (grid) {
    grid.innerHTML = `<div class="loading-spinner" style="grid-column:1/-1;"><i class="fa-solid fa-circle-notch fa-spin"></i> Loading Places Catalog...</div>`;
  }

  const lifeSec = document.getElementById("life-periods-section");
  if (lifeSec) {
    lifeSec.hidden = Boolean(query);
    lifeSec.style.display = query ? "none" : "";
  }

  loadAllPlacesMap(query);
  if (!query) {
    loadLifePeriods();
  }

  const params = new URLSearchParams();
  params.set("limit", "120");
  if (query) params.set("q", query);
  if (state.currentCategory && state.currentCategory !== "ALL") params.set("category", state.currentCategory);
  if (state.currentCity && state.currentCity !== "ALL") params.set("city", state.currentCity);
  if (state.currentEra && state.currentEra !== "ALL") params.set("era", state.currentEra);
  if (state.currentCadence && state.currentCadence !== "ALL") params.set("cadence", state.currentCadence);
  if (state.currentDwell && state.currentDwell !== "ALL") params.set("dwell", state.currentDwell);
  if (state.currentSort) params.set("sort", state.currentSort);
  if (state.reviewedOnly) params.set("reviewed_only", "true");

  try {
    const [placesRes, reviewsRes] = await Promise.all([
      fetchSlotJson("places-list", `/api/places?${params.toString()}`),
      state.reviewedOnly
        ? fetchSlotJson("places-reviews", `/api/reviews${query ? `?q=${encodeURIComponent(query)}` : ""}`)
        : Promise.resolve({ aborted: false, data: null }),
    ]);

    if (placesRes.aborted || !placesRes.data || placesRes.data.status !== "SUCCESS") return;
    const data = placesRes.data;

    if (Array.isArray(data.categories) && data.categories.length) {
      renderCategoryPills(data.categories);
    }
    if (Array.isArray(data.cities) && data.cities.length) {
      populateCitiesDropdown(data.cities);
    }

    const totalPlaces = data.total_count ?? data.count ?? (data.places || []).length;
    if (totalPlaces !== undefined) {
      setElText(
        "badge-places",
        totalPlaces >= 1000 ? `${(totalPlaces / 1000).toFixed(1)}k` : String(totalPlaces)
      );
    }

    const reviewsByPlaceId = new Map();
    for (const r of reviewsRes.data?.reviews || []) {
      if (r.place_id) reviewsByPlaceId.set(r.place_id, r);
    }

    const places = data.places || [];
    if (!grid) return;
    grid.innerHTML = "";

    if (!places.length) {
      grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1;"><p>No visited places match the current filters.</p></div>`;
      return;
    }

    places.forEach((p) => {
      const card = document.createElement("article");
      card.className = "place-card card";
      const catColor = CATEGORY_MAP_COLORS[p.category] || "#1a73e8";
      const iconCls = getPlaceIcon(p.name, p.category);
      const visits = Number(p.visit_count) || 0;
      const lastDate = p.last_visited ? String(p.last_visited).slice(0, 10) : "";
      const review = p.review || reviewsByPlaceId.get(p.place_id) || null;
      const rating = Number(p.rating || review?.rating || 0);
      const reviewComment = p.review_text || review?.comment || review?.review_text || "";
      const photos = Array.isArray(p.photos) ? p.photos : Array.isArray(review?.photos) ? review.photos : [];

      card.innerHTML = `
        <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:10px;">
          <div style="display:flex;align-items:flex-start;gap:10px;min-width:0;flex:1;">
            <div style="width:36px;height:36px;border-radius:10px;background:${catColor}1a;color:${catColor};display:flex;align-items:center;justify-content:center;font-size:15px;flex-shrink:0;">
              <i class="fa-solid ${iconCls}"></i>
            </div>
            <div style="min-width:0;flex:1;">
              <h4 class="place-card-title" style="margin:0;font-size:14px;font-weight:700;color:var(--text-main);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer;" title="${escapeHtml(p.name || "Place")}">${escapeHtml(p.name || "Place")}</h4>
              <div style="font-size:11.5px;color:var(--text-muted);margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escapeHtml(p.address || p.city || "")}">${escapeHtml(p.address || p.city || "Coordinates recorded")}</div>
            </div>
          </div>
          <button type="button" class="tag-badge btn-place-visits-count" style="background:rgba(26,115,232,0.12);color:#1a73e8;border:none;font-weight:700;font-size:11px;cursor:pointer;flex-shrink:0;" title="Inspect all ${visits} visits">
            ${visits} visit${visits === 1 ? "" : "s"}
          </button>
        </div>

        <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-top:8px;">
          ${p.category ? `<span class="tag-badge" style="font-size:10.5px;background:${catColor}18;color:${catColor};font-weight:600;">${escapeHtml(p.category)}</span>` : ""}
          ${p.city ? `<span class="tag-badge" style="font-size:10.5px;">${escapeHtml(p.city)}</span>` : ""}
          ${rating > 0 ? `<span style="font-size:11.5px;color:#b45309;font-weight:700;" title="Rated ${rating}/5">${escapeHtml(renderStars(rating))}</span>` : ""}
        </div>

        ${
          reviewComment
            ? `<div class="review-card" style="margin-top:8px;padding:8px 10px;border-radius:8px;background:var(--bg-subtle);border-left:3px solid #f59e0b;font-size:12px;color:var(--text-main);line-height:1.4;">
                "${escapeHtml(reviewComment)}"
              </div>`
            : ""
        }

        ${
          photos.length
            ? `<div style="display:flex;gap:6px;overflow-x:auto;margin-top:8px;">
                ${photos
                  .slice(0, 5)
                  .map((ph, idx) => {
                    const raw = typeof ph === "string" ? ph : ph.preview_url || ph.url || "";
                    return `<img src="${escapeHtml(getPhotoUrl(raw, "thumb"))}" alt="${escapeHtml(p.name || "Place")} photo" loading="lazy" decoding="async" data-hide-on-error="self" data-place-photo-idx="${idx}" style="width:52px;height:52px;object-fit:cover;border-radius:6px;cursor:pointer;border:1px solid var(--border-color);flex-shrink:0;">`;
                  })
                  .join("")}
              </div>`
            : ""
        }

        <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:10px;padding-top:8px;border-top:1px solid var(--border-subtle);">
          <span style="font-size:11px;color:var(--text-muted);font-family:var(--font-mono);">
            ${lastDate ? `Last: ${escapeHtml(lastDate)}` : ""}
          </span>
          <div style="display:flex;gap:6px;align-items:center;">
            <button type="button" class="btn btn-xs btn-secondary btn-place-edit" title="Edit place &amp; Place ID" style="padding:3px 8px;font-size:11px;">
              <i class="fa-solid fa-pen"></i>
            </button>
            ${
              p.google_maps_url
                ? `<a href="${safeHref(p.google_maps_url)}" target="_blank" rel="noopener noreferrer" class="btn btn-xs btn-secondary" title="Open in Google Maps" style="padding:3px 8px;font-size:11px;text-decoration:none;"><i class="fa-solid fa-arrow-up-right-from-square"></i></a>`
                : ""
            }
            ${
              lastDate
                ? `<button type="button" class="btn btn-xs btn-primary btn-place-jump" style="padding:3px 9px;font-size:11px;">
                    <i class="fa-solid fa-calendar-day"></i> Last Visit
                  </button>`
                : ""
            }
          </div>
        </div>
      `;

      card.querySelector(".place-card-title")?.addEventListener("click", () => {
        const lat = Number(p.latitude);
        const lng = Number(p.longitude);
        if (Number.isFinite(lat) && Number.isFinite(lng)) {
          panPlacesMapTo(lat, lng, 16);
        }
        appNav.openPlaceVisitsModal(p.place_id, p.name);
      });

      card.querySelector(".btn-place-visits-count")?.addEventListener("click", () => {
        appNav.openPlaceVisitsModal(p.place_id, p.name);
      });

      card.querySelector(".btn-place-edit")?.addEventListener("click", () => {
        appNav.openEditPlaceModal(p);
      });

      card.querySelector(".btn-place-jump")?.addEventListener("click", () => {
        if (lastDate) appNav.jumpToTimelineDay(lastDate, true, "places");
      });

      if (photos.length) {
        const photoUrls = photos
          .map((ph) => getPhotoUrl(typeof ph === "string" ? ph : ph.preview_url || ph.url || "", "orig"))
          .filter(Boolean);
        card.querySelectorAll("img[data-place-photo-idx]").forEach((imgEl) => {
          imgEl.addEventListener("click", () => {
            const idx = Number(imgEl.dataset.placePhotoIdx) || 0;
            appNav.openPhotoLightbox(photoUrls, idx, p.name || "Place", reviewComment);
          });
        });
      }

      grid.appendChild(card);
    });
  } catch (err) {
    console.error("Error loading places:", err);
    if (grid) {
      grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1;">Error loading places: ${escapeHtml(err.message)}</div>`;
    }
  }
}

export function initPlacesEvents() {
  const sortSelect = document.getElementById("places-sort-select");
  if (sortSelect) {
    state.currentSort = sortSelect.value || "visits";
    sortSelect.addEventListener("change", (e) => {
      state.currentSort = e.target.value;
      loadPlaces(getGlobalSearchQuery());
    });
  }

  document.getElementById("places-city-select")?.addEventListener("change", (e) => {
    state.currentCity = e.target.value;
    loadPlaces(getGlobalSearchQuery());
  });

  document.getElementById("places-era-select")?.addEventListener("change", (e) => {
    state.currentEra = e.target.value;
    loadPlaces(getGlobalSearchQuery());
  });

  document.getElementById("places-cadence-select")?.addEventListener("change", (e) => {
    state.currentCadence = e.target.value;
    loadPlaces(getGlobalSearchQuery());
  });

  document.getElementById("places-dwell-select")?.addEventListener("change", (e) => {
    state.currentDwell = e.target.value;
    loadPlaces(getGlobalSearchQuery());
  });

  document.getElementById("places-reviewed-only")?.addEventListener("change", (e) => {
    state.reviewedOnly = Boolean(e.target.checked);
    loadPlaces(getGlobalSearchQuery());
  });
}
