// Titik masuk front-end dashboard.
import { startClock } from "./modules/clock.js";
import { initCalibration } from "./modules/calibration.js";
import { initCameraAdmin } from "./modules/camera-admin.js";
import { initConnection, showConnecting } from "./modules/connection.js";
import { initControls } from "./modules/controls.js";
import { refreshDependents, startPolling } from "./modules/panels.js";
import { subscribe } from "./state.js";

// Saat state berubah: muat ulang panel terkait, lalu simulasikan koneksi bila kamera berganti.
subscribe(async (_state, changedKeys) => {
  await refreshDependents(changedKeys);
  if (changedKeys.includes("camera")) showConnecting();
});

initControls();
initCameraAdmin();
initCalibration();
initConnection();
startClock();
startPolling();
