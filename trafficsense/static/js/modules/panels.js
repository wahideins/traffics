// Pemuat panel: mengambil HTML panel dari Django dan menggantinya di halaman.
//
// Atribut pada elemen panel (lihat templates/dashboard/partials/):
//   data-panel="nama"            nama panel (sesuai views/panels.py)
//   data-refresh="live"          ikut diperbarui berkala
//   data-depends="camera range"  diperbarui paksa saat state ini berubah
import { fetchPanel } from "../api.js";
import { config } from "../config.js";
import { getState } from "../state.js";
import { isInteracting, qsa, replacePanel } from "../utils/dom.js";

const inflight = new WeakMap();

export async function refreshPanel(element, { force = false } = {}) {
  if (!element.isConnected) return;
  if (!force && isInteracting(element)) return;

  inflight.get(element)?.abort();
  const controller = new AbortController();
  inflight.set(element, controller);

  try {
    const html = await fetchPanel(element.dataset.panel, getState(), controller.signal);
    if (!element.isConnected) return;
    // Pengguna bisa mulai menunjuk panel selagi permintaan berjalan: cek lagi sebelum mengganti.
    if (!force && isInteracting(element)) return;
    replacePanel(element, html);
  } catch (error) {
    if (error.name !== "AbortError") console.warn(error);
  }
}

// Muat ulang panel yang bergantung pada state yang berubah.
export function refreshDependents(changedKeys) {
  const matching = qsa("[data-panel]").filter((element) =>
    (element.dataset.depends || "").split(" ").some((key) => changedKeys.includes(key)),
  );
  // Lewati panel yang berada di dalam panel lain yang ikut dimuat ulang.
  const targets = matching.filter(
    (element) => !matching.some((other) => other !== element && other.contains(element)),
  );
  return Promise.all(targets.map((element) => refreshPanel(element, { force: true })));
}

function refreshLivePanels() {
  qsa('[data-panel][data-refresh="live"]').forEach((element) => refreshPanel(element));
}

export function startPolling() {
  setInterval(() => {
    if (!document.hidden) refreshLivePanels();
  }, config.refreshMs);

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refreshLivePanels();
  });
}
