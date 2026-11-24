// Akses ke endpoint Django. Saat ini hanya potongan HTML panel.
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
