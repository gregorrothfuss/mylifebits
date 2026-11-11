import { fetchSlotJson, postJson } from "../api.js";
import { escapeHtml, setElText } from "../dom.js";
import { appNav, invalidateClientCaches, state } from "../state.js";

let gmmStreamTimer = null;

export function pauseGMMStream() {
  if (gmmStreamTimer) {
    clearInterval(gmmStreamTimer);
    gmmStreamTimer = null;
  }
}

export function refreshGMMScreen() {
  if (document.hidden || !state.gmmPanelOpen || state.activeTab !== "timeline") return;
  const img = document.getElementById("gmm-screen-img");
  if (!img) return;
  img.src = `/api/device/screen?t=${Date.now()}`;
}

export function resumeGMMStreamIfEligible() {
  pauseGMMStream();
  const autoBox = document.getElementById("gmm-auto-refresh");
  if (!state.gmmPanelOpen || state.activeTab !== "timeline" || document.hidden) return;
  if (autoBox && !autoBox.checked) return;
  refreshGMMScreen();
  gmmStreamTimer = setInterval(() => {
    if (document.hidden || !state.gmmPanelOpen || state.activeTab !== "timeline") {
      pauseGMMStream();
      return;
    }
    refreshGMMScreen();
  }, 2200);
}

export async function sendGMMTouch(action, x, y = 0) {
  try {
    await postJson("/api/device/touch", { action, x, y });
    setTimeout(refreshGMMScreen, 220);
  } catch (err) {
    console.warn("GMM touch error:", err);
  }
}

export async function syncGMMDate(dateStr) {
  const target = dateStr || state.currentDate;
  setElText("gmm-active-date", target);
  try {
    await postJson("/api/device/intent-day", { date: target });
    setTimeout(refreshGMMScreen, 650);
  } catch (err) {
    console.warn("GMM intent-day error:", err);
  }
}

export async function loadGMMComparison(dateStr) {
  const target = dateStr || state.currentDate;
  setElText("gmm-active-date", target);
  const listEl = document.getElementById("gmm-comparison-list");
  if (!listEl) return;

  listEl.innerHTML = `<div class="loading-spinner"><i class="fa-solid fa-circle-notch fa-spin"></i> Loading comparison...</div>`;

  try {
    const { aborted, data } = await fetchSlotJson(
      "gmm-compare",
      `/api/device/compare-day?date=${encodeURIComponent(target)}`
    );
    if (aborted || !data || data.status !== "SUCCESS") {
      if (!aborted) {
        listEl.innerHTML = `<div class="empty-state">${escapeHtml(data?.error || "Device comparison unavailable.")}</div>`;
      }
      return;
    }

    const items = data.comparisons || data.items || [];
    const issueCount = items.filter((it) => it.status && it.status !== "MATCH").length;
    setElText("gmm-discrepancy-badge", `${issueCount} Issue${issueCount === 1 ? "" : "s"}`);

    if (!items.length) {
      listEl.innerHTML = `<div class="empty-state">No segments to compare for ${escapeHtml(target)}.</div>`;
      return;
    }

    listEl.innerHTML = "";
    items.forEach((comp) => {
      const card = document.createElement("div");
      card.className = "gmm-comp-card";
      const sSeg = comp.studio_segment || comp.studio || null;
      const gSeg = comp.device_segment || comp.gmm || null;
      const sLabel = sSeg ? sSeg.place_name || sSeg.activity_type || "Studio Segment" : "Missing in Studio";
      const gLabel = gSeg ? gSeg.place_name || gSeg.activity_type || "Device Segment" : "Missing on Device";
      const isMatch = comp.status === "MATCH";

      card.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
          <span class="pill-badge ${isMatch ? "green" : "red"}" style="font-size:10px;">${escapeHtml(comp.status || "DIFF")}</span>
          ${sSeg ? `<button type="button" class="btn btn-xs btn-secondary btn-gmm-edit-studio" style="padding:2px 8px;font-size:11px;"><i class="fa-solid fa-pen"></i> Edit Studio</button>` : ""}
        </div>
        <div style="font-size:12px;color:#0f172a;"><strong>Studio:</strong> ${escapeHtml(sLabel)}</div>
        <div style="font-size:12px;color:#334155;margin-top:2px;"><strong>Device:</strong> ${escapeHtml(gLabel)}</div>
        ${comp.diff_details ? `<div style="font-size:11px;color:#475569;margin-top:4px;">${escapeHtml(comp.diff_details)}</div>` : ""}
        ${
          !isMatch && comp.conflict_id
            ? `<div style="display:flex;gap:6px;margin-top:8px;">
                <button type="button" class="btn btn-xs btn-primary btn-keep-studio" style="font-size:11px;">Keep Studio</button>
                <button type="button" class="btn btn-xs btn-secondary btn-keep-device" style="font-size:11px;">Adopt Device</button>
              </div>`
            : ""
        }
      `;

      if (sSeg) {
        card.querySelector(".btn-gmm-edit-studio")?.addEventListener("click", () => {
          appNav.openEditSegmentModal(sSeg);
        });
      }

      if (!isMatch && comp.conflict_id) {
        const resolve = async (resolution) => {
          await postJson("/api/device/resolve-conflict", {
            conflict_id: comp.conflict_id,
            date: target,
            resolution,
          });
          invalidateClientCaches();
          await appNav.loadDay(target, false);
          await loadGMMComparison(target);
        };
        card.querySelector(".btn-keep-studio")?.addEventListener("click", () => resolve("studio"));
        card.querySelector(".btn-keep-device")?.addEventListener("click", () => resolve("device"));
      }

      listEl.appendChild(card);
    });
  } catch (err) {
    listEl.innerHTML = `<div class="empty-state">Error comparing device day: ${escapeHtml(err.message)}</div>`;
  }
}

export async function openGMMComparator(dateStr) {
  const panel = document.getElementById("gmm-side-panel");
  if (!panel) return;
  state.gmmPanelOpen = true;
  panel.hidden = false;
  panel.style.display = "flex";

  try {
    const { data } = await fetchSlotJson("gmm-status", "/api/device/status");
    if (data && data.device_name) {
      setElText("gmm-device-name", data.device_name);
    }
  } catch {
    // Keep default device label
  }

  resumeGMMStreamIfEligible();
  await loadGMMComparison(dateStr || state.currentDate);
}

export function closeGMMComparator() {
  state.gmmPanelOpen = false;
  pauseGMMStream();
  const panel = document.getElementById("gmm-side-panel");
  if (panel) {
    panel.hidden = true;
    panel.style.display = "none";
  }
}

export function initGMMPanelEvents() {
  document.getElementById("btn-gmm-close")?.addEventListener("click", closeGMMComparator);
  document.getElementById("btn-gmm-sync-day")?.addEventListener("click", () => syncGMMDate(state.currentDate));
  document.getElementById("btn-gmm-refresh")?.addEventListener("click", refreshGMMScreen);
  document.getElementById("btn-gmm-key-back")?.addEventListener("click", () => sendGMMTouch("key", 4));
  document.getElementById("btn-gmm-key-home")?.addEventListener("click", () => sendGMMTouch("key", 3));
  document.getElementById("btn-gmm-open-cal")?.addEventListener("click", () => sendGMMTouch("tap", 480, 1315));
  document.getElementById("gmm-auto-refresh")?.addEventListener("change", resumeGMMStreamIfEligible);

  const screenBox = document.getElementById("gmm-screen-box");
  screenBox?.addEventListener("click", (e) => {
    const rect = screenBox.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const devX = Math.round(((e.clientX - rect.left) / rect.width) * 1080);
    const devY = Math.round(((e.clientY - rect.top) / rect.height) * 2400);
    sendGMMTouch("tap", devX, devY);
  });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) pauseGMMStream();
    else resumeGMMStreamIfEligible();
  });
}
