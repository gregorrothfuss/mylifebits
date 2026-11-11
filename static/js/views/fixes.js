import { fetchSlotJson, postJson } from "../api.js";
import { escapeHtml, getPhotoUrl, isDialogOpen, safeHref, setElText } from "../dom.js";
import { registerAuxiliaryMap, unregisterAuxiliaryMap } from "../maps.js";
import { appNav, getGlobalSearchQuery, invalidateClientCaches, state } from "../state.js";
import { format24hTime } from "../time.js";

let cachedFixes = [];
let cachedFixCounts = { pending: 0, accepted: 0, rejected: 0, total: 0 };
let selectedFixIdx = 0;
let fixDetailMap = null;

function disposeFixDetailMap() {
  if (fixDetailMap) {
    unregisterAuxiliaryMap("fixes-mini-map");
    try {
      fixDetailMap.remove();
    } catch {
      // Ignore already disposed map
    }
    fixDetailMap = null;
  }
}

function renderFixesToolbar(sources = []) {
  const toolbar = document.getElementById("fixes-toolbar-container");
  if (!toolbar) return;

  const counts = cachedFixCounts;
  const statuses = [
    { key: "pending", label: `Pending (${counts.pending ?? 0})` },
    { key: "accepted", label: `Accepted (${counts.accepted ?? 0})` },
    { key: "rejected", label: `Rejected (${counts.rejected ?? 0})` },
  ];

  toolbar.innerHTML = `
    <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;">
      ${statuses
        .map(
          (st) => `
        <button type="button" class="cat-pill fix-status-pill ${state.currentFixesFilter === st.key ? "active" : ""}" data-status="${st.key}" style="font-size:11px;padding:4px 9px;">
          ${escapeHtml(st.label)}
        </button>`
        )
        .join("")}
    </div>
    <div style="display:flex;gap:6px;align-items:center;margin-top:8px;">
      <label for="fixes-source-select" class="visually-hidden">Evidence Source</label>
      <select id="fixes-source-select" aria-label="Filter fix proposals by source" style="flex:1;font-size:11.5px;padding:4px 8px;border-radius:6px;border:1px solid var(--border-color);background:var(--bg-subtle);color:var(--text-main);">
        <option value="ALL">All Evidence Sources</option>
        ${sources
          .map(
            (src) =>
              `<option value="${escapeHtml(src)}" ${state.currentFixesSource === src ? "selected" : ""}>${escapeHtml(src)}</option>`
          )
          .join("")}
      </select>
      ${
        state.currentFixesFilter === "pending" && cachedFixes.length > 0
          ? `<button type="button" id="btn-batch-apply-fixes" class="btn btn-xs btn-primary" title="Batch-apply high-confidence proposals">
              <i class="fa-solid fa-check-double"></i> Batch
            </button>`
          : ""
      }
      ${
        state.currentFixesFilter === "rejected" && cachedFixes.length > 0
          ? `<button type="button" id="btn-purge-rejected-fixes" class="btn btn-xs btn-secondary" title="Purge rejected proposals">
              <i class="fa-solid fa-broom"></i> Purge
            </button>`
          : ""
      }
    </div>
  `;

  toolbar.querySelectorAll(".fix-status-pill").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.currentFixesFilter = btn.getAttribute("data-status") || "pending";
      selectedFixIdx = 0;
      loadFixProposals(getGlobalSearchQuery());
    });
  });

  toolbar.querySelector("#fixes-source-select")?.addEventListener("change", (e) => {
    state.currentFixesSource = e.target.value;
    selectedFixIdx = 0;
    loadFixProposals(getGlobalSearchQuery());
  });

  toolbar.querySelector("#btn-batch-apply-fixes")?.addEventListener("click", async () => {
    const highConfIds = cachedFixes
      .filter((f) => Number(f.confidence || 0) >= 0.85)
      .map((f) => f.id);
    const targetIds = highConfIds.length ? highConfIds : cachedFixes.slice(0, 25).map((f) => f.id);
    if (!targetIds.length) return;
    if (!window.confirm(`Apply ${targetIds.length} candidate fix proposals?`)) return;
    try {
      const { data } = await postJson("/api/fixes/batch-apply", { ids: targetIds, min_confidence: 0.85 });
      if (data.status === "SUCCESS") {
        invalidateClientCaches();
        appNav.loadOverview();
        await loadFixProposals(getGlobalSearchQuery());
      } else {
        alert(data.error || "Batch apply failed.");
      }
    } catch (err) {
      alert(`Batch apply error: ${err.message}`);
    }
  });

  toolbar.querySelector("#btn-purge-rejected-fixes")?.addEventListener("click", async () => {
    if (!window.confirm("Remove rejected proposals from queue?")) return;
    try {
      await postJson("/api/fixes/purge", { status: "rejected" });
      await loadFixProposals(getGlobalSearchQuery());
    } catch (err) {
      alert(`Purge error: ${err.message}`);
    }
  });
}

function renderFixDetailPane(f) {
  const pane = document.getElementById("fixes-detail-pane");
  if (!pane) return;

  disposeFixDetailMap();

  if (!f) {
    pane.innerHTML = `
      <div class="fixes-detail-empty">
        <div style="width:64px;height:64px;border-radius:50%;background:var(--bg-card);display:flex;align-items:center;justify-content:center;margin:0 auto 16px;box-shadow:var(--shadow-sm);border:1px solid var(--border-subtle);">
          <i class="fa-solid fa-check-circle" style="font-size:24px;color:var(--accent-green);"></i>
        </div>
        <h3 style="color:var(--text-main);font-size:16px;font-weight:600;margin-bottom:6px;">No Proposals Selected</h3>
        <p style="color:var(--text-muted);font-size:13px;max-width:340px;line-height:1.5;">All proposals in this filter view have been reviewed.</p>
      </div>
    `;
    return;
  }

  state.selectedFixProposal = f;
  let details = {};
  if (f.details_json) {
    try {
      details = typeof f.details_json === "string" ? JSON.parse(f.details_json) : f.details_json;
    } catch {
      details = {};
    }
  }

  const venueName = f.proposed_place_name || details.place_name || details.name || "";
  const headline = venueName || f.description || f.fix_type || "Candidate Timeline Fix";
  const dateStr = f.date || details.date || String(f.start_time || details.start_time || "").slice(0, 10);
  const confPct = Math.round(Number(f.confidence ?? 0.8) * 100);
  const lat = Number(f.latitude ?? details.latitude ?? details.lat);
  const lng = Number(f.longitude ?? details.longitude ?? details.lng);
  const hasCoords = Number.isFinite(lat) && Number.isFinite(lng);
  const exifPhotosList = Array.isArray(details.photos) ? details.photos : [];
  const dupId = details.duplicate_place_id || details.duplicate_id || null;
  const primaryId = f.proposed_place_id || details.primary_place_id || details.place_id || null;

  pane.innerHTML = `
    <div style="padding:20px;display:flex;flex-direction:column;gap:16px;max-width:920px;">
      <div class="card" style="padding:18px 20px;">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap;">
          <div style="min-width:0;flex:1;">
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:6px;">
              <span class="tag-badge" style="background:#eff6ff;color:#1d4ed8;font-weight:700;">${escapeHtml(f.fix_type || "PROPOSAL")}</span>
              ${f.source ? `<span class="tag-badge">${escapeHtml(f.source)}</span>` : ""}
              <span class="tag-badge" style="background:#ecfdf5;color:#047857;font-weight:700;">${confPct}% confidence</span>
              ${dateStr ? `<span style="font-family:var(--font-mono);font-size:12px;color:#334155;">${escapeHtml(dateStr)}</span>` : ""}
            </div>
            <h3 style="margin:0;font-size:18px;font-weight:700;color:var(--text-main);">${escapeHtml(headline)}</h3>
            ${f.description && f.description !== headline ? `<p style="margin:6px 0 0 0;font-size:13px;color:#334155;line-height:1.5;">${escapeHtml(f.description)}</p>` : ""}
          </div>

          <div style="display:flex;gap:8px;flex-wrap:wrap;flex-shrink:0;">
            ${
              f.status === "pending" || !f.status
                ? `
              <button type="button" id="btn-fix-accept" class="btn btn-primary" style="background:var(--accent-green);border-color:var(--accent-green);">
                <i class="fa-solid fa-check"></i> Accept (A)
              </button>
              <button type="button" id="btn-fix-reject" class="btn btn-secondary" style="color:#b91c1c;border-color:#fecaca;background:#fef2f2;">
                <i class="fa-solid fa-xmark"></i> Reject (R)
              </button>`
                : `<span class="tag-badge" style="font-weight:700;text-transform:uppercase;">${escapeHtml(f.status)}</span>`
            }
            <button type="button" id="btn-fix-edit-place" class="btn btn-secondary">
              <i class="fa-solid fa-pen"></i> Edit (E)
            </button>
            ${
              dateStr
                ? `<button type="button" id="btn-fix-open-day" class="btn btn-secondary">
                    <i class="fa-solid fa-calendar-day"></i> View Day
                  </button>`
                : ""
            }
            ${
              primaryId && dupId
                ? `<button type="button" id="btn-fix-compare-dupes" class="btn btn-secondary">
                    <i class="fa-solid fa-code-compare"></i> Compare Places
                  </button>`
                : ""
            }
          </div>
        </div>

        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-top:14px;padding-top:12px;border-top:1px solid var(--border-subtle);font-size:12px;color:#334155;">
          ${
            f.start_time || details.start_time
              ? `<div><strong style="color:var(--text-muted);display:block;font-size:11px;">Window</strong>${escapeHtml(format24hTime(f.start_time || details.start_time))} – ${escapeHtml(format24hTime(f.end_time || details.end_time))}</div>`
              : ""
          }
          ${
            f.proposed_place_id || details.place_id
              ? `<div><strong style="color:var(--text-muted);display:block;font-size:11px;">Place ID</strong><span style="font-family:var(--font-mono);font-size:11px;">${escapeHtml(f.proposed_place_id || details.place_id)}</span></div>`
              : ""
          }
          ${
            details.address
              ? `<div><strong style="color:var(--text-muted);display:block;font-size:11px;">Address</strong>${escapeHtml(details.address)}</div>`
              : ""
          }
          ${
            details.evidence || f.evidence_summary
              ? `<div><strong style="color:var(--text-muted);display:block;font-size:11px;">Corroborating Evidence</strong>${escapeHtml(details.evidence || f.evidence_summary)}</div>`
              : ""
          }
        </div>
      </div>

      ${
        exifPhotosList.length
          ? `<div class="card" style="padding:16px;">
              <h4 style="margin:0 0 10px 0;font-size:13.5px;font-weight:700;color:var(--text-main);"><i class="fa-solid fa-camera" style="color:var(--accent-blue);"></i> Corroborating Photo Evidence (${exifPhotosList.length})</h4>
              <div style="display:flex;gap:8px;overflow-x:auto;">
                ${exifPhotosList
                  .map((p, idx) => {
                    const raw = p.preview_url || (p.sha256 ? `/api/photo?sha256=${encodeURIComponent(p.sha256)}` : p.id ? `/previews/${encodeURIComponent(p.id)}.webp` : "");
                    return `<img src="${escapeHtml(getPhotoUrl(raw, "thumb"))}" alt="${escapeHtml(p.filename || "Evidence photo")}" loading="lazy" decoding="async" data-hide-on-error="self" data-fix-photo-idx="${idx}" style="width:88px;height:88px;object-fit:cover;border-radius:8px;cursor:pointer;border:1px solid var(--border-color);flex-shrink:0;">`;
                  })
                  .join("")}
              </div>
            </div>`
          : ""
      }

      ${
        hasCoords
          ? `<div class="card" style="padding:12px;overflow:hidden;">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                <span style="font-size:12.5px;font-weight:700;color:var(--text-main);"><i class="fa-solid fa-map-pin" style="color:#ef4444;"></i> Spatial Context (${lat.toFixed(5)}, ${lng.toFixed(5)})</span>
                <a href="${safeHref(`https://www.google.com/maps/search/?api=1&query=${lat},${lng}`)}" target="_blank" rel="noopener noreferrer" style="font-size:11.5px;color:var(--accent-blue);text-decoration:none;font-weight:600;">Open in Google Maps <i class="fa-solid fa-arrow-up-right-from-square"></i></a>
              </div>
              <div id="fixes-mini-map" style="height:280px;width:100%;border-radius:8px;overflow:hidden;border:1px solid var(--border-color);"></div>
            </div>`
          : ""
      }
    </div>
  `;

  document.getElementById("btn-fix-accept")?.addEventListener("click", () => applyFixProposal(f.id));
  document.getElementById("btn-fix-reject")?.addEventListener("click", () => rejectFixProposal(f.id));
  document.getElementById("btn-fix-edit-place")?.addEventListener("click", () => {
    appNav.openEditPlaceModal(
      {
        place_id: f.proposed_place_id || details.place_id || "",
        name: venueName,
        address: details.address || "",
        latitude: hasCoords ? lat : "",
        longitude: hasCoords ? lng : "",
        category: details.category || "",
        city: details.city || "",
      },
      f.id
    );
  });
  document.getElementById("btn-fix-open-day")?.addEventListener("click", () => {
    if (dateStr) appNav.jumpToTimelineDay(dateStr, true, "fixes", f.target_id || null);
  });
  document.getElementById("btn-fix-compare-dupes")?.addEventListener("click", () => {
    if (primaryId && dupId) {
      appNav.openDuplicateComparison(primaryId, dupId, () => loadFixProposals(getGlobalSearchQuery()));
    }
  });

  if (exifPhotosList.length) {
    const lightboxUrls = exifPhotosList
      .map((x) =>
        getPhotoUrl(
          x.preview_url ||
            (x.sha256 ? `/api/photo?sha256=${encodeURIComponent(x.sha256)}` : x.id ? `/previews/${encodeURIComponent(x.id)}.webp` : ""),
          "orig"
        )
      )
      .filter(Boolean);
    pane.querySelectorAll("img[data-fix-photo-idx]").forEach((imgEl) => {
      imgEl.addEventListener("click", () => {
        const idx = Number(imgEl.dataset.fixPhotoIdx) || 0;
        const p = exifPhotosList[idx] || {};
        appNav.openPhotoLightbox(lightboxUrls, idx, venueName || headline, p.filename || "");
      });
    });
  }

  if (hasCoords && typeof L !== "undefined") {
    const mapContainer = document.getElementById("fixes-mini-map");
    if (mapContainer) {
      fixDetailMap = L.map("fixes-mini-map", { zoomControl: true }).setView([lat, lng], 16);
      registerAuxiliaryMap("fixes-mini-map", fixDetailMap);
      L.circleMarker([lat, lng], {
        radius: 9,
        color: "#ffffff",
        weight: 2,
        fillColor: "#2563eb",
        fillOpacity: 0.92,
      })
        .bindPopup(escapeHtml(headline))
        .addTo(fixDetailMap);
    }
  }
}

function renderFixesQueueList() {
  const listEl = document.getElementById("fixes-list-container");
  if (!listEl) return;

  setElText("fixes-queue-count", `${cachedFixes.length} item${cachedFixes.length === 1 ? "" : "s"}`);

  if (!cachedFixes.length) {
    listEl.innerHTML = `
      <div class="empty-state" style="padding:36px 16px;text-align:center;">
        <i class="fa-solid fa-check-double" style="font-size:22px;color:var(--accent-green);"></i>
        <p style="margin-top:8px;font-size:12.5px;color:var(--text-muted);">Zero proposals in this queue.</p>
      </div>
    `;
    renderFixDetailPane(null);
    return;
  }

  selectedFixIdx = Math.max(0, Math.min(selectedFixIdx, cachedFixes.length - 1));
  listEl.innerHTML = "";

  cachedFixes.forEach((f, idx) => {
    const item = document.createElement("div");
    item.className = `fix-queue-item ${idx === selectedFixIdx ? "selected active" : ""}`;
    item.style.cssText = `padding:10px 14px;border-bottom:1px solid var(--border-subtle);cursor:pointer;background:${idx === selectedFixIdx ? "rgba(26,115,232,0.08)" : "transparent"};border-left:3px solid ${idx === selectedFixIdx ? "#1a73e8" : "transparent"};`;

    const title = f.proposed_place_name || f.description || f.fix_type || `Proposal #${f.id}`;
    const dateStr = f.date || String(f.start_time || "").slice(0, 10);
    const confPct = Math.round(Number(f.confidence ?? 0.8) * 100);

    item.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;gap:6px;">
        <span style="font-size:10.5px;font-weight:700;color:#1d4ed8;text-transform:uppercase;">${escapeHtml(f.fix_type || "FIX")}</span>
        <span style="font-size:10.5px;font-family:var(--font-mono);color:var(--text-muted);">${escapeHtml(dateStr)} · ${confPct}%</span>
      </div>
      <div style="font-size:13px;font-weight:600;color:var(--text-main);margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escapeHtml(title)}">
        ${escapeHtml(title)}
      </div>
    `;
    item.addEventListener("click", () => {
      selectedFixIdx = idx;
      renderFixesQueueList();
    });
    listEl.appendChild(item);
  });

  renderFixDetailPane(cachedFixes[selectedFixIdx]);
}

export async function applyFixProposal(proposalId) {
  try {
    const { data } = await postJson("/api/fixes/apply", { id: proposalId, proposal_id: proposalId });
    if (data.status === "SUCCESS") {
      invalidateClientCaches();
      appNav.loadOverview();
      await loadFixProposals(getGlobalSearchQuery());
    } else {
      alert(data.error || "Could not apply proposal.");
    }
  } catch (err) {
    alert(`Error applying proposal: ${err.message}`);
  }
}

export async function rejectFixProposal(proposalId) {
  try {
    const { data } = await postJson("/api/fixes/reject", { id: proposalId, proposal_id: proposalId });
    if (data.status === "SUCCESS") {
      invalidateClientCaches();
      appNav.loadOverview();
      await loadFixProposals(getGlobalSearchQuery());
    } else {
      alert(data.error || "Could not reject proposal.");
    }
  } catch (err) {
    alert(`Error rejecting proposal: ${err.message}`);
  }
}

export async function loadFixProposals(searchQuery = null) {
  const q = searchQuery !== null ? String(searchQuery).trim() : getGlobalSearchQuery();
  const params = new URLSearchParams();
  params.set("status", state.currentFixesFilter || "pending");
  params.set("limit", "200");
  if (state.currentFixesSource && state.currentFixesSource !== "ALL") {
    params.set("source", state.currentFixesSource);
  }
  if (q) params.set("q", q);

  try {
    const { aborted, data } = await fetchSlotJson("fixes-list", `/api/fixes?${params.toString()}`);
    if (aborted || !data || data.status !== "SUCCESS") return;

    cachedFixes = data.fixes || data.proposals || [];
    cachedFixCounts = data.counts || {
      pending: cachedFixes.length,
      accepted: 0,
      rejected: 0,
      total: cachedFixes.length,
    };

    const pendingTotal = Number(cachedFixCounts.pending ?? 0);
    setElText(
      "badge-fixes",
      pendingTotal >= 1000 ? `${(pendingTotal / 1000).toFixed(1)}k` : String(pendingTotal)
    );

    const sources = Array.isArray(data.sources)
      ? data.sources
      : Array.from(new Set(cachedFixes.map((x) => x.source).filter(Boolean)));
    renderFixesToolbar(sources);
    renderFixesQueueList();
  } catch (err) {
    console.error("Error loading fix proposals:", err);
  }
}

export function initFixesEvents() {
  window.addEventListener("keydown", (e) => {
    if (state.activeTab !== "fixes") return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const activeTag = document.activeElement?.tagName || "";
    if (activeTag === "INPUT" || activeTag === "TEXTAREA" || activeTag === "SELECT") return;
    if (document.querySelector("dialog[open]") || isDialogOpen(document.getElementById("modal-container"))) return;
    if (!cachedFixes.length) return;

    const current = cachedFixes[selectedFixIdx];
    if (e.key === "ArrowDown") {
      e.preventDefault();
      selectedFixIdx = Math.min(cachedFixes.length - 1, selectedFixIdx + 1);
      renderFixesQueueList();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      selectedFixIdx = Math.max(0, selectedFixIdx - 1);
      renderFixesQueueList();
    } else if (e.key.toLowerCase() === "a" && current && state.currentFixesFilter === "pending") {
      e.preventDefault();
      applyFixProposal(current.id);
    } else if (e.key.toLowerCase() === "r" && current && state.currentFixesFilter === "pending") {
      e.preventDefault();
      rejectFixProposal(current.id);
    } else if (e.key.toLowerCase() === "e" && current) {
      e.preventDefault();
      document.getElementById("btn-fix-edit-place")?.click();
    }
  });
}
