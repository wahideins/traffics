// Jam dan tanggal di header dan HUD kamera (waktu perangkat pengguna).
import { qsa } from "../utils/dom.js";

const timeFormat = new Intl.DateTimeFormat("id-ID", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

const dateFormat = new Intl.DateTimeFormat("id-ID", {
  weekday: "long",
  day: "numeric",
  month: "long",
  year: "numeric",
});

function render() {
  const now = new Date();
  const time = timeFormat.format(now).replace(/\./g, ":");
  const date = dateFormat.format(now);
  qsa("[data-clock]").forEach((el) => (el.textContent = time));
  qsa("[data-date]").forEach((el) => (el.textContent = date));
}

export function startClock() {
  render();
  setInterval(render, 1000);
}
