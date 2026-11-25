// Akses ke endpoint Django: potongan HTML panel dan aksi kamera (POST + CSRF).
import { panelUrl } from "./config.js";

export async function fetchPanel(name, state, signal) {
  const query = new URLSearchParams({
    camera: state.camera,
    range: state.range,
    event_type: state.eventType,
  });
  const response = await fetch(`${panelUrl(name)}?${query}`, { signal });
  if (!response.ok) {
    throw new Error(`Panel "${name}" gagal dimuat (HTTP ${response.status})`);
  }
  return response.text();
}

function csrfToken() {
  return document.querySelector('meta[name="csrf-token"]')?.content ?? "";
}

// POST ke endpoint JSON. Tidak melempar untuk galat HTTP; hasilnya {ok, status, data}.
export async function postForm(url, formData = new FormData(), { json = false } = {}) {
  try {
    const response = await fetch(url, {
      method: "POST",
      body: json ? JSON.stringify(formData) : formData,
      headers: {
        "X-CSRFToken": csrfToken(),
        Accept: "application/json",
        ...(json ? { "Content-Type": "application/json" } : {}),
      },
      credentials: "same-origin",
    });
    let data = {};
    try {
      data = await response.json();
    } catch {
      /* respons bukan JSON */
    }
    return { ok: response.ok, status: response.status, data };
  } catch {
    return { ok: false, status: 0, data: { message: "Tidak bisa menghubungi server." } };
  }
}
