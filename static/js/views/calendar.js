import { fetchSlotJson } from "../api.js";
import { escapeHtml } from "../dom.js";
import { appNav, state } from "../state.js";
import {
  formatActivityName,
  getLocalToday,
  getMinutesFromTimeStr,
  getWeekDateRange,
  stepDate,
} from "../time.js";

export function renderCalendarGrid(daysMap) {
  const gridContainer = document.getElementById("cal-days-grid");
  if (!gridContainer) return;

  let gridHtml = "";
  const dates = Object.keys(daysMap).sort();

  for (const dStr of dates) {
    const dayData = daysMap[dStr] || {};
    const dObj = new Date(`${dStr}T12:00:00Z`);
    const dow = dObj.toLocaleDateString("en-US", { weekday: "short", timeZone: "UTC" });
    const monthDay = dObj.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });

    const anomalyCount = (dayData.anomalies || []).length;
    const gapCount = (dayData.gaps || []).length;

    let badgeHtml = "";
    if (anomalyCount > 0) {
      badgeHtml += `<span class="pill-badge red" style="font-size:9.5px;padding:2px 5px;" title="${anomalyCount} anomalies detected">🚨 ${anomalyCount}</span> `;
    }
    if (gapCount > 0) {
      badgeHtml += `<span class="pill-badge yellow" style="font-size:9.5px;padding:2px 5px;" title="${gapCount} unaccounted gaps">⚠️ ${gapCount} gaps</span>`;
    }

    gridHtml += `
      <div class="day-column" data-date="${escapeHtml(dStr)}">
        <div class="day-column-header">
          <div class="day-header-dow">${escapeHtml(dow)}</div>
          <div class="day-header-date">${escapeHtml(monthDay)}</div>
          <div style="margin-top:2px;">${badgeHtml}</div>
        </div>
        <div class="day-column-body">
    `;

    for (const g of dayData.gaps || []) {
      if (!g.start_time || !g.end_time) continue;
      const sMin = getMinutesFromTimeStr(g.start_time);
      const topPct = ((sMin / 1440.0) * 100).toFixed(2);
      const durPct = Math.max(0.6, (g.duration_minutes / 1440.0) * 100).toFixed(2);

      gridHtml += `
        <div class="cal-gap-block" style="top:${topPct}%;height:${durPct}%;" title="${escapeHtml(`Unaccounted Gap: ${g.duration_minutes} min (${g.start_time.slice(11, 16)} - ${g.end_time.slice(11, 16)})`)}">
          ${g.duration_minutes >= 30 ? `⚠️ GAP: ${Math.round(g.duration_minutes)}m` : g.duration_minutes >= 15 ? `⚠️ ${Math.round(g.duration_minutes)}m` : ""}
        </div>
      `;
    }

    for (const s of dayData.segments || []) {
      if (!s.start_time) continue;
      const sMin = getMinutesFromTimeStr(s.start_time);
      const topPct = ((sMin / 1440.0) * 100).toFixed(2);
      const durPct = Math.max(1.0, ((s.duration_minutes || 15) / 1440.0) * 100).toFixed(2);

      let typeClass = "poi";
      let icon = "fa-location-dot";
      let title = s.place_name || "Place Visit";

      if (s.segment_type === "visit") {
        if (title.toLowerCase().includes("home") || (s.category && s.category.includes("Home"))) {
          typeClass = "home";
          icon = "fa-house";
        } else if (
          s.semantic_type === "TYPE_WORK" ||
          (s.category && (s.category.includes("Work") || s.category.includes("Education"))) ||
          /\b(office|workplace|campus|university|college|school)\b/i.test(title)
        ) {
          typeClass = "work";
          icon = "fa-briefcase";
        }
      } else if (s.segment_type === "activity") {
        typeClass = "activity";
        const act = s.activity_type || "TRAVEL";
        title = formatActivityName(act);
        if (act.includes("WALK") || act.includes("FOOT")) icon = "fa-person-walking";
        else if (act.includes("CYCL")) icon = "fa-bicycle";
        else if (act.includes("SUBWAY") || act.includes("METRO")) icon = "fa-train-subway";
        else if (act.includes("TRAM")) icon = "fa-train-tram";
        else if (act.includes("TRAIN")) icon = "fa-train";
        else if (act.includes("FLY")) icon = "fa-plane";
        else icon = "fa-car";
      }

      const isAnomaly = (dayData.anomalies || []).some((a) => a.segment_id === s.id);
      const anomalyClass = isAnomaly ? "anomaly" : "";
      const timeStr = `${(s.start_time || "").slice(11, 16)} – ${(s.end_time || "").slice(11, 16)}`;
      const showSubtitle = (s.duration_minutes || 0) >= 35;

      gridHtml += `
        <div class="cal-event-block ${typeClass} ${anomalyClass}" style="top:${topPct}%;height:${durPct}%;"
             data-seg-id="${escapeHtml(s.id)}" data-date="${escapeHtml(dStr)}"
             title="${escapeHtml(`${title} (${timeStr}, ${s.duration_minutes || 0}m)`)}">
          ${showSubtitle ? `<div class="cal-event-time">${escapeHtml(timeStr)}</div>` : ""}
          <div class="cal-event-title">
            <i class="fa-solid ${icon}"></i>
            <span>${isAnomaly ? "🚨 " : ""}${escapeHtml(title)}</span>
          </div>
        </div>
      `;
    }

    gridHtml += `
        </div>
      </div>
    `;
  }

  gridContainer.innerHTML = gridHtml;

  gridContainer.querySelectorAll(".cal-event-block").forEach((el) => {
    el.addEventListener("click", () => {
      const segId = el.getAttribute("data-seg-id");
      const targetDate = el.getAttribute("data-date");
      if (targetDate) {
        appNav.jumpToTimelineDay(targetDate, true, "calendar", segId || null);
      }
    });
  });

  gridContainer.querySelectorAll(".day-column-header").forEach((el) => {
    el.style.cursor = "pointer";
    el.addEventListener("click", () => {
      const parentCol = el.closest(".day-column");
      const targetDate = parentCol?.getAttribute("data-date");
      if (targetDate) {
        appNav.jumpToTimelineDay(targetDate, true, "calendar");
      }
    });
  });
}

export async function loadCalendarMatrix(customDate = null) {
  if (customDate) {
    state.calFocusDate = customDate;
  } else if (!state.calFocusDate) {
    state.calFocusDate = state.currentDate || getLocalToday();
  }

  const datePicker = document.getElementById("cal-date-picker");
  if (datePicker) datePicker.value = state.calFocusDate;

  const { startDate, endDate } = getWeekDateRange(state.calFocusDate);
  const rangeLabel = document.getElementById("cal-range-label");
  if (rangeLabel) {
    rangeLabel.textContent = `Week of ${startDate} to ${endDate}`;
  }

  const timeAxis = document.getElementById("cal-time-axis");
  if (timeAxis && !timeAxis.children.length) {
    let axisHtml = "";
    for (let h = 0; h < 24; h++) {
      axisHtml += `<div class="time-hour-label">${String(h).padStart(2, "0")}:00</div>`;
    }
    timeAxis.innerHTML = axisHtml;
  }

  const gridContainer = document.getElementById("cal-days-grid");
  if (gridContainer) {
    gridContainer.innerHTML =
      '<div class="loading-spinner" style="padding:40px;margin:auto;"><i class="fa-solid fa-circle-notch fa-spin"></i> Rendering Calendar Matrix...</div>';
  }

  try {
    const { aborted, data } = await fetchSlotJson(
      "calendar-range",
      `/api/calendar-range?start_date=${encodeURIComponent(startDate)}&end_date=${encodeURIComponent(endDate)}`
    );
    if (aborted) return;
    if (!data || data.status !== "SUCCESS" || !data.days) {
      if (gridContainer) gridContainer.innerHTML = '<div class="empty-state">Failed to load calendar data.</div>';
      return;
    }

    renderCalendarGrid(data.days);
  } catch (err) {
    console.error("Error loading calendar matrix:", err);
    if (gridContainer) {
      gridContainer.innerHTML = `<div class="empty-state">Error loading calendar matrix: ${escapeHtml(err.message)}</div>`;
    }
  }
}

export function initCalendarMatrixEvents() {
  document.getElementById("btn-cal-prev-week")?.addEventListener("click", () => {
    state.calFocusDate = stepDate(state.calFocusDate || state.currentDate || getLocalToday(), -7);
    loadCalendarMatrix();
  });

  document.getElementById("btn-cal-next-week")?.addEventListener("click", () => {
    state.calFocusDate = stepDate(state.calFocusDate || state.currentDate || getLocalToday(), 7);
    loadCalendarMatrix();
  });

  document.getElementById("cal-date-picker")?.addEventListener("change", (e) => {
    if (e.target.value) {
      state.calFocusDate = e.target.value;
      loadCalendarMatrix();
    }
  });

  document.querySelectorAll(".cal-jump-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".cal-jump-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      if (btn.id === "cal-jump-today-btn") {
        state.calFocusDate = getLocalToday();
        loadCalendarMatrix(state.calFocusDate);
        return;
      }
      const targetDate = btn.getAttribute("data-date");
      if (targetDate) {
        state.calFocusDate = targetDate;
        loadCalendarMatrix(targetDate);
      }
    });
  });

  window.loadCalendarMatrix = loadCalendarMatrix;
  window.renderCalendarGrid = renderCalendarGrid;
}
