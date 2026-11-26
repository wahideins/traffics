// Tambah dan tes kamera RTSP lewat dialog (dipakai di halaman pengaturan).
import { postForm } from "../api.js";
import { qsa } from "../utils/dom.js";

const dialog = () => document.getElementById("add-camera-dialog");
const form = () => document.querySelector("[data-camera-form]");

function setStatus(kind, text) {
  const el = form().querySelector("[data-form-status]");
  el.textContent = text;
  el.className = `form-status${kind ? ` form-status--${kind}` : ""}`;
}

function clearErrors() {
  qsa("[data-error-for]", form()).forEach((el) => (el.textContent = ""));
  qsa(".input", form()).forEach((el) => el.removeAttribute("aria-invalid"));
}

function showErrors(errors = {}) {
  clearErrors();
  let first = null;
  for (const [field, message] of Object.entries(errors)) {
    const slot = form().querySelector(`[data-error-for="${CSS.escape(field)}"]`);
    const input = form().elements[field];
    if (slot) slot.textContent = message;
    if (input) {
      input.setAttribute("aria-invalid", "true");
      first ??= input;
    }
  }
  first?.focus();
}

function setBusy(busy) {
  qsa("[data-submit-btn], [data-action=probe-camera]", form()).forEach((b) => (b.disabled = busy));
}

function openDialog() {
  form().reset();
  clearErrors();
  setStatus("", "");
  dialog().showModal();
  form().elements.name.focus();
}

async function probe() {
  clearErrors();
  setBusy(true);
  setStatus("info", "Mencoba terhubung… (bisa sampai 10 detik)");
  const { data } = await postForm(dialog().dataset.probeUrl, new FormData(form()));
  setBusy(false);
  if (data.errors) {
    showErrors(data.errors);
    setStatus("error", "Periksa isian yang bertanda merah.");
  } else if (data.ok) {
    setStatus("ok", data.message || "Terhubung.");
  } else {
    setStatus("error", data.message || "Gagal terhubung.");
  }
}

async function submit(event) {
  event.preventDefault();
  clearErrors();
  setBusy(true);
  setStatus("info", "Menyimpan…");
  const { ok, data } = await postForm(form().action, new FormData(form()));
  setBusy(false);
  if (ok && data.ok) {
    dialog().close();
    hooks.onAdded(data.code);
  } else {
    showErrors(data.errors);
    setStatus("error", data.errors ? "Periksa isian yang bertanda merah." : "Gagal menyimpan kamera.");
  }
}

const hooks = { onAdded: () => window.location.reload() };

export function initCameraAdmin(options = {}) {
  Object.assign(hooks, options);
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-action]");
    if (!button) return;
    switch (button.dataset.action) {
      case "open-add-camera": return openDialog();
      case "close-add-camera": return dialog().close();
      case "probe-camera": return probe();
    }
  });

  // Klik pada latar gelap (di luar kotak dialog) menutup dialog.
  dialog().addEventListener("click", (event) => {
    if (event.target === dialog()) dialog().close();
  });
  form().addEventListener("submit", submit);
}
