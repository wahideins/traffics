// Simulasi status koneksi RTSP: overlay "Menghubungkan…" saat ganti kamera
// atau menekan "Hubungkan ulang". Belum ada koneksi sungguhan di tahap ini.
import { config } from "../config.js";

let timer;

export function showConnecting(duration = config.connectingMs) {
  const overlay = document.querySelector(".feed__overlay");
  const button = document.querySelector("[data-reconnect-btn]");
  if (!overlay) return;

  overlay.hidden = false;
  if (button) {
    button.disabled = true;
    button.textContent = "Menghubungkan…";
  }

  clearTimeout(timer);
  timer = setTimeout(() => {
    document.querySelectorAll(".feed__overlay").forEach((el) => (el.hidden = true));
    document.querySelectorAll("[data-reconnect-btn]").forEach((btn) => {
      btn.disabled = false;
      btn.textContent = "Hubungkan ulang";
    });
  }, duration);
}

export function initConnection() {
  document.addEventListener("submit", (event) => {
    if (event.target.matches('[data-action="reconnect"]')) {
      event.preventDefault();
      showConnecting();
    }
  });
}
