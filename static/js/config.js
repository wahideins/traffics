// Konfigurasi dibaca dari atribut data-* pada <body> (diisi oleh Django).
const body = document.body;

export const config = {
  panelUrlTemplate: body.dataset.panelUrl, // contoh: "/panels/__name__/"
  refreshMs: Number(body.dataset.refreshMs) || 2000,
  connectingMs: 1400, // lama overlay "Menghubungkan…" (simulasi)
};

export function panelUrl(name) {
  return config.panelUrlTemplate.replace("__name__", name);
}
