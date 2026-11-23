// Status koneksi RTSP: overlay "Menghubungkan…" saat ganti kamera atau menekan "Hubungkan ulang".
// Untuk kamera RTSP, tombol meminta server menyambung ulang lalu memuat ulang video.
import { postForm } from "../api.js";
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

function reloadVideo() {
  const img = document.querySelector("img[data-feed-video]");
  if (!img) return;
  const url = new URL(img.getAttribute("src"), window.location.href);
  url.searchParams.set("t", Date.now());
  img.src = url.toString();
}

export function initConnection() {
  document.addEventListener("submit", async (event) => {
    const formEl = event.target;
    if (!formEl.matches('[data-action="reconnect"]')) return;
    event.preventDefault();

    const url = formEl.dataset.reconnectUrl;
    if (url) await postForm(url);
    showConnecting();
    if (url) setTimeout(reloadVideo, 300);
  });
}
