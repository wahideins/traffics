// Overlay "Menghubungkan…" sebentar saat kamera diganti.
import { config } from "../config.js";

let timer;

export function showConnecting(duration = config.connectingMs) {
  const overlay = document.querySelector(".feed__overlay");
  if (!overlay) return;

  overlay.hidden = false;

  clearTimeout(timer);
  timer = setTimeout(() => {
    document.querySelectorAll(".feed__overlay").forEach((el) => (el.hidden = true));
  }, duration);
}
