// Halaman pengaturan: simpan parameter, kelola model, tindakan kamera.
import { postForm } from "./api.js";
import { initCameraAdmin } from "./modules/camera-admin.js";
import { qs, qsa } from "./utils/dom.js";

const root = qs("[data-admin]");
const statusEl = qs("[data-admin-status]");

function say(text, kind = "info") {
  statusEl.hidden = !text;
  statusEl.textContent = text;
  statusEl.className = `form-status form-status--${kind}`;
}

const message = (res) => res.data?.message || (res.ok ? "Selesai." : `Gagal (HTTP ${res.status}).`);

function describeModel(info) {
  const lines = [
    `Keluaran: ${info.layout}, masukan ${info.input}, perangkat ${(info.provider || "").toUpperCase()}`,
    `Kecepatan uji: ${info.ms} ms per frame (sekitar ${info.max_fps} fps)`,
  ];
  (info.warnings || []).forEach((w) => lines.push(`⚠ ${w}`));
  return lines.join("\n");
}

function showResult(name, text) {
  const row = qsa("[data-result-for]", root).find((r) => r.dataset.resultFor === name);
  if (!row) return say(text);
  row.hidden = !text;
  row.firstElementChild.textContent = text;
}

// Simpan parameter
const form = qs("[data-settings-form]");
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  qsa("[data-error-for]", form).forEach((el) => (el.textContent = ""));
  say("Menyimpan…");
  const res = await postForm(form.action, new FormData(form));
  if (res.ok) {
    say(res.data.restarted ? "Tersimpan. Kamera dimulai ulang; muat ulang dashboard." : "Tersimpan (tidak ada perubahan).", "ok");
    setTimeout(() => location.reload(), 1200);
    return;
  }
  const errors = res.data?.errors || {};
  Object.entries(errors).forEach(([key, text]) => {
    const el = qs(`[data-error-for="${key}"]`, form);
    if (el) el.textContent = text;
  });
  say(Object.keys(errors).length ? "Ada isian yang perlu diperbaiki." : message(res), "error");
});

qs("[data-reset]", form)?.addEventListener("click", async (event) => {
  if (!confirm("Hapus semua pengaturan tersimpan dan kembali ke bawaan?")) return;
  const res = await postForm(event.currentTarget.dataset.url);
  say(res.ok ? "Dikembalikan ke bawaan." : message(res), res.ok ? "ok" : "error");
  if (res.ok) setTimeout(() => location.reload(), 800);
});

// Tombol model dan kamera (delegasi, karena tabel kamera diperbarui berkala)
root.addEventListener("click", async (event) => {
  const btn = event.target.closest("button");
  if (!btn) return;
  const { modelTest, modelPost, post, confirm: ask, reload } = btn.dataset;
  if (ask && !confirm(ask)) return;
  if (modelTest) {
    const name = btn.closest("[data-model]").dataset.model;
    btn.disabled = true;
    showResult(name, "Menguji… (bisa beberapa detik)");
    const res = await postForm(modelTest);
    btn.disabled = false;
    showResult(name, res.ok ? describeModel(res.data.info) : message(res));
  } else if (modelPost || post) {
    btn.disabled = true;
    const res = await postForm(modelPost || post);
    btn.disabled = false;
    say(message(res), res.ok ? "ok" : "error");
    if (res.ok && (modelPost || reload)) setTimeout(() => location.reload(), 600);
  }
});

// Unggah model
const upload = qs("[data-upload]");
upload.addEventListener("submit", async (event) => {
  event.preventDefault();
  say("Mengunggah dan memeriksa model…");
  const res = await postForm(upload.action, new FormData(upload));
  if (res.ok) {
    say(`${res.data.name} diunggah.\n${describeModel(res.data.info)}`, "ok");
    setTimeout(() => location.reload(), 2500);
  } else {
    say(message(res), "error");
  }
});

// Tabel kamera diperbarui tiap 3 detik
const cams = qs("[data-cameras]");
setInterval(async () => {
  if (document.hidden) return;
  try {
    const r = await fetch(root.dataset.camerasUrl, { credentials: "same-origin" });
    if (r.ok) cams.innerHTML = await r.text();
  } catch { /* abaikan */ }
}, 3000);

initCameraAdmin();
