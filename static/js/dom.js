export function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function safeHref(rawUrl) {
  if (!rawUrl || typeof rawUrl !== "string") return "#";
  const trimmed = rawUrl.trim();
  if (trimmed.startsWith("/") && !trimmed.startsWith("//")) {
    return escapeHtml(trimmed);
  }
  try {
    const parsed = new URL(trimmed, window.location.origin);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") {
      return escapeHtml(parsed.href);
    }
  } catch {
    return "#";
  }
  return "#";
}

export function getPhotoUrl(url, _size = "thumb") {
  if (!url) return "";
  const str = String(url).trim();
  if (!str) return "";
  if (str.startsWith("http://") || str.startsWith("https://") || str.startsWith("/") || str.startsWith("data:") || str.startsWith("blob:")) {
    return str;
  }
  return `/${str}`;
}

window.getPhotoUrl = getPhotoUrl;

export function setElText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val !== undefined && val !== null ? String(val) : "";
}

export function renderStars(rating) {
  const n = Math.max(0, Math.min(5, Math.round(Number(rating) || 0)));
  return "★".repeat(n) + "☆".repeat(5 - n);
}

export function formatPeopleList(raw) {
  if (!raw) return "";
  if (Array.isArray(raw)) {
    return raw.map((item) => String(item).trim()).filter(Boolean).join(", ");
  }
  const str = String(raw).trim();
  if (!str || str === "[]" || str === "null") return "";
  if (str.startsWith("[")) {
    try {
      const parsed = JSON.parse(str);
      if (Array.isArray(parsed)) {
        return parsed.map((item) => String(item).trim()).filter(Boolean).join(", ");
      }
    } catch {
      // Fall through to plain string
    }
  }
  return str;
}

export function isDialogOpen(dialog) {
  if (!dialog) return false;
  if (dialog instanceof HTMLDialogElement) {
    return dialog.open;
  }
  return !dialog.classList.contains("hidden");
}

export function openDialog(dialog) {
  if (!dialog) return;
  if (dialog instanceof HTMLDialogElement) {
    dialog.classList.remove("hidden");
    if (!dialog.open) {
      dialog.showModal();
    }
    return;
  }
  dialog.classList.remove("hidden");
}

export function closeDialog(dialog) {
  if (!dialog) return;
  if (dialog instanceof HTMLDialogElement) {
    if (dialog.open) {
      dialog.close();
    }
    return;
  }
  dialog.classList.add("hidden");
}

export function closeAllDialogs() {
  document.querySelectorAll("dialog[open]").forEach((dlg) => {
    dlg.close();
  });
}

export function initDialogLightDismissFallback() {
  if (typeof HTMLDialogElement === "undefined") return;
  const supportsClosedBy = "closedBy" in HTMLDialogElement.prototype;
  if (supportsClosedBy) return;

  document.querySelectorAll('dialog[closedby="any"]').forEach((dialog) => {
    dialog.addEventListener("click", (event) => {
      if (event.target !== dialog) return;
      const rect = dialog.getBoundingClientRect();
      const clickedInBackdrop =
        event.clientX < rect.left ||
        event.clientX > rect.right ||
        event.clientY < rect.top ||
        event.clientY > rect.bottom;
      if (clickedInBackdrop && dialog.open) {
        dialog.close();
      }
    });
  });
}

export function showPopoverSafe(el) {
  if (!el) return;
  el.hidden = false;
  if (typeof el.showPopover === "function") {
    try {
      if (!el.matches(":popover-open")) {
        el.showPopover();
      }
      return;
    } catch {
      // Fallback below if not mounted or unsupported
    }
  }
  el.classList.add("is-open");
}

export function hidePopoverSafe(el) {
  if (!el) return;
  if (typeof el.hidePopover === "function") {
    try {
      if (el.matches(":popover-open")) {
        el.hidePopover();
      }
    } catch {
      // Ignore when already closed
    }
  }
  el.classList.remove("is-open");
}

export function isIMEComposing(event) {
  return Boolean(event.isComposing || event.keyCode === 229);
}

export function initImageErrorDelegation() {
  document.addEventListener(
    "error",
    (event) => {
      const target = event.target;
      if (!(target instanceof HTMLImageElement)) return;

      const fallbackIcon = target.dataset.fallbackIcon;
      if (fallbackIcon && target.parentElement) {
        const wrapper = target.parentElement;
        wrapper.textContent = "";
        const iconDiv = document.createElement("div");
        iconDiv.className = "search-item-icon";
        const iconEl = document.createElement("i");
        iconEl.className = `fa-solid ${fallbackIcon}`;
        iconDiv.appendChild(iconEl);
        wrapper.replaceWith(iconDiv);
        return;
      }

      const hideMode = target.dataset.hideOnError;
      if (hideMode === "parent" && target.parentElement) {
        target.parentElement.hidden = true;
        target.parentElement.style.display = "none";
      } else if (hideMode === "self") {
        target.hidden = true;
        target.style.display = "none";
      }
    },
    true
  );
}

const loadedScripts = new Map();
const loadedStyles = new Set();

export function loadStylesheetOnce(href) {
  if (loadedStyles.has(href) || document.querySelector(`link[href="${href}"]`)) {
    loadedStyles.add(href);
    return Promise.resolve();
  }
  return new Promise((resolve, reject) => {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = href;
    link.onload = () => {
      loadedStyles.add(href);
      resolve();
    };
    link.onerror = () => reject(new Error(`Failed to load stylesheet: ${href}`));
    document.head.appendChild(link);
  });
}

export function loadExternalScriptOnce(src) {
  if (loadedScripts.has(src)) {
    return loadedScripts.get(src);
  }
  const existing = document.querySelector(`script[src="${src}"]`);
  if (existing && existing.dataset.loaded === "true") {
    return Promise.resolve();
  }
  const promise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.onload = () => {
      script.dataset.loaded = "true";
      resolve();
    };
    script.onerror = () => {
      loadedScripts.delete(src);
      reject(new Error(`Failed to load script: ${src}`));
    };
    document.head.appendChild(script);
  });
  loadedScripts.set(src, promise);
  return promise;
}
