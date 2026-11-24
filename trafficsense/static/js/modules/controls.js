// Kontrol pengguna: pilih kamera, rentang waktu, dan filter kejadian.
// Memakai delegasi event karena panelnya diganti ulang oleh panels.js.
import { setState } from "../state.js";

const ACTIONS = {
  "select-camera": (button) => setState({ camera: button.dataset.camera }),
  "select-range": (button) => setState({ range: button.dataset.range }),
  "select-event-type": (button) => setState({ eventType: button.dataset.eventType }),
};

export function initControls() {
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-action]");
    if (!button || !(button.dataset.action in ACTIONS)) return;
    ACTIONS[button.dataset.action](button);
  });
}
