const inFlightControllers = new Map();

export function abortSlot(slot) {
  const prev = inFlightControllers.get(slot);
  if (prev) {
    prev.abort();
    inFlightControllers.delete(slot);
  }
}

export async function fetchSlotJson(slot, url, options = {}) {
  abortSlot(slot);
  const controller = new AbortController();
  inFlightControllers.set(slot, controller);

  try {
    const res = await fetch(url, {
      ...options,
      signal: controller.signal,
    });
    if (inFlightControllers.get(slot) === controller) {
      inFlightControllers.delete(slot);
    }
    const data = await res.json();
    return { aborted: false, ok: res.ok, status: res.status, data };
  } catch (err) {
    if (inFlightControllers.get(slot) === controller) {
      inFlightControllers.delete(slot);
    }
    if (err && err.name === "AbortError") {
      return { aborted: true, ok: false, status: 0, data: null };
    }
    throw err;
  }
}

export async function postJson(url, payload = {}, options = {}) {
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    body: JSON.stringify(payload),
    ...options,
  });
  const data = await res.json();
  return { ok: res.ok, status: res.status, data };
}
