import { getLocalToday } from "./time.js";

const DEV_W = 1080;
const DEV_H = 2400;

const img = document.getElementById("screen-img");
const viewport = document.getElementById("screen-viewport");
const ripple = document.getElementById("touch-ripple");
const statusDot = document.getElementById("status-dot");
const fpsBadge = document.getElementById("fps-badge");
const toastEl = document.getElementById("toast");
const dateInput = document.getElementById("jump-date-input");

const params = new URLSearchParams(window.location.search);
const initialDate = params.get("date") || getLocalToday();
if (dateInput) {
  dateInput.value = initialDate;
}

let isFetching = false;
let lastFrameTime = performance.now();
let currentObjectUrl = null;
let frameTimer = null;
let statusTimer = null;

function showToast(msg) {
  if (!toastEl) return;
  toastEl.textContent = msg;
  toastEl.classList.add("show");
  clearTimeout(toastEl._timer);
  toastEl._timer = setTimeout(() => toastEl.classList.remove("show"), 1800);
}

async function checkStatus() {
  if (document.hidden) return;
  try {
    const r = await fetch("/api/device/status");
    const d = await r.json();
    if (d.connected) {
      statusDot?.classList.add("online");
    } else {
      statusDot?.classList.remove("online");
      if (fpsBadge) fpsBadge.textContent = "Offline";
    }
  } catch {
    statusDot?.classList.remove("online");
  }
}

async function pullFrame() {
  if (isFetching || document.hidden || !img) return;
  isFetching = true;
  const t0 = performance.now();
  try {
    const resp = await fetch(`/api/device/screen?t=${Date.now()}`, { cache: "no-store" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const blob = await resp.blob();
    if (blob.size > 1000) {
      const nextUrl = URL.createObjectURL(blob);
      img.onload = () => {
        if (currentObjectUrl) URL.revokeObjectURL(currentObjectUrl);
        currentObjectUrl = nextUrl;
      };
      img.src = nextUrl;
      statusDot?.classList.add("online");
      const dt = Math.max(1, performance.now() - lastFrameTime);
      lastFrameTime = performance.now();
      const fps = (1000 / dt).toFixed(1);
      const lat = Math.round(performance.now() - t0);
      if (fpsBadge) fpsBadge.textContent = `${fps} fps · ${lat}ms`;
    }
  } catch {
    if (fpsBadge) fpsBadge.textContent = "Reconnecting...";
  } finally {
    isFetching = false;
    if (!document.hidden) {
      scheduleFrame(180);
    }
  }
}

function scheduleFrame(delayMs) {
  clearTimeout(frameTimer);
  if (!document.hidden) {
    frameTimer = setTimeout(pullFrame, delayMs);
  }
}

function startStatusPolling() {
  clearInterval(statusTimer);
  statusTimer = setInterval(() => {
    if (!document.hidden) checkStatus();
  }, 6000);
}

function toDeviceCoords(clientX, clientY) {
  const rect = viewport.getBoundingClientRect();
  const relX = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
  const relY = Math.max(0, Math.min(1, (clientY - rect.top) / rect.height));
  return {
    x: Math.round(relX * DEV_W),
    y: Math.round(relY * DEV_H),
    pxX: clientX - rect.left,
    pxY: clientY - rect.top,
  };
}

function triggerRipple(pxX, pxY) {
  if (!ripple) return;
  ripple.classList.remove("animate");
  ripple.style.left = `${pxX}px`;
  ripple.style.top = `${pxY}px`;
  void ripple.offsetWidth;
  ripple.classList.add("animate");
}

let pointerDown = null;

viewport?.addEventListener("pointerdown", (e) => {
  viewport.setPointerCapture(e.pointerId);
  const c = toDeviceCoords(e.clientX, e.clientY);
  pointerDown = { ...c, t: performance.now() };
  triggerRipple(c.pxX, c.pxY);
});

viewport?.addEventListener("pointerup", async (e) => {
  if (!pointerDown) return;
  const up = toDeviceCoords(e.clientX, e.clientY);
  const dx = up.x - pointerDown.x;
  const dy = up.y - pointerDown.y;
  const dist = Math.hypot(dx, dy);
  const elapsed = Math.round(performance.now() - pointerDown.t);
  const start = pointerDown;
  pointerDown = null;

  try {
    if (dist < 28) {
      if (elapsed > 550) {
        await fetch("/api/device/touch", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "swipe", x: start.x, y: start.y, x2: start.x, y2: start.y, duration: 650 }),
        });
      } else {
        await fetch("/api/device/touch", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "tap", x: up.x, y: up.y }),
        });
      }
    } else {
      const dur = Math.max(120, Math.min(700, elapsed));
      await fetch("/api/device/touch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "swipe", x: start.x, y: start.y, x2: up.x, y2: up.y, duration: dur }),
      });
    }
    scheduleFrame(90);
  } catch (err) {
    console.error("Touch error:", err);
  }
});

let wheelLock = false;
viewport?.addEventListener(
  "wheel",
  async (e) => {
    e.preventDefault();
    if (wheelLock) return;
    wheelLock = true;
    setTimeout(() => {
      wheelLock = false;
    }, 280);

    const c = toDeviceCoords(e.clientX, e.clientY);
    const delta = e.deltaY > 0 ? -520 : 520;
    const y2 = Math.max(200, Math.min(DEV_H - 200, c.y + delta));
    await fetch("/api/device/touch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "swipe", x: c.x, y: c.y, x2: c.x, y2, duration: 220 }),
    });
    scheduleFrame(120);
  },
  { passive: false }
);

async function sendKey(keycode) {
  await fetch("/api/device/touch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "key", x: keycode }),
  });
  scheduleFrame(120);
}

document.getElementById("nav-back")?.addEventListener("click", () => sendKey(4));
document.getElementById("nav-home")?.addEventListener("click", () => sendKey(3));
document.getElementById("nav-recents")?.addEventListener("click", () => sendKey(187));

document.getElementById("btn-Screenshot")?.addEventListener("click", () => {
  scheduleFrame(10);
  showToast("Refreshing screen...");
});

document.getElementById("btn-wake")?.addEventListener("click", async () => {
  await sendKey(224);
  await fetch("/api/device/touch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "swipe", x: 540, y: 1950, x2: 540, y2: 650, duration: 250 }),
  });
  showToast("Woke & unlocked screen");
  scheduleFrame(200);
});

document.getElementById("btn-open-timeline")?.addEventListener("click", async () => {
  showToast("Launching Google Maps Timeline...");
  await fetch("/api/device/open-timeline", { method: "POST" });
  scheduleFrame(600);
});

async function jumpToDate(dateStr) {
  if (!dateStr) return;
  showToast(`Navigating device to ${dateStr}...`);
  await fetch("/api/device/intent-day", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ date: dateStr }),
  });
  scheduleFrame(700);
}

document.getElementById("btn-jump-date")?.addEventListener("click", () => {
  if (dateInput?.value) {
    jumpToDate(dateInput.value);
  }
});

window.addEventListener("keydown", async (e) => {
  if (e.isComposing || e.keyCode === 229) return;
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const activeTag = document.activeElement?.tagName || "";
  if (activeTag === "INPUT" || activeTag === "TEXTAREA" || activeTag === "SELECT" || activeTag === "BUTTON" || activeTag === "A") {
    return;
  }

  if (e.key === "Escape") {
    e.preventDefault();
    await sendKey(4);
  } else if (e.key === "Backspace") {
    e.preventDefault();
    await sendKey(67);
  } else if (e.key === "Enter") {
    e.preventDefault();
    await sendKey(66);
  } else if (e.key.length === 1) {
    await fetch("/api/device/keyboard", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: e.key }),
    });
    scheduleFrame(50);
  }
});

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    clearTimeout(frameTimer);
  } else {
    checkStatus();
    scheduleFrame(20);
  }
});

checkStatus();
startStatusPolling();
scheduleFrame(20);
if (params.get("jump") === "1" && params.get("date")) {
  setTimeout(() => jumpToDate(params.get("date")), 400);
}
