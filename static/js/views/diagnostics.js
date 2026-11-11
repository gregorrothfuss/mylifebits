import { fetchSlotJson } from "../api.js";
import { escapeHtml, setElText } from "../dom.js";
import { appNav, state } from "../state.js";
import { format24hTime } from "../time.js";

let cachedOutliers = [];

export async function loadDiagnosticsGaps() {
  const tbody = document.getElementById("gaps-table-body");
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="8" class="text-center">Loading gaps...</td></tr>`;

  const minHours = Number(document.getElementById("gap-filter-duration")?.value || 0);
  const minMinutes = minHours > 0 ? Math.round(minHours * 60) : 15;

  try {
    const { aborted, data } = await fetchSlotJson(
      "diag-gaps",
      `/api/diagnostics/gaps?min_minutes=${minMinutes}&limit=200`
    );
    if (aborted || !data || data.status !== "SUCCESS") return;

    const gaps = data.gaps || [];
    if (data.total_count !== undefined || gaps.length) {
      setElText("diag-post-gaps", (data.total_count ?? gaps.length).toLocaleString());
    }

    if (!gaps.length) {
      tbody.innerHTML = `<tr><td colspan="8" class="text-center">No timeline gaps matching filter.</td></tr>`;
      return;
    }

    tbody.innerHTML = "";
    gaps.forEach((g) => {
      const tr = document.createElement("tr");
      const dateStr = g.date || String(g.start_time || "").slice(0, 10);
      const durMin = Math.round(Number(g.duration_minutes) || 0);
      const durStr = durMin >= 60 ? `${Math.floor(durMin / 60)}h ${durMin % 60}m` : `${durMin}m`;
      const distKm = g.jump_meters ? `${(Number(g.jump_meters) / 1000).toFixed(1)} km` : "0.0 km";

      tr.innerHTML = `
        <td style="font-family:var(--font-mono);color:#0f172a;font-weight:600;">${escapeHtml(dateStr)}</td>
        <td style="color:#b91c1c;font-weight:700;">${escapeHtml(durStr)}</td>
        <td style="font-family:var(--font-mono);color:#334155;">${escapeHtml(format24hTime(g.start_time))} – ${escapeHtml(format24hTime(g.end_time))}</td>
        <td style="color:#334155;">${escapeHtml(g.prev_place_name || "Unknown")}</td>
        <td style="color:#334155;">${escapeHtml(g.next_place_name || "Unknown")}</td>
        <td style="font-family:var(--font-mono);color:#475569;">${escapeHtml(distKm)}</td>
        <td style="font-family:var(--font-mono);color:#475569;">${Number(g.raw_pings || 0)}</td>
        <td><button type="button" class="btn btn-xs btn-primary btn-inspect-gap">Inspect</button></td>
      `;
      tr.querySelector(".btn-inspect-gap")?.addEventListener("click", () => {
        if (dateStr) appNav.jumpToTimelineDay(dateStr, true, "diagnostics");
      });
      tbody.appendChild(tr);
    });
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" class="text-center">Error loading gaps: ${escapeHtml(err.message)}</td></tr>`;
  }
}

export async function loadDiagnosticsAnomalies() {
  const tbody = document.getElementById("speed-table-body");
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="7" class="text-center">Loading speed anomalies...</td></tr>`;

  try {
    const { aborted, data } = await fetchSlotJson("diag-anomalies", "/api/diagnostics/anomalies?limit=200");
    if (aborted || !data || data.status !== "SUCCESS") return;

    const anomalies = data.anomalies || [];
    setElText("diag-speed-outliers", (data.total_count ?? anomalies.length).toLocaleString());

    if (!anomalies.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="text-center">Zero physical velocity anomalies detected.</td></tr>`;
      return;
    }

    tbody.innerHTML = "";
    anomalies.forEach((a) => {
      const tr = document.createElement("tr");
      const dateStr = a.date || String(a.start_time || "").slice(0, 10);
      const speedKmh = Number(a.speed_kmh || 0).toFixed(1);
      const distKm = ((Number(a.distance_meters) || 0) / 1000).toFixed(1);
      const durMin = Math.round(Number(a.duration_minutes) || 0);

      tr.innerHTML = `
        <td style="font-family:var(--font-mono);color:#0f172a;font-weight:600;">${escapeHtml(dateStr)}</td>
        <td style="color:#334155;">${escapeHtml(a.activity_type || "UNKNOWN")}</td>
        <td style="color:#b91c1c;font-weight:700;font-family:var(--font-mono);">${escapeHtml(speedKmh)} km/h</td>
        <td style="font-family:var(--font-mono);color:#334155;">${escapeHtml(distKm)} km</td>
        <td style="font-family:var(--font-mono);color:#475569;">${durMin}m</td>
        <td style="color:#334155;">${escapeHtml(a.description || a.reason || "")}</td>
        <td><button type="button" class="btn btn-xs btn-primary btn-inspect-anom">Inspect</button></td>
      `;
      tr.querySelector(".btn-inspect-anom")?.addEventListener("click", () => {
        if (dateStr) appNav.jumpToTimelineDay(dateStr, true, "diagnostics", a.segment_id || null);
      });
      tbody.appendChild(tr);
    });
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-center">Error loading anomalies: ${escapeHtml(err.message)}</td></tr>`;
  }
}

export async function loadDiagnosticsUnconfirmed() {
  const tbody = document.getElementById("unconf-table-body");
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="7" class="text-center">Loading unconfirmed places...</td></tr>`;

  try {
    const { aborted, data } = await fetchSlotJson("diag-unconfirmed", "/api/diagnostics/unconfirmed?limit=200");
    if (aborted || !data || data.status !== "SUCCESS") return;

    const rows = data.unconfirmed || data.visits || [];
    if (!rows.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="text-center">No unconfirmed visits remaining.</td></tr>`;
      return;
    }

    tbody.innerHTML = "";
    rows.forEach((u) => {
      const tr = document.createElement("tr");
      const dateStr = u.date || String(u.start_time || "").slice(0, 10);
      const probPct = u.probability ? `${Math.round(Number(u.probability) * 100)}%` : "n/a";
      tr.innerHTML = `
        <td style="font-family:var(--font-mono);color:#0f172a;font-weight:600;">${escapeHtml(dateStr)}</td>
        <td style="font-family:var(--font-mono);color:#334155;">${escapeHtml(format24hTime(u.start_time))}</td>
        <td style="font-family:var(--font-mono);font-size:11.5px;color:#334155;">${escapeHtml(u.place_id || u.place_name || "")}</td>
        <td style="color:#334155;">${escapeHtml(u.category || "")}</td>
        <td style="color:#475569;">${escapeHtml(u.city || "")}</td>
        <td style="font-family:var(--font-mono);color:#b45309;font-weight:700;">${escapeHtml(probPct)}</td>
        <td><button type="button" class="btn btn-xs btn-primary btn-inspect-unconf">Inspect</button></td>
      `;
      tr.querySelector(".btn-inspect-unconf")?.addEventListener("click", () => {
        if (dateStr) appNav.jumpToTimelineDay(dateStr, true, "diagnostics", u.id || u.segment_id || null);
      });
      tbody.appendChild(tr);
    });
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-center">Error: ${escapeHtml(err.message)}</td></tr>`;
  }
}

export function renderOutliersTable() {
  const tbody = document.getElementById("outliers-table-body");
  if (!tbody) return;

  const filterType = document.getElementById("outlier-filter-type")?.value || "ALL";
  const rows =
    filterType === "ALL"
      ? cachedOutliers
      : cachedOutliers.filter((o) => o.anomaly_type === filterType || o.type === filterType);

  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-center">No matching GPS anomalies found.</td></tr>`;
    return;
  }

  tbody.innerHTML = "";
  rows.forEach((o) => {
    const tr = document.createElement("tr");
    const dateStr = o.date || String(o.timestamp || "").slice(0, 10);
    const timeStr = format24hTime(o.timestamp || "");
    const velStr = o.speed_kmh ? `${Number(o.speed_kmh).toFixed(0)} km/h` : "n/a";
    const coords =
      Number.isFinite(Number(o.latitude)) && Number.isFinite(Number(o.longitude))
        ? `${Number(o.latitude).toFixed(4)}, ${Number(o.longitude).toFixed(4)}`
        : "";

    tr.innerHTML = `
      <td style="font-family:var(--font-mono);color:#0f172a;font-weight:600;">${escapeHtml(dateStr)}</td>
      <td style="font-family:var(--font-mono);color:#334155;">${escapeHtml(timeStr)}</td>
      <td><span class="tag-badge" style="color:#b91c1c;background:#fef2f2;font-weight:700;">${escapeHtml(o.anomaly_type || o.type || "OUTLIER")}</span></td>
      <td style="font-family:var(--font-mono);color:#b91c1c;font-weight:700;">${escapeHtml(velStr)}</td>
      <td style="color:#334155;">${escapeHtml(o.reason || o.description || "")}</td>
      <td style="font-family:var(--font-mono);font-size:11.5px;color:#475569;">${escapeHtml(coords)}</td>
      <td><button type="button" class="btn btn-xs btn-primary btn-inspect-outlier">Inspect on Map</button></td>
    `;
    tr.querySelector(".btn-inspect-outlier")?.addEventListener("click", () => {
      state.showRawSignals = true;
      if (dateStr) appNav.jumpToTimelineDay(dateStr, true, "diagnostics");
    });
    tbody.appendChild(tr);
  });
}

export async function loadOutliersLeaderboard() {
  const tbody = document.getElementById("outliers-table-body");
  if (tbody) tbody.innerHTML = `<tr><td colspan="7" class="text-center">Loading GPS anomalies...</td></tr>`;

  try {
    const { aborted, data } = await fetchSlotJson("gps-outliers", "/api/outliers?limit=250");
    if (aborted || !data || data.status !== "SUCCESS") return;

    cachedOutliers = data.outliers || [];
    if (data.metrics) {
      if (data.metrics.teleport !== undefined) setElText("metric-teleport", data.metrics.teleport);
      if (data.metrics.velocity !== undefined) setElText("metric-velocity", data.metrics.velocity);
      if (data.metrics.multipath !== undefined) setElText("metric-multipath", data.metrics.multipath);
      if (data.metrics.scatter !== undefined) setElText("metric-scatter", data.metrics.scatter);
    }
    renderOutliersTable();
  } catch (err) {
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="7" class="text-center">Error loading outliers: ${escapeHtml(err.message)}</td></tr>`;
    }
  }
}

export function initDiagnosticsEvents() {
  document.getElementById("gap-filter-duration")?.addEventListener("change", loadDiagnosticsGaps);
  document.getElementById("btn-re-evaluate-outliers")?.addEventListener("click", loadOutliersLeaderboard);
  document.getElementById("outlier-filter-type")?.addEventListener("change", renderOutliersTable);

  document.querySelectorAll(".diag-subtabs .subtab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".diag-subtabs .subtab-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const target = btn.getAttribute("data-subtab");
      document.querySelectorAll("#tab-diagnostics .subtab-content").forEach((panel) => {
        panel.classList.remove("active");
      });
      if (target === "gaps-table") {
        document.getElementById("gaps-table-view")?.classList.add("active");
        loadDiagnosticsGaps();
      } else if (target === "speed-table") {
        document.getElementById("speed-table-view")?.classList.add("active");
        loadDiagnosticsAnomalies();
      } else if (target === "unconf-table") {
        document.getElementById("unconf-table-view")?.classList.add("active");
        loadDiagnosticsUnconfirmed();
      }
    });
  });
}
