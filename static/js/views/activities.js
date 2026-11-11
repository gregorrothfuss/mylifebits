import { fetchSlotJson } from "../api.js";
import { escapeHtml } from "../dom.js";
import { appNav, state } from "../state.js";

export async function loadActivitySummaries(period = null) {
  if (period) state.currentActivityPeriod = period;
  const heroGrid = document.getElementById("activities-hero-grid");
  const pillsContainer = document.getElementById("activities-period-pills-container");
  const bar = document.getElementById("mode-progress-bar");
  const cardsGrid = document.getElementById("mode-cards-grid");
  const nuggetsGrid = document.getElementById("activities-nuggets-container");
  const topPlacesEl = document.getElementById("activities-top-places");
  const rareModesEl = document.getElementById("activities-rare-modes");
  const subLabel = document.getElementById("activities-period-sub");

  if (heroGrid) {
    heroGrid.innerHTML =
      '<div class="loading-spinner" style="grid-column:1/-1;padding:30px;"><i class="fa-solid fa-circle-notch fa-spin"></i> Calculating Activity Summaries...</div>';
  }

  try {
    const { aborted, data } = await fetchSlotJson(
      "activities-summary",
      `/api/insights/activity-summaries?period=${encodeURIComponent(state.currentActivityPeriod)}`
    );
    if (aborted || !data || data.status !== "SUCCESS") return;

    if (subLabel) {
      subLabel.textContent =
        state.currentActivityPeriod === "all"
          ? "Comprehensive lifetime movement metrics across your entire timeline"
          : `Movement and distance breakdown for calendar year ${state.currentActivityPeriod}`;
    }

    if (pillsContainer && Array.isArray(data.available_periods)) {
      pillsContainer.innerHTML = "";
      data.available_periods.forEach((p) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = `cat-pill ${state.currentActivityPeriod === p ? "active" : ""}`;
        btn.textContent = p === "all" ? "All Time" : String(p);
        btn.addEventListener("click", () => {
          state.currentActivityPeriod = p;
          loadActivitySummaries(p);
        });
        pillsContainer.appendChild(btn);
      });
    }

    if (heroGrid) {
      const tot = data.totals || {};
      heroGrid.innerHTML = `
        <div class="stat-card card" style="padding:16px;">
          <div style="font-size:11.5px;color:var(--text-muted);text-transform:uppercase;font-weight:700;margin-bottom:4px;">Total Distance</div>
          <div style="font-size:24px;font-weight:800;color:var(--accent-blue);font-family:var(--font-mono);">${tot.total_distance_km ? Number(tot.total_distance_km).toLocaleString() : 0} <span style="font-size:14px;font-weight:600;">km</span></div>
          <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">Across ${tot.total_activities ? Number(tot.total_activities).toLocaleString() : 0} movements</div>
        </div>
        <div class="stat-card card" style="padding:16px;">
          <div style="font-size:11.5px;color:var(--text-muted);text-transform:uppercase;font-weight:700;margin-bottom:4px;">Time in Motion</div>
          <div style="font-size:24px;font-weight:800;color:var(--accent-green);font-family:var(--font-mono);">${tot.total_hours ? Number(tot.total_hours).toLocaleString() : 0} <span style="font-size:14px;font-weight:600;">hrs</span></div>
          <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">Active transit &amp; journey time</div>
        </div>
        <div class="stat-card card" style="padding:16px;">
          <div style="font-size:11.5px;color:var(--text-muted);text-transform:uppercase;font-weight:700;margin-bottom:4px;">Bicycle Travel</div>
          <div style="font-size:24px;font-weight:800;color:#b45309;font-family:var(--font-mono);">${tot.cycle_km ? Number(tot.cycle_km).toLocaleString() : 0} <span style="font-size:14px;font-weight:600;">km</span></div>
          <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">${escapeHtml(tot.transcon_cycles || 0)}x Coast-to-Coast equivalents</div>
        </div>
        <div class="stat-card card" style="padding:16px;">
          <div style="font-size:11.5px;color:var(--text-muted);text-transform:uppercase;font-weight:700;margin-bottom:4px;">Cosmic Flight</div>
          <div style="font-size:24px;font-weight:800;color:#7e22ce;font-family:var(--font-mono);">${tot.fly_km ? Number(tot.fly_km).toLocaleString() : 0} <span style="font-size:14px;font-weight:600;">km</span></div>
          <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">${escapeHtml(tot.earth_orbits || 0)}x Earth orbits · ${escapeHtml(tot.moon_trips || 0)}x Moon distance</div>
        </div>
      `;
    }

    if (bar) {
      bar.innerHTML = "";
      (data.modes || []).forEach((m) => {
        if (m.pct_distance > 0.5) {
          const seg = document.createElement("div");
          seg.style.width = `${m.pct_distance}%`;
          seg.style.background = m.color || "#2563eb";
          seg.title = `${m.label}: ${Number(m.total_km || 0).toLocaleString()} km (${m.pct_distance}%)`;
          bar.appendChild(seg);
        }
      });
    }

    if (cardsGrid) {
      cardsGrid.innerHTML = "";
      (data.modes || []).forEach((m) => {
        const card = document.createElement("div");
        card.className = "mode-summary-card card";
        const color = m.color || "#2563eb";
        card.style.cssText = `padding:14px 16px;display:flex;align-items:center;gap:12px;border-left:4px solid ${color};`;

        card.innerHTML = `
          <div style="width:38px;height:38px;border-radius:8px;background:${escapeHtml(color)}20;color:${escapeHtml(color)};display:flex;align-items:center;justify-content:center;font-size:16px;flex-shrink:0;">
            <i class="fa-solid ${escapeHtml(m.icon || "fa-route")}"></i>
          </div>
          <div style="flex:1;min-width:0;">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">
              <strong style="font-size:13.5px;color:var(--text-main);">${escapeHtml(m.label)}</strong>
              <span class="tag-badge" style="font-size:10.5px;background:var(--bg-subtle);color:#334155;font-weight:700;">${escapeHtml(m.pct_distance)}%</span>
            </div>
            <div style="display:flex;gap:12px;margin-top:4px;font-size:12px;color:var(--text-muted);font-family:var(--font-mono);">
              <span><strong style="color:var(--text-main);">${Number(m.total_km || 0).toLocaleString()}</strong> km</span>
              <span><strong style="color:var(--text-main);">${Number(m.total_hours || 0).toLocaleString()}</strong> hrs</span>
              <span><strong>${Number(m.count || 0).toLocaleString()}</strong> legs</span>
            </div>
          </div>
        `;
        cardsGrid.appendChild(card);
      });
    }

    if (nuggetsGrid) {
      nuggetsGrid.innerHTML = "";
      (data.curated_nuggets || []).forEach((n) => {
        const card = document.createElement("div");
        card.className = "nugget-card card";
        card.style.padding = "16px";
        const accent = n.accent || "#1d4ed8";
        card.innerHTML = `
          <div class="nugget-badge" style="background:${escapeHtml(accent)}20;color:${escapeHtml(accent)};font-size:11px;font-weight:700;display:inline-block;padding:3px 8px;border-radius:4px;margin-bottom:8px;">
            <i class="fa-solid ${escapeHtml(n.icon || "fa-gem")}"></i> ${escapeHtml(n.badge || n.category)}
          </div>
          <div class="nugget-title" style="font-size:14px;font-weight:700;color:var(--text-main);margin-bottom:4px;">${escapeHtml(n.title)}</div>
          <div class="nugget-subtitle" style="font-size:11.5px;color:var(--text-muted);margin-bottom:8px;">
            <i class="fa-regular fa-calendar"></i> ${escapeHtml(n.date)} · ${escapeHtml(n.subtitle)}
          </div>
          <div class="nugget-why" style="font-size:12px;color:var(--text-muted);line-height:1.4;">
            ${escapeHtml(n.why)}
          </div>
        `;
        if (n.date && n.date !== "Lifetime") {
          card.style.cursor = "pointer";
          card.title = `Jump to timeline for ${n.date}`;
          card.addEventListener("click", () => appNav.jumpToTimelineDay(n.date, true, "activities"));
        }
        nuggetsGrid.appendChild(card);
      });
    }

    if (topPlacesEl) {
      topPlacesEl.innerHTML = "";
      (data.top_places || []).forEach((p, idx) => {
        const row = document.createElement("div");
        row.style.cssText =
          "display:flex;align-items:center;justify-content:space-between;padding:8px 12px;background:var(--bg-subtle);border-radius:8px;font-size:12px;cursor:pointer;";
        row.innerHTML = `
          <div style="display:flex;align-items:center;gap:8px;min-width:0;flex:1;">
            <span style="font-weight:700;color:var(--text-muted);font-family:var(--font-mono);font-size:11px;flex-shrink:0;">#${idx + 1}</span>
            <strong style="color:var(--text-main);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(p.name)}</strong>
            ${p.city ? `<span style="color:var(--text-muted);font-size:11px;flex-shrink:0;">(${escapeHtml(p.city)})</span>` : ""}
          </div>
          <span class="tag-badge" style="font-size:10.5px;background:rgba(26,115,232,0.14);color:var(--accent-blue);font-weight:700;flex-shrink:0;">
            ${Number(p.visit_count) || 0} visits
          </span>
        `;
        row.addEventListener("click", () => appNav.openPlaceVisitsModal(p.place_id, p.name));
        topPlacesEl.appendChild(row);
      });
    }

    if (rareModesEl) {
      rareModesEl.innerHTML = "";
      (data.rare_modes || []).forEach((r) => {
        const pill = document.createElement("div");
        const color = r.color || "#6d28d9";
        pill.style.cssText = `display:flex;align-items:center;gap:6px;padding:6px 12px;background:var(--bg-subtle);border:1px solid var(--border-color);border-radius:20px;font-size:11.5px;color:#334155;font-weight:600;cursor:${r.highlight_date ? "pointer" : "default"};`;
        pill.innerHTML = `
          <i class="fa-solid ${escapeHtml(r.icon || "fa-compass")}" style="color:${escapeHtml(color)};"></i>
          <span>${escapeHtml(r.title)} (${Number(r.count) || 0}x · ${escapeHtml(r.total_km)} km)</span>
        `;
        if (r.highlight_date) {
          pill.title = `View peak session on ${r.highlight_date} (${r.highlight_dist_km} km)`;
          pill.addEventListener("click", () => appNav.jumpToTimelineDay(r.highlight_date, true, "activities"));
        }
        rareModesEl.appendChild(pill);
      });
    }
  } catch (err) {
    console.error("Error loading activity summaries:", err);
    if (heroGrid) {
      heroGrid.innerHTML = `<div class="empty-state">Error loading activity summaries: ${escapeHtml(err.message)}</div>`;
    }
  }
}

export function initActivitiesEvents() {
  document.getElementById("btn-refresh-activity-nuggets")?.addEventListener("click", () => {
    loadActivitySummaries(state.currentActivityPeriod);
  });
}
