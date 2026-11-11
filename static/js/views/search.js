import { abortSlot, fetchSlotJson } from "../api.js";
import { escapeHtml, hidePopoverSafe, isIMEComposing, showPopoverSafe } from "../dom.js";
import { getPlaceIcon, panDayMapTo, panPlacesMapTo } from "../maps.js";
import { appNav, getGlobalSearchQuery, state, updateUrlQuery } from "../state.js";

export function initGlobalSearch() {
  const input = document.getElementById("global-search-input");
  const dropdown = document.getElementById("global-search-dropdown");
  const clearBtn = document.getElementById("global-search-clear");
  if (!input || !dropdown) return;

  let debounceTimer = null;
  let tabLiveSearchTimer = null;
  let selectedIdx = -1;
  let currentResults = [];

  function closeDropdown() {
    hidePopoverSafe(dropdown);
  }

  function openDropdown() {
    showPopoverSafe(dropdown);
  }

  window.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      input.focus();
      input.select();
    } else if (
      e.key === "/" &&
      document.activeElement?.tagName !== "INPUT" &&
      document.activeElement?.tagName !== "TEXTAREA" &&
      document.activeElement?.tagName !== "SELECT"
    ) {
      e.preventDefault();
      input.focus();
      input.select();
    }
  });

  function showSearchInPlacesList(q) {
    if (!q) return;
    closeDropdown();
    updateUrlQuery(q);
    state.currentPlacesQuery = q;
    state.currentCategory = "ALL";
    state.currentCity = "ALL";
    const citySelect = document.getElementById("places-city-select");
    if (citySelect) citySelect.value = "ALL";
    document.querySelectorAll("#category-pills-container .cat-pill").forEach((p) => {
      p.classList.toggle("active", p.getAttribute("data-cat") === "ALL");
    });
    appNav.switchTab("places");
    appNav.loadPlaces(q);
    input.value = q;
    if (clearBtn) clearBtn.style.display = "block";
  }

  function selectSearchResult(it) {
    closeDropdown();
    if (!it) return;

    if (it.type === "PERSON") {
      const searchQ = it.name || it.title;
      updateUrlQuery(searchQ);
      appNav.openPersonVisitsModal(searchQ);
      return;
    }

    if (it.type === "PERSON_VISIT" || it.type === "PHOTO_VISIT" || it.segment_id) {
      if (it.date) {
        appNav.jumpToTimelineDay(it.date, true, "search", it.segment_id);
        const lat = parseFloat(it.latitude);
        const lng = parseFloat(it.longitude);
        if (Number.isFinite(lat) && Number.isFinite(lng)) {
          panDayMapTo(lat, lng, 16.5);
        }
      }
      return;
    }

    if (it.type === "PLACE" || it.place_id) {
      const searchQ = getGlobalSearchQuery() || it.title;
      state.currentPlacesQuery = searchQ;
      appNav.switchTab("places");
      appNav.loadPlaces(searchQ);
      if (it.place_id) {
        appNav.openPlaceVisitsModal(it.place_id, it.title);
      }
      const lat = parseFloat(it.latitude);
      const lng = parseFloat(it.longitude);
      if (Number.isFinite(lat) && Number.isFinite(lng)) {
        panPlacesMapTo(lat, lng, 16);
      }
      return;
    }

    if (it.type === "CATEGORY") {
      appNav.switchTab("places");
      state.currentCategory = String(it.title || "").replace("Category: ", "").trim();
      appNav.loadPlaces("");
      return;
    }

    if (it.type === "LOCATION") {
      appNav.switchTab("trips");
      appNav.loadTrips(it.title, "ALL");
      return;
    }

    if (it.date) {
      appNav.jumpToTimelineDay(it.date, true, "search");
      const lat = parseFloat(it.latitude);
      const lng = parseFloat(it.longitude);
      if (Number.isFinite(lat) && Number.isFinite(lng)) {
        panDayMapTo(lat, lng, 16);
      }
    }
  }

  function renderSearchDropdown(results, query) {
    currentResults = results || [];
    selectedIdx = -1;

    if (!results || results.length === 0) {
      dropdown.innerHTML = `<div class="search-empty-state"><i class="fa-solid fa-magnifying-glass" style="margin-bottom:6px;font-size:16px;"></i><p>No matching places, people, or days found for "<strong>${escapeHtml(query)}</strong>"</p></div>`;
      openDropdown();
      return;
    }

    dropdown.innerHTML = "";
    const people = results.filter((r) => r.type === "PERSON");
    const personVisits = results.filter((r) => r.type === "PERSON_VISIT");
    const dates = results.filter((r) => r.type === "DATE");
    const months = results.filter((r) => r.type === "MONTH");
    const photoVisits = results.filter((r) => r.type === "PHOTO_VISIT");
    const places = results.filter((r) => r.type === "PLACE");
    const locations = results.filter((r) => r.type === "LOCATION");
    const categories = results.filter((r) => r.type === "CATEGORY");

    function appendGroup(title, items, icon) {
      if (!items.length) return;
      const header = document.createElement("div");
      header.className = "search-group-header";
      const titleSpan = document.createElement("span");
      titleSpan.innerHTML = `<i class="fa-solid ${icon}"></i> ${escapeHtml(title)} (${items.length})`;
      header.appendChild(titleSpan);

      if (title === "Places & POIs") {
        const actionBtn = document.createElement("button");
        actionBtn.type = "button";
        actionBtn.className = "search-group-action-btn";
        actionBtn.innerHTML = `Show in Places list <i class="fa-solid fa-arrow-right"></i>`;
        actionBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          showSearchInPlacesList(query);
        });
        header.appendChild(actionBtn);
      }

      if (title === "People & Contacts" && people.length > 0) {
        const personName = people[0].name || people[0].title;
        const actionBtn = document.createElement("button");
        actionBtn.type = "button";
        actionBtn.className = "search-group-action-btn";
        actionBtn.innerHTML = `All visits with ${escapeHtml(personName)} <i class="fa-solid fa-arrow-right"></i>`;
        actionBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          closeDropdown();
          updateUrlQuery(personName);
          appNav.openPersonVisitsModal(personName);
        });
        header.appendChild(actionBtn);
      }

      dropdown.appendChild(header);

      items.forEach((it) => {
        const itemEl = document.createElement("div");
        itemEl.className = "search-result-item";
        const catIcon = getPlaceIcon(it.title, it.category) || it.icon || "fa-location-dot";
        const hasThumb = it.preview_url || it.sha256;
        const thumbSrc = it.preview_url || `/api/photo?sha256=${encodeURIComponent(it.sha256 || "")}`;
        const thumbHtml = hasThumb
          ? `<div class="search-item-thumb-wrapper"><img src="${escapeHtml(thumbSrc)}" class="search-item-thumb" alt="" loading="lazy" decoding="async" data-fallback-icon="${escapeHtml(catIcon)}"></div>`
          : `<div class="search-item-icon"><i class="fa-solid ${escapeHtml(catIcon)}"></i></div>`;

        const scorePill = it.score
          ? `<span class="search-score-pill" title="Semantic Match: ${(it.score * 100).toFixed(0)}%"><i class="fa-solid fa-sparkles"></i> ${(it.score * 100).toFixed(0)}%</span>`
          : "";

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
            ${it.date ? `<span class="search-date-badge">${escapeHtml(it.date)}</span>` : ""}
            ${it.visit_count ? `<div style="font-size:10px;color:var(--text-dim);margin-top:2px;">${Number(it.visit_count)} visits</div>` : ""}
            ${it.photo_count ? `<div style="font-size:10px;color:var(--accent-blue);margin-top:2px;font-weight:600;"><i class="fa-solid fa-camera"></i> ${Number(it.photo_count)}</div>` : ""}
          </div>
        `;

        itemEl.addEventListener("click", () => {
          selectSearchResult(it);
        });

        dropdown.appendChild(itemEl);
      });
    }

    appendGroup("People & Contacts", people, "fa-user");
    appendGroup("Visits with Person", personVisits, "fa-user-group");
    appendGroup("Photo Moments & Visits", photoVisits, "fa-camera-retro");
    appendGroup("Days & Dates", dates, "fa-calendar-day");
    appendGroup("Months & Years", months, "fa-calendar-days");
    appendGroup("Places & POIs", places, "fa-location-dot");
    appendGroup("Countries & Cities", locations, "fa-globe");
    appendGroup("Categories", categories, "fa-tag");

    openDropdown();
  }

  async function executeSearchNow(q) {
    if (!q) return;
    clearTimeout(debounceTimer);
    closeDropdown();
    updateUrlQuery(q);

    const dMatch = q.match(/(\d{4})[/-](\d{1,2})[/-](\d{1,2})/);
    if (dMatch) {
      const dt = `${dMatch[1]}-${dMatch[2].padStart(2, "0")}-${dMatch[3].padStart(2, "0")}`;
      appNav.jumpToTimelineDay(dt, true, "search");
      return;
    }

    try {
      const { aborted, data } = await fetchSlotJson(
        "global-search",
        `/api/search?q=${encodeURIComponent(q)}&limit=25`
      );
      if (aborted || !data) return;
      const results = data.results || [];

      const dateMatch = results.find((r) => r.type === "DATE");
      if (dateMatch) {
        selectSearchResult(dateMatch);
        return;
      }

      const personMatch = results.find((r) => r.type === "PERSON");
      if (personMatch) {
        appNav.openPersonVisitsModal(personMatch.name || personMatch.title);
        return;
      }

      const personVisit = results.find((r) => r.type === "PERSON_VISIT");
      if (personVisit) {
        selectSearchResult(personVisit);
        return;
      }

      if (state.activeTab === "places") {
        state.currentCategory = "ALL";
        state.currentCity = "ALL";
        appNav.loadPlaces(q);
        return;
      }
      if (state.activeTab === "trips") {
        appNav.loadTrips(q, "ALL");
        return;
      }

      const photoVisit = results.find((r) => r.type === "PHOTO_VISIT");
      if (photoVisit) {
        selectSearchResult(photoVisit);
        return;
      }

      showSearchInPlacesList(q);
    } catch (err) {
      console.error("Execute search error:", err);
      showSearchInPlacesList(q);
    }
  }

  window.executeGlobalSearchNow = executeSearchNow;

  input.addEventListener("input", () => {
    const q = input.value.trim();
    updateUrlQuery(q);
    if (clearBtn) clearBtn.style.display = q ? "block" : "none";

    if (!q) {
      abortSlot("global-search");
      closeDropdown();
      dropdown.innerHTML = "";
      currentResults = [];
      if (state.activeTab === "places") appNav.loadPlaces("");
      else if (state.activeTab === "trips") appNav.loadTrips("", state.currentTripCountry);
      else if (state.activeTab === "fixes") appNav.loadFixProposals("");
      return;
    }

    if (state.activeTab === "places") {
      clearTimeout(tabLiveSearchTimer);
      tabLiveSearchTimer = setTimeout(() => appNav.loadPlaces(q), 220);
    } else if (state.activeTab === "trips") {
      clearTimeout(tabLiveSearchTimer);
      tabLiveSearchTimer = setTimeout(() => appNav.loadTrips(q, state.currentTripCountry), 220);
    } else if (state.activeTab === "fixes") {
      clearTimeout(tabLiveSearchTimer);
      tabLiveSearchTimer = setTimeout(() => appNav.loadFixProposals(q), 220);
    }

    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(async () => {
      try {
        const { aborted, data } = await fetchSlotJson(
          "global-search",
          `/api/search?q=${encodeURIComponent(q)}&limit=25`
        );
        if (!aborted && data && data.status === "SUCCESS") {
          renderSearchDropdown(data.results, q);
        }
      } catch (err) {
        console.error("Search fetch error:", err);
      }
    }, 140);
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

  input.addEventListener("keydown", async (e) => {
    if (isIMEComposing(e)) return;
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
      const q = input.value.trim();
      if (!q) return;
      if (selectedIdx >= 0 && selectedIdx < currentResults.length) {
        selectSearchResult(currentResults[selectedIdx]);
      } else {
        await executeSearchNow(q);
      }
    } else if (e.key === "Escape") {
      closeDropdown();
      input.blur();
    }
  });

  clearBtn?.addEventListener("click", () => {
    input.value = "";
    clearBtn.style.display = "none";
    abortSlot("global-search");
    closeDropdown();
    dropdown.innerHTML = "";
    updateUrlQuery("");
    input.focus();
    if (state.activeTab === "places") appNav.loadPlaces("");
    else if (state.activeTab === "trips") appNav.loadTrips("", state.currentTripCountry);
    else if (state.activeTab === "fixes") appNav.loadFixProposals("");
  });

  document.addEventListener("click", (e) => {
    if (!input.contains(e.target) && !dropdown.contains(e.target)) {
      closeDropdown();
    }
  });

  input.addEventListener("focus", () => {
    if (input.value.trim() && dropdown.children.length > 0) {
      openDropdown();
    }
  });
}
