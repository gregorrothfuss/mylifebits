export function getLocalToday() {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function stepDate(dateStr, deltaDays) {
  const parts = String(dateStr || "").split("-").map(Number);
  if (parts.length !== 3 || parts.some(Number.isNaN)) {
    return getLocalToday();
  }
  const [y, m, d] = parts;
  const utcMs = Date.UTC(y, m - 1, d, 12, 0, 0) + deltaDays * 86400 * 1000;
  const next = new Date(utcMs);
  const ny = next.getUTCFullYear();
  const nm = String(next.getUTCMonth() + 1).padStart(2, "0");
  const nd = String(next.getUTCDate()).padStart(2, "0");
  return `${ny}-${nm}-${nd}`;
}

export function extractIsoOffset(isoStr) {
  if (!isoStr || typeof isoStr !== "string") return "";
  const match = isoStr.trim().match(/(Z|[+-]\d{2}:\d{2}|[+-]\d{4})$/);
  if (!match) return "";
  const raw = match[1];
  if (raw === "Z") return "Z";
  if (raw.length === 5 && !raw.includes(":")) {
    return `${raw.slice(0, 3)}:${raw.slice(3)}`;
  }
  return raw;
}

export function format24hTime(isoStr) {
  if (!isoStr || typeof isoStr !== "string") return "--:--";
  const match = isoStr.match(/T(\d{2}:\d{2})/);
  if (match) return match[1];
  const spaceMatch = isoStr.match(/\s(\d{2}:\d{2})/);
  if (spaceMatch) return spaceMatch[1];
  return isoStr.slice(11, 16) || "--:--";
}

export function formatEventTime(isoStr) {
  return format24hTime(isoStr);
}

export function toDateTimeLocalValue(isoStr) {
  if (!isoStr || typeof isoStr !== "string") return "";
  const clean = isoStr.trim().replace(" ", "T");
  const match = clean.match(/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})/);
  if (match) return match[1];
  return "";
}

export function fromDateTimeLocalValue(localVal, preservedOffset = "+00:00") {
  if (!localVal || typeof localVal !== "string") return "";
  const trimmed = localVal.trim();
  const hasSeconds = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/.test(trimmed);
  const base = hasSeconds ? trimmed.slice(0, 19) : `${trimmed.slice(0, 16)}:00`;
  const offset = preservedOffset || "+00:00";
  return `${base}${offset}`;
}

export function getDayStartEpoch(dayData) {
  const dateStr = dayData?.date || getLocalToday();
  let offset = "";
  const segments = dayData?.segments || [];
  for (const s of segments) {
    offset = extractIsoOffset(s.start_time) || extractIsoOffset(s.end_time);
    if (offset) break;
  }
  const isoMidnight = `${dateStr}T00:00:00${offset || "Z"}`;
  const parsed = Date.parse(isoMidnight);
  if (Number.isNaN(parsed)) {
    return Date.parse(`${dateStr}T00:00:00Z`) / 1000.0;
  }
  return parsed / 1000.0;
}

export function getMinutesFromTimeStr(isoStr) {
  if (!isoStr || isoStr.length < 16) return 0;
  const h = parseInt(isoStr.slice(11, 13), 10) || 0;
  const m = parseInt(isoStr.slice(14, 16), 10) || 0;
  return h * 60 + m;
}

export function getWeekDateRange(dateStr) {
  const baseDate = dateStr || getLocalToday();
  const d = new Date(`${baseDate}T12:00:00Z`);
  const day = d.getUTCDay();
  const diffToMon = (day === 0 ? -6 : 1) - day;
  const startDate = stepDate(baseDate, diffToMon);
  const endDate = stepDate(startDate, 6);
  return { startDate, endDate };
}

export function formatActivityName(actType) {
  if (!actType) return "Travel";
  const upper = String(actType).toUpperCase();
  if (upper === "IN_PASSENGER_VEHICLE" || upper === "DRIVING") return "Driving";
  return String(actType)
    .replace(/^IN_/, "")
    .replace(/^ON_/, "")
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
