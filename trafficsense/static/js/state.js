// State tampilan: kamera, rentang waktu, filter kejadian.
// Disinkronkan ke URL (?camera=&range=&event_type=) agar reload tetap di pilihan yang sama.
const body = document.body;

const state = {
  camera: body.dataset.initialCamera,
  range: body.dataset.initialRange,
  eventType: body.dataset.initialEventType,
};

const listeners = new Set();

export function getState() {
  return { ...state };
}

export function setState(patch) {
  const changed = Object.keys(patch).filter((key) => state[key] !== patch[key]);
  if (changed.length === 0) return;

  Object.assign(state, patch);
  syncUrl();
  listeners.forEach((listener) => listener(getState(), changed));
}

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function syncUrl() {
  const url = new URL(window.location.href);
  url.searchParams.set("camera", state.camera);
  url.searchParams.set("range", state.range);
  url.searchParams.set("event_type", state.eventType);
  window.history.replaceState(null, "", url.toString());
}
