import { fetchSlotJson, postJson } from "../api.js";
import {
  closeDialog,
  escapeHtml,
  formatPeopleList,
  getPhotoUrl,
  isDialogOpen,
  isIMEComposing,
  openDialog,
  safeHref,
  setElText,
} from "../dom.js";
import { applyBaseTileLayerToMap } from "../maps.js";
import { appNav, invalidateClientCaches, state, updateUrlQuery } from "../state.js";
import {
  extractIsoOffset,
  format24hTime,
  fromDateTimeLocalValue,
  toDateTimeLocalValue,
} from "../time.js";

const CANONICAL_ACTIVITY_TYPES = [
  "WALKING",
  "RUNNING",
  "HIKING",
  "CYCLING",
  "IN_PASSENGER_VEHICLE",
  "IN_TAXI",
  "MOTORCYCLING",
  "IN_BUS",
  "IN_SUBWAY",
  "IN_TRAIN",
  "IN_TRAM",
  "IN_FERRY",
  "FLYING",
  "BOATING",
  "KAYAKING",
  "SKIING",
  "SNOWBOARDING",
];

let currentLightboxPhotos = [];
let currentLightboxIndex = 0;
let dupeCompareMap = null;
let pendingDupeMergeCallback = null;

function disposeDupeMap() {
  if (dupeCompareMap) {
    try {
      dupeCompareMap.remove();
    } catch {
      // Ignore already disposed map
    }
    dupeCompareMap = null;
  }
}

export function openAddSegmentModal(defaultDate = null, defaultStart = null, defaultEnd = null) {
  const modal = document.getElementById("modal-container");
  const content = document.getElementById("modal-content");
  if (!modal || !content) return;

  const baseDate = defaultDate || state.currentDate;
  const startLocal = defaultStart ? toDateTimeLocalValue(defaultStart) : `${baseDate}T12:00`;
  const endLocal = defaultEnd ? toDateTimeLocalValue(defaultEnd) : `${baseDate}T13:00`;
  const preservedOffset = extractIsoOffset(defaultStart) || extractIsoOffset(defaultEnd) || "-04:00";

  setElText("modal-title", "Add Timeline Segment");
  content.innerHTML = `
    <form id="segment-create-form" style="display:flex;flex-direction:column;gap:12px;">
      <div class="form-group">
        <label for="seg-create-type" style="font-size:12px;font-weight:600;display:block;margin-bottom:4px;">Segment Type</label>
        <select id="seg-create-type" class="input-field" style="width:100%;padding:8px;border-radius:8px;border:1px solid var(--border-color);background:var(--bg-subtle);color:var(--text-main);">
          <option value="visit">Place Visit</option>
          <option value="activity">Movement / Activity</option>
        </select>
      </div>
      <div id="seg-create-visit-fields" style="display:flex;flex-direction:column;gap:10px;">
        <div>
          <label for="seg-create-place-name" style="font-size:12px;font-weight:600;display:block;margin-bottom:4px;">Place Name</label>
          <input type="text" id="seg-create-place-name" placeholder="e.g. Union Square Greenmarket" style="width:100%;padding:8px 10px;border-radius:8px;border:1px solid var(--border-color);background:var(--bg-subtle);color:var(--text-main);">
        </div>
        <div>
          <label for="seg-create-place-id" style="font-size:12px;font-weight:600;display:block;margin-bottom:4px;">Canonical Place ID (ChIJ...)</label>
          <input type="text" id="seg-create-place-id" placeholder="Optional ChIJ..." style="width:100%;padding:8px 10px;font-family:var(--font-mono);border-radius:8px;border:1px solid var(--border-color);background:var(--bg-subtle);color:var(--text-main);">
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
          <div>
            <label for="seg-create-lat" style="font-size:12px;font-weight:600;display:block;margin-bottom:4px;">Latitude</label>
            <input type="number" step="any" id="seg-create-lat" placeholder="40.7359" style="width:100%;padding:8px 10px;border-radius:8px;border:1px solid var(--border-color);background:var(--bg-subtle);color:var(--text-main);">
          </div>
          <div>
            <label for="seg-create-lng" style="font-size:12px;font-weight:600;display:block;margin-bottom:4px;">Longitude</label>
            <input type="number" step="any" id="seg-create-lng" placeholder="-73.9911" style="width:100%;padding:8px 10px;border-radius:8px;border:1px solid var(--border-color);background:var(--bg-subtle);color:var(--text-main);">
          </div>
        </div>
      </div>
      <div id="seg-create-activity-fields" hidden style="display:none;flex-direction:column;gap:10px;">
        <div>
          <label for="seg-create-act-type" style="font-size:12px;font-weight:600;display:block;margin-bottom:4px;">Activity Mode</label>
          <select id="seg-create-act-type" style="width:100%;padding:8px;border-radius:8px;border:1px solid var(--border-color);background:var(--bg-subtle);color:var(--text-main);">
            ${CANONICAL_ACTIVITY_TYPES.map((m) => `<option value="${m}">${m}</option>`).join("")}
          </select>
        </div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
        <div>
          <label for="seg-create-start" style="font-size:12px;font-weight:600;display:block;margin-bottom:4px;">Start Time (${escapeHtml(preservedOffset)})</label>
          <input type="datetime-local" id="seg-create-start" value="${escapeHtml(startLocal)}" required style="width:100%;padding:8px;border-radius:8px;border:1px solid var(--border-color);background:var(--bg-subtle);color:var(--text-main);">
        </div>
        <div>
          <label for="seg-create-end" style="font-size:12px;font-weight:600;display:block;margin-bottom:4px;">End Time (${escapeHtml(preservedOffset)})</label>
          <input type="datetime-local" id="seg-create-end" value="${escapeHtml(endLocal)}" required style="width:100%;padding:8px;border-radius:8px;border:1px solid var(--border-color);background:var(--bg-subtle);color:var(--text-main);">
        </div>
      </div>
      <div>
        <label for="seg-create-notes" style="font-size:12px;font-weight:600;display:block;margin-bottom:4px;">Notes</label>
        <textarea id="seg-create-notes" rows="2" placeholder="Optional context or companions..." style="width:100%;padding:8px 10px;border-radius:8px;border:1px solid var(--border-color);background:var(--bg-subtle);color:var(--text-main);"></textarea>
      </div>
      <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:6px;">
        <button type="button" id="btn-seg-create-cancel" class="btn btn-secondary">Cancel</button>
        <button type="submit" class="btn btn-primary">Create Segment</button>
      </div>
    </form>
  `;

  const typeSel = document.getElementById("seg-create-type");
  const visitFields = document.getElementById("seg-create-visit-fields");
  const actFields = document.getElementById("seg-create-activity-fields");
  typeSel?.addEventListener("change", () => {
    const isAct = typeSel.value === "activity";
    if (visitFields) {
      visitFields.hidden = isAct;
      visitFields.style.display = isAct ? "none" : "flex";
    }
    if (actFields) {
      actFields.hidden = !isAct;
      actFields.style.display = isAct ? "flex" : "none";
    }
  });

  document.getElementById("btn-seg-create-cancel")?.addEventListener("click", () => closeDialog(modal));
  document.getElementById("segment-create-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const segType = typeSel?.value || "visit";
    const startIso = fromDateTimeLocalValue(document.getElementById("seg-create-start")?.value || "", preservedOffset);
    const endIso = fromDateTimeLocalValue(document.getElementById("seg-create-end")?.value || "", preservedOffset);
    const payload = {
      segment_type: segType,
      start_time: startIso,
      end_time: endIso,
      notes: document.getElementById("seg-create-notes")?.value?.trim() || "",
    };
    if (segType === "visit") {
      payload.place_name = document.getElementById("seg-create-place-name")?.value?.trim() || "Place Visit";
      payload.place_id = document.getElementById("seg-create-place-id")?.value?.trim() || null;
      const lat = parseFloat(document.getElementById("seg-create-lat")?.value || "");
      const lng = parseFloat(document.getElementById("seg-create-lng")?.value || "");
      if (Number.isFinite(lat)) payload.latitude = lat;
      if (Number.isFinite(lng)) payload.longitude = lng;
    } else {
      payload.activity_type = document.getElementById("seg-create-act-type")?.value || "WALKING";
    }

    try {
      const { data } = await postJson("/api/segments/create", payload);
      if (data.status === "SUCCESS") {
        closeDialog(modal);
        invalidateClientCaches();
        await appNav.loadDay(state.currentDate, false);
      } else {
        alert(data.error || data.message || "Failed to create segment.");
      }
    } catch (err) {
      alert(`Failed to create segment: ${err.message}`);
    }
  });

  openDialog(modal);
}

export function openEditSegmentModal(seg) {
  if (!seg || typeof seg !== "object") return;
  const modal = document.getElementById("modal-container");
  const content = document.getElementById("modal-content");
  if (!modal || !content) return;

  const isVisit = seg.segment_type === "visit";
  const preservedStartOffset = extractIsoOffset(seg.start_time) || extractIsoOffset(seg.end_time) || "+00:00";
  const preservedEndOffset = extractIsoOffset(seg.end_time) || preservedStartOffset;
  const startLocal = toDateTimeLocalValue(seg.start_time);
  const endLocal = toDateTimeLocalValue(seg.end_time);

  setElText("modal-title", isVisit ? "Edit Timeline Visit" : "Edit Activity Segment");
  content.innerHTML = `
    <form id="segment-edit-form" style="display:flex;flex-direction:column;gap:12px;">
      ${
        isVisit
          ? `
        <div>
          <label for="seg-edit-place-name" style="font-size:12px;font-weight:600;display:block;margin-bottom:4px;">Place Name</label>
          <input type="text" id="seg-edit-place-name" value="${escapeHtml(seg.place_name || "")}" style="width:100%;padding:8px 10px;border-radius:8px;border:1px solid var(--border-color);background:var(--bg-subtle);color:var(--text-main);">
        </div>
        <div>
          <label for="seg-edit-place-id" style="font-size:12px;font-weight:600;display:block;margin-bottom:4px;">Place ID</label>
          <input type="text" id="seg-edit-place-id" value="${escapeHtml(seg.place_id || "")}" style="width:100%;padding:8px 10px;font-family:var(--font-mono);border-radius:8px;border:1px solid var(--border-color);background:var(--bg-subtle);color:var(--text-main);">
        </div>
      `
          : `
        <div>
          <label for="seg-edit-act-type" style="font-size:12px;font-weight:600;display:block;margin-bottom:4px;">Activity Type</label>
          <select id="seg-edit-act-type" style="width:100%;padding:8px;border-radius:8px;border:1px solid var(--border-color);background:var(--bg-subtle);color:var(--text-main);">
            ${CANONICAL_ACTIVITY_TYPES.map(
              (m) => `<option value="${m}" ${seg.activity_type === m ? "selected" : ""}>${m}</option>`
            ).join("")}
          </select>
        </div>
      `
      }
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
        <div>
          <label for="seg-edit-start" style="font-size:12px;font-weight:600;display:block;margin-bottom:4px;">Start (${escapeHtml(preservedStartOffset)})</label>
          <input type="datetime-local" id="seg-edit-start" value="${escapeHtml(startLocal)}" required style="width:100%;padding:8px;border-radius:8px;border:1px solid var(--border-color);background:var(--bg-subtle);color:var(--text-main);">
        </div>
        <div>
          <label for="seg-edit-end" style="font-size:12px;font-weight:600;display:block;margin-bottom:4px;">End (${escapeHtml(preservedEndOffset)})</label>
          <input type="datetime-local" id="seg-edit-end" value="${escapeHtml(endLocal)}" required style="width:100%;padding:8px;border-radius:8px;border:1px solid var(--border-color);background:var(--bg-subtle);color:var(--text-main);">
        </div>
      </div>
      <div>
        <label for="seg-edit-with-people" style="font-size:12px;font-weight:600;display:block;margin-bottom:4px;">Companions</label>
        <input type="text" id="seg-edit-with-people" value="${escapeHtml(formatPeopleList(seg.with_people))}" placeholder="Comma-separated names" style="width:100%;padding:8px 10px;border-radius:8px;border:1px solid var(--border-color);background:var(--bg-subtle);color:var(--text-main);">
      </div>
      <div>
        <label for="seg-edit-notes" style="font-size:12px;font-weight:600;display:block;margin-bottom:4px;">Notes</label>
        <textarea id="seg-edit-notes" rows="3" style="width:100%;padding:8px 10px;border-radius:8px;border:1px solid var(--border-color);background:var(--bg-subtle);color:var(--text-main);">${escapeHtml(seg.notes || "")}</textarea>
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-top:8px;">
        <button type="button" id="btn-seg-delete" class="btn btn-secondary" style="color:#b91c1c;border-color:#fecaca;background:#fef2f2;">
          <i class="fa-solid fa-trash"></i> Delete Segment
        </button>
        <div style="display:flex;gap:8px;">
          <button type="button" id="btn-seg-edit-cancel" class="btn btn-secondary">Cancel</button>
          <button type="submit" class="btn btn-primary">Save Changes</button>
        </div>
      </div>
    </form>
  `;

  document.getElementById("btn-seg-edit-cancel")?.addEventListener("click", () => closeDialog(modal));

  document.getElementById("btn-seg-delete")?.addEventListener("click", async () => {
    if (!window.confirm("Delete this timeline segment?")) return;
    try {
      const { data } = await postJson("/api/segments/delete", { id: seg.id, segment_id: seg.id });
      if (data.status === "SUCCESS") {
        closeDialog(modal);
        invalidateClientCaches();
        await appNav.loadDay(state.currentDate, false);
      } else {
        alert(data.error || "Failed to delete segment.");
      }
    } catch (err) {
      alert(`Error deleting segment: ${err.message}`);
    }
  });

  document.getElementById("segment-edit-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const startVal = document.getElementById("seg-edit-start")?.value || "";
    const endVal = document.getElementById("seg-edit-end")?.value || "";
    const payload = {
      id: seg.id,
      segment_id: seg.id,
      start_time: fromDateTimeLocalValue(startVal, preservedStartOffset),
      end_time: fromDateTimeLocalValue(endVal, preservedEndOffset),
      with_people: document.getElementById("seg-edit-with-people")?.value?.trim() || "",
      notes: document.getElementById("seg-edit-notes")?.value?.trim() || "",
    };
    if (isVisit) {
      payload.place_name = document.getElementById("seg-edit-place-name")?.value?.trim() || seg.place_name;
      payload.place_id = document.getElementById("seg-edit-place-id")?.value?.trim() || seg.place_id;
    } else {
      payload.activity_type = document.getElementById("seg-edit-act-type")?.value || seg.activity_type;
    }

    try {
      const { data } = await postJson("/api/segments/update", payload);
      if (data.status === "SUCCESS") {
        closeDialog(modal);
        invalidateClientCaches();
        await appNav.loadDay(state.currentDate, false);
      } else {
        alert(data.error || "Failed to update segment.");
      }
    } catch (err) {
      alert(`Error updating segment: ${err.message}`);
    }
  });

  openDialog(modal);
}

export async function triggerReinferDay() {
  const modal = document.getElementById("modal-container");
  const content = document.getElementById("modal-content");
  if (!modal || !content) return;

  setElText("modal-title", `Re-Infer Day (${state.currentDate})`);
  content.innerHTML = `<div class="loading-spinner" style="padding:24px;"><i class="fa-solid fa-circle-notch fa-spin"></i> Running multi-source physics &amp; evidence re-inference...</div>`;
  openDialog(modal);

  try {
    const { data } = await postJson("/api/reinfer-day", { date: state.currentDate });
    if (data.status !== "SUCCESS") {
      content.innerHTML = `<div class="empty-state" style="color:#b91c1c;">${escapeHtml(data.error || data.message || "Re-inference failed.")}</div>`;
      return;
    }

    const report = data.report || data;
    const candidateVisits = report.candidate_visits || report.visits || [];
    content.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:12px;color:var(--text-main);">
        <div style="padding:12px;border-radius:8px;background:var(--bg-subtle);border:1px solid var(--border-color);font-size:12.5px;color:#334155;">
          <strong>Quality Assessment:</strong> ${escapeHtml(report.quality_gain || report.message || "Evaluation complete")}
        </div>
        ${
          candidateVisits.length
            ? `<div style="display:flex;flex-direction:column;gap:6px;max-height:300px;overflow-y:auto;">
                ${candidateVisits
                  .map(
                    (v) => `
                  <div style="padding:8px 10px;border-radius:6px;border:1px solid var(--border-color);background:#ffffff;font-size:12px;color:#0f172a;">
                    <strong>${escapeHtml(v.place_name || "Candidate Visit")}</strong>
                    <div style="color:#475569;font-size:11px;">${escapeHtml(format24hTime(v.start_time))} – ${escapeHtml(format24hTime(v.end_time))}</div>
                  </div>`
                  )
                  .join("")}
              </div>`
            : `<div style="font-size:12px;color:#475569;">No new missing visits required insertion for ${escapeHtml(state.currentDate)}.</div>`
        }
        <div style="display:flex;justify-content:flex-end;">
          <button type="button" id="btn-reinfer-done" class="btn btn-primary">Done</button>
        </div>
      </div>
    `;
    document.getElementById("btn-reinfer-done")?.addEventListener("click", () => closeDialog(modal));
    invalidateClientCaches();
    await appNav.loadDay(state.currentDate, false);
  } catch (err) {
    content.innerHTML = `<div class="empty-state" style="color:#b91c1c;">Error: ${escapeHtml(err.message)}</div>`;
  }
}

function updateLightboxView() {
  const modal = document.getElementById("photo-lightbox-modal");
  if (!modal || !currentLightboxPhotos.length) return;

  const img = document.getElementById("lightbox-img");
  const titleEl = document.getElementById("lightbox-place-title");
  const textEl = document.getElementById("lightbox-review-text");
  const counterEl = document.getElementById("lightbox-counter");
  const prevBtn = document.getElementById("lightbox-prev-btn");
  const nextBtn = document.getElementById("lightbox-next-btn");

  const entry = currentLightboxPhotos[currentLightboxIndex];
  const rawUrl = typeof entry === "string" ? entry : entry?.url || "";
  if (img) {
    img.src = getPhotoUrl(rawUrl, "orig");
    img.setAttribute("referrerpolicy", "no-referrer");
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

export function openPhotoLightbox(photoUrlsOrObj, initialIdx = 0, placeTitle = "", reviewText = "") {
  let urls = [];
  let resolvedTitle = placeTitle;
  let resolvedCaption = reviewText;

  if (Array.isArray(photoUrlsOrObj)) {
    urls = photoUrlsOrObj.filter(Boolean);
  } else if (photoUrlsOrObj && typeof photoUrlsOrObj === "object" && photoUrlsOrObj.url) {
    urls = [photoUrlsOrObj.url];
    resolvedTitle = resolvedTitle || photoUrlsOrObj.caption || "Photo";
    resolvedCaption = resolvedCaption || photoUrlsOrObj.date || "";
  } else if (typeof photoUrlsOrObj === "string" && photoUrlsOrObj) {
    urls = [photoUrlsOrObj];
  }

  if (!urls.length) return;
  currentLightboxPhotos = urls;
  currentLightboxIndex = Math.max(0, Math.min(Number(initialIdx) || 0, urls.length - 1));

  const modal = document.getElementById("photo-lightbox-modal");
  if (!modal) return;
  modal.dataset.placeTitle = resolvedTitle || "Place";
  modal.dataset.reviewText = resolvedCaption || "";

  updateLightboxView();
  openDialog(modal);
}

export function lightboxPrev() {
  if (!currentLightboxPhotos.length) return;
  currentLightboxIndex = (currentLightboxIndex - 1 + currentLightboxPhotos.length) % currentLightboxPhotos.length;
  updateLightboxView();
}

export function lightboxNext() {
  if (!currentLightboxPhotos.length) return;
  currentLightboxIndex = (currentLightboxIndex + 1) % currentLightboxPhotos.length;
  updateLightboxView();
}

export async function openPlaceVisitsModal(placeId, placeName = "Place") {
  const modal = document.getElementById("place-visits-modal");
  const body = document.getElementById("place-visits-body");
  if (!modal || !body) return;

  setElText("place-visits-title", placeName || "Place Visits");
  setElText("place-visits-subtitle", "Loading recorded visits...");
  body.innerHTML = `<div class="loading-spinner" style="padding:24px;"><i class="fa-solid fa-circle-notch fa-spin"></i> Loading visits...</div>`;
  openDialog(modal);

  try {
    const { aborted, data } = await fetchSlotJson(
      "place-visits",
      `/api/places/visits?place_id=${encodeURIComponent(placeId)}`
    );
    if (aborted || !data || data.status !== "SUCCESS") {
      if (!aborted) {
        body.innerHTML = `<div class="empty-state">Could not load visits for this place.</div>`;
      }
      return;
    }

    const visits = data.visits || [];
    setElText(
      "place-visits-subtitle",
      `${visits.length} recorded visit${visits.length === 1 ? "" : "s"} across your timeline`
    );

    if (!visits.length) {
      body.innerHTML = `<div class="empty-state">No recorded visits found.</div>`;
      return;
    }

    body.innerHTML = "";
    const list = document.createElement("div");
    list.style.display = "flex";
    list.style.flexDirection = "column";
    list.style.gap = "8px";

    visits.forEach((v, idx) => {
      const dateStr = (v.date || String(v.start_time || "").slice(0, 10)).trim();
      const durMin = Math.round(Number(v.duration_minutes) || 0);
      const durStr = durMin >= 60 ? `${Math.floor(durMin / 60)}h ${durMin % 60}m` : `${durMin}m`;

      const row = document.createElement("div");
      row.style.cssText =
        "display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 14px;border-radius:10px;border:1px solid var(--border-color);background:var(--bg-subtle);";
      row.innerHTML = `
        <div style="min-width:0;flex:1;">
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
            <span style="font-family:var(--font-mono);font-size:11px;color:var(--text-muted);">#${visits.length - idx}</span>
            <strong style="font-size:13px;color:var(--text-main);">${escapeHtml(dateStr)}</strong>
            <span style="font-size:12px;color:#334155;font-family:var(--font-mono);">${escapeHtml(format24hTime(v.start_time))} – ${escapeHtml(format24hTime(v.end_time))}</span>
            <span class="tag-badge" style="font-size:11px;">${escapeHtml(durStr)}</span>
          </div>
          ${formatPeopleList(v.with_people) ? `<div style="font-size:11.5px;color:#6d28d9;margin-top:3px;"><i class="fa-solid fa-user-group"></i> ${escapeHtml(formatPeopleList(v.with_people))}</div>` : ""}
          ${v.notes ? `<div style="font-size:11.5px;color:var(--text-muted);margin-top:3px;">${escapeHtml(v.notes)}</div>` : ""}
        </div>
        <button type="button" class="btn btn-sm btn-primary btn-jump-visit-day" style="flex-shrink:0;">
          <i class="fa-solid fa-calendar-day"></i> Open Day
        </button>
      `;
      row.querySelector(".btn-jump-visit-day")?.addEventListener("click", () => {
        closeDialog(modal);
        if (dateStr) {
          appNav.jumpToTimelineDay(dateStr, true, "places", v.id || v.segment_id || null);
        }
      });
      list.appendChild(row);
    });

    body.appendChild(list);
  } catch (err) {
    body.innerHTML = `<div class="empty-state">Error loading visits: ${escapeHtml(err.message)}</div>`;
  }
}

export async function openPersonVisitsModal(personName) {
  const targetName = String(personName || "").trim();
  if (!targetName) return;

  const modal = document.getElementById("person-visits-modal");
  const body = document.getElementById("person-visits-body");
  const viewPlacesBtn = document.getElementById("btn-person-view-places");
  if (!modal || !body) return;

  setElText("person-visits-title", `Visits with ${targetName}`);
  setElText("person-visits-subtitle", "Loading shared timeline moments...");
  setElText("person-visits-footer-count", "");
  body.innerHTML = `<div class="loading-spinner" style="padding:24px;"><i class="fa-solid fa-circle-notch fa-spin"></i> Loading visits...</div>`;
  openDialog(modal);

  try {
    const { aborted, data } = await fetchSlotJson(
      "person-visits",
      `/api/people/visits?person=${encodeURIComponent(targetName)}`
    );
    if (aborted || !data || data.status !== "SUCCESS") {
      if (!aborted) {
        body.innerHTML = `<div class="empty-state">No visits found for ${escapeHtml(targetName)}.</div>`;
      }
      return;
    }

    const visits = data.visits || [];
    setElText("person-visits-subtitle", `${visits.length} shared visit${visits.length === 1 ? "" : "s"} recorded`);
    setElText("person-visits-footer-count", `${visits.length} total visits`);

    if (viewPlacesBtn) {
      viewPlacesBtn.style.display = visits.length > 0 ? "inline-flex" : "none";
      viewPlacesBtn.onclick = () => {
        closeDialog(modal);
        updateUrlQuery(targetName);
        const searchInput = document.getElementById("global-search-input");
        if (searchInput) searchInput.value = targetName;
        appNav.switchTab("places");
        appNav.loadPlaces(targetName);
      };
    }

    if (!visits.length) {
      body.innerHTML = `<div class="empty-state">No shared visits found for ${escapeHtml(targetName)}.</div>`;
      return;
    }

    body.innerHTML = "";
    const list = document.createElement("div");
    list.style.cssText = "display:flex;flex-direction:column;gap:8px;";

    visits.forEach((v) => {
      const dateStr = v.date || String(v.start_time || "").slice(0, 10);
      const row = document.createElement("div");
      row.style.cssText =
        "display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 14px;border-radius:10px;border:1px solid var(--border-color);background:var(--bg-subtle);";
      row.innerHTML = `
        <div style="min-width:0;flex:1;">
          <div style="font-weight:700;font-size:13.5px;color:var(--text-main);">${escapeHtml(v.place_name || "Place Visit")}</div>
          <div style="font-size:12px;color:#334155;margin-top:2px;">
            <strong>${escapeHtml(dateStr)}</strong> · ${escapeHtml(format24hTime(v.start_time))} – ${escapeHtml(format24hTime(v.end_time))}
            ${v.city ? ` · ${escapeHtml(v.city)}` : ""}
          </div>
          ${v.notes ? `<div style="font-size:11.5px;color:var(--text-muted);margin-top:3px;">${escapeHtml(v.notes)}</div>` : ""}
        </div>
        <button type="button" class="btn btn-sm btn-primary btn-jump-person-day" style="flex-shrink:0;">
          <i class="fa-solid fa-calendar-day"></i> Open Day
        </button>
      `;
      row.querySelector(".btn-jump-person-day")?.addEventListener("click", () => {
        closeDialog(modal);
        if (dateStr) {
          appNav.jumpToTimelineDay(dateStr, true, "search", v.id || v.segment_id || null);
        }
      });
      list.appendChild(row);
    });

    body.appendChild(list);
  } catch (err) {
    body.innerHTML = `<div class="empty-state">Error loading visits: ${escapeHtml(err.message)}</div>`;
  }
}

export async function openDuplicateComparison(primaryId, dupId, onMerged = null) {
  const modal = document.getElementById("duplicate-compare-modal");
  const cols = document.getElementById("dupe-compare-columns");
  if (!modal || !cols) return;

  pendingDupeMergeCallback = onMerged;
  disposeDupeMap();
  cols.innerHTML = `<div class="loading-spinner" style="grid-column:1/-1;padding:24px;"><i class="fa-solid fa-circle-notch fa-spin"></i> Comparing place records...</div>`;
  openDialog(modal);

  try {
    const url = `/api/places/compare?primary_id=${encodeURIComponent(primaryId)}&duplicate_id=${encodeURIComponent(dupId)}`;
    const { aborted, data } = await fetchSlotJson("dupe-compare", url);
    if (aborted || !data || data.status !== "SUCCESS") return;

    const p1 = data.primary || {};
    const p2 = data.duplicate || {};
    const distM = Math.round(Number(data.distance_meters) || 0);
    setElText("dupe-map-distance-badge", `${distM}m distance`);

    const renderPlaceCard = (p, badgeText, accent) => `
      <div class="card" style="padding:14px;border:1px solid ${accent};background:var(--bg-subtle);">
        <div style="font-size:11px;font-weight:700;color:${accent};text-transform:uppercase;margin-bottom:4px;">${escapeHtml(badgeText)}</div>
        <div style="font-size:15px;font-weight:700;color:var(--text-main);">${escapeHtml(p.name || "Place")}</div>
        <div style="font-size:12px;color:var(--text-muted);margin-top:3px;">${escapeHtml(p.address || "No address")}</div>
        <div style="font-size:11px;font-family:var(--font-mono);color:#334155;margin-top:6px;">ID: ${escapeHtml(p.place_id || "")}</div>
        <div style="font-size:12px;color:#334155;margin-top:4px;"><strong>${Number(p.visit_count) || 0}</strong> visits · ${escapeHtml(p.category || "Uncategorized")}</div>
      </div>
    `;
    cols.innerHTML =
      renderPlaceCard(p1, "Canonical Target", "#16a34a") +
      renderPlaceCard(p2, "Duplicate Candidate", "#d97706");

    if (typeof L !== "undefined") {
      const mapEl = document.getElementById("dupe-compare-map");
      if (mapEl) {
        mapEl.innerHTML = "";
        dupeCompareMap = L.map("dupe-compare-map", { zoomControl: true });
        applyBaseTileLayerToMap(dupeCompareMap, "dupe-compare-map", state.currentMapStyle);

        const pts = [];
        if (Number.isFinite(Number(p1.latitude)) && Number.isFinite(Number(p1.longitude))) {
          const c1 = [Number(p1.latitude), Number(p1.longitude)];
          L.circleMarker(c1, { radius: 8, color: "#ffffff", fillColor: "#16a34a", fillOpacity: 0.95 })
            .bindPopup(escapeHtml(`Canonical: ${p1.name || ""}`))
            .addTo(dupeCompareMap);
          pts.push(c1);
        }
        if (Number.isFinite(Number(p2.latitude)) && Number.isFinite(Number(p2.longitude))) {
          const c2 = [Number(p2.latitude), Number(p2.longitude)];
          L.circleMarker(c2, { radius: 8, color: "#ffffff", fillColor: "#d97706", fillOpacity: 0.95 })
            .bindPopup(escapeHtml(`Duplicate: ${p2.name || ""}`))
            .addTo(dupeCompareMap);
          pts.push(c2);
        }
        if (pts.length === 1) dupeCompareMap.setView(pts[0], 17);
        else if (pts.length > 1) dupeCompareMap.fitBounds(pts, { padding: [32, 32], maxZoom: 18 });
      }
    }

    const mergeBtn = document.getElementById("btn-merge-dupe-action");
    if (mergeBtn) {
      mergeBtn.onclick = async () => {
        mergeBtn.disabled = true;
        try {
          const { data: mRes } = await postJson("/api/places/merge", {
            primary_id: primaryId,
            duplicate_id: dupId,
          });
          if (mRes.status === "SUCCESS") {
            closeDialog(modal);
            invalidateClientCaches();
            if (typeof pendingDupeMergeCallback === "function") {
              pendingDupeMergeCallback(mRes);
            }
          } else {
            alert(mRes.error || "Merge failed.");
          }
        } catch (err) {
          alert(`Merge error: ${err.message}`);
        } finally {
          mergeBtn.disabled = false;
        }
      };
    }
  } catch (err) {
    cols.innerHTML = `<div class="empty-state" style="grid-column:1/-1;">Error comparing places: ${escapeHtml(err.message)}</div>`;
  }
}

export function openEditPlaceModal(placeObj = {}, proposalId = null) {
  const modal = document.getElementById("edit-place-modal");
  if (!modal) return;

  const setVal = (id, v) => {
    const el = document.getElementById(id);
    if (el) el.value = v !== undefined && v !== null ? String(v) : "";
  };

  setVal("edit-place-original-id", placeObj.place_id || "");
  setVal("edit-place-proposal-id", proposalId || "");
  setVal("edit-place-deeplink", "");
  setVal("edit-place-new-id", placeObj.place_id || "");
  setVal("edit-place-name", placeObj.name || placeObj.place_name || "");
  setVal("edit-place-address", placeObj.address || "");
  setVal("edit-place-lat", placeObj.latitude ?? "");
  setVal("edit-place-lng", placeObj.longitude ?? "");
  setVal("edit-place-city", placeObj.city || "");

  const catEl = document.getElementById("edit-place-category");
  if (catEl && placeObj.category) {
    catEl.value = placeObj.category;
  }

  const statusSpan = document.getElementById("deep-link-status");
  if (statusSpan) {
    statusSpan.style.display = "none";
    statusSpan.textContent = "";
  }

  openDialog(modal);
}

async function resolveGoogleMapsDeepLink() {
  const input = document.getElementById("edit-place-deeplink");
  const statusSpan = document.getElementById("deep-link-status");
  const urlVal = input?.value?.trim() || "";
  if (!urlVal) return;

  if (statusSpan) {
    statusSpan.style.display = "inline";
    statusSpan.style.color = "#1d4ed8";
    statusSpan.textContent = "Resolving link...";
  }

  try {
    const { data } = await postJson("/api/places/resolve-link", { url: urlVal });
    if (data.status === "SUCCESS") {
      if (data.place_id) document.getElementById("edit-place-new-id").value = data.place_id;
      if (data.name) document.getElementById("edit-place-name").value = data.name;
      if (data.address) document.getElementById("edit-place-address").value = data.address;
      if (data.latitude !== undefined && data.latitude !== null) {
        document.getElementById("edit-place-lat").value = data.latitude;
      }
      if (data.longitude !== undefined && data.longitude !== null) {
        document.getElementById("edit-place-lng").value = data.longitude;
      }
      if (data.city) document.getElementById("edit-place-city").value = data.city;
      if (statusSpan) {
        statusSpan.style.color = "#15803d";
        statusSpan.textContent = "Resolved!";
      }
    } else if (statusSpan) {
      statusSpan.style.color = "#b91c1c";
      statusSpan.textContent = data.error || "Could not extract metadata";
    }
  } catch (err) {
    if (statusSpan) {
      statusSpan.style.color = "#b91c1c";
      statusSpan.textContent = `Error: ${err.message}`;
    }
  }
}

export function initModalsEvents() {
  const genericModal = document.getElementById("modal-container");
  document.getElementById("modal-close-btn")?.addEventListener("click", () => closeDialog(genericModal));

  const lightboxModal = document.getElementById("photo-lightbox-modal");
  lightboxModal?.querySelector(".lightbox-close-btn")?.addEventListener("click", () => closeDialog(lightboxModal));
  document.getElementById("lightbox-prev-btn")?.addEventListener("click", lightboxPrev);
  document.getElementById("lightbox-next-btn")?.addEventListener("click", lightboxNext);

  window.addEventListener("keydown", (e) => {
    if (!isDialogOpen(lightboxModal)) return;
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      lightboxPrev();
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      lightboxNext();
    }
  });

  const dupeModal = document.getElementById("duplicate-compare-modal");
  dupeModal?.addEventListener("close", disposeDupeMap);
  document.getElementById("btn-close-dupe-modal")?.addEventListener("click", () => closeDialog(dupeModal));
  document.getElementById("btn-cancel-dupe-modal")?.addEventListener("click", () => closeDialog(dupeModal));

  const placeVisitsModal = document.getElementById("place-visits-modal");
  document.getElementById("btn-close-place-visits")?.addEventListener("click", () => closeDialog(placeVisitsModal));
  document.getElementById("btn-done-place-visits")?.addEventListener("click", () => closeDialog(placeVisitsModal));

  const personVisitsModal = document.getElementById("person-visits-modal");
  document.getElementById("btn-close-person-visits")?.addEventListener("click", () => closeDialog(personVisitsModal));
  document.getElementById("btn-done-person-visits")?.addEventListener("click", () => closeDialog(personVisitsModal));

  const editPlaceModal = document.getElementById("edit-place-modal");
  document.getElementById("btn-close-edit-place-modal")?.addEventListener("click", () => closeDialog(editPlaceModal));
  document.getElementById("btn-cancel-edit-place-modal")?.addEventListener("click", () => closeDialog(editPlaceModal));

  document.getElementById("btn-resolve-deeplink")?.addEventListener("click", resolveGoogleMapsDeepLink);
  document.getElementById("edit-place-deeplink")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      if (isIMEComposing(e)) return;
      e.preventDefault();
      resolveGoogleMapsDeepLink();
    }
  });

  document.getElementById("btn-save-edit-place")?.addEventListener("click", async () => {
    const originalId = document.getElementById("edit-place-original-id")?.value?.trim() || "";
    const proposalId = document.getElementById("edit-place-proposal-id")?.value?.trim() || "";
    const newPlaceId = document.getElementById("edit-place-new-id")?.value?.trim() || "";
    const name = document.getElementById("edit-place-name")?.value?.trim() || "";
    const address = document.getElementById("edit-place-address")?.value?.trim() || "";
    const lat = parseFloat(document.getElementById("edit-place-lat")?.value || "");
    const lng = parseFloat(document.getElementById("edit-place-lng")?.value || "");
    const category = document.getElementById("edit-place-category")?.value || "Other / POI";
    const city = document.getElementById("edit-place-city")?.value?.trim() || "";
    const relink = Boolean(document.getElementById("edit-place-relink")?.checked);

    const payload = {
      original_place_id: originalId,
      place_id: newPlaceId || originalId,
      new_place_id: newPlaceId || originalId,
      name,
      address,
      category,
      city,
      relink_segments: relink,
    };
    if (Number.isFinite(lat)) payload.latitude = lat;
    if (Number.isFinite(lng)) payload.longitude = lng;

    try {
      const endpoint = proposalId ? "/api/fixes/edit-and-apply" : "/api/places/edit-place";
      if (proposalId) payload.proposal_id = Number(proposalId);
      const { data } = await postJson(endpoint, payload);
      if (data.status === "SUCCESS") {
        closeDialog(editPlaceModal);
        invalidateClientCaches();
        if (state.activeTab === "places") {
          appNav.loadPlaces(state.currentPlacesQuery);
        } else if (state.activeTab === "fixes") {
          appNav.loadFixProposals();
        } else if (state.activeTab === "timeline") {
          appNav.loadDay(state.currentDate, false);
        }
      } else {
        alert(data.error || "Failed saving place updates.");
      }
    } catch (err) {
      alert(`Error saving place: ${err.message}`);
    }
  });

  window.openPhotoLightbox = openPhotoLightbox;
  window.safeHref = safeHref;
}
