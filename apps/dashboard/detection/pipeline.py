"""Pipeline deteksi satu kamera: frame terbaru -> detektor -> penganalisis, di thread sendiri.

Frame yang datang saat inferensi masih berjalan dibuang (selalu memproses yang terbaru),
sehingga lambatnya model tidak menumpuk antrean maupun memperlambat video.
"""
import json
import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .detector import DetectorUnavailable

LOG = logging.getLogger(__name__)

LOADING, RUNNING, UNAVAILABLE, ERROR, STOPPED = "loading", "running", "unavailable", "error", "stopped"
SAVE_INTERVAL = 30.0
MAX_CONSECUTIVE_ERRORS = 5

# Warna kotak (BGR) selaras dengan kelas kendaraan di CSS.
BOX_COLORS = {"motor": (235, 99, 37), "mobil": (116, 144, 14), "bus": (245, 177, 111), "truk": (11, 119, 217)}
ALERT_COLOR = (68, 68, 239)  # merah
SPEED_COLOR = (22, 160, 245)  # oranye


@dataclass(frozen=True)
class PipelineStatus:
    state: str = LOADING
    message: str = ""
    infer_ms: float = 0.0
    fps: float = 0.0


class DetectionPipeline:
    def __init__(self, code, analyzer, detector_factory, config, *, state_path=None, clock=time.time):
        self.code = code
        self.analyzer = analyzer
        self._detector_factory = detector_factory
        self._config = config
        self._state_path = Path(state_path) if state_path else None
        self._clock = clock

        self._cond = threading.Condition()
        self._pending = None  # (frame, waktu)
        self._last_accept = 0.0
        self._stopping = False
        self._thread = None
        self._status = PipelineStatus()
        self._last_save = time.monotonic()
        self._busy = False

    # --- siklus hidup ------------------------------------------------------
    def start(self):
        with self._cond:
            if self._thread is not None:
                return
            self._thread = threading.Thread(target=self._run, name=f"detect-{self.code}", daemon=True)
            self._thread.start()

    def stop(self):
        with self._cond:
            self._stopping = True
            self._cond.notify_all()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3.0)
        self._save_state()
        self._set(state=STOPPED)

    def status(self):
        with self._cond:
            return self._status

    @property
    def active(self):
        """True bila pipeline masih berjalan atau sedang memuat (kamera perlu dijaga tetap menyala)."""
        return self.status().state in (LOADING, RUNNING, ERROR)

    # --- dari thread pembaca video ---------------------------------------
    def submit(self, frame):
        """Tawarkan frame. Hanya diterima bila sudah waktunya dan pekerja tidak sibuk."""
        if self._stopping or self.status().state not in (LOADING, RUNNING):
            return
        now = time.monotonic()
        with self._cond:
            if self._busy or self._pending is not None:
                return
            if now - self._last_accept < 1.0 / max(self._config.detect_fps, 0.1):
                return
            self._last_accept = now
            self._pending = (frame.copy(), self._clock())
            self._cond.notify_all()

    def annotate(self, frame):
        """Gambar kotak deteksi, garis hitung, dan label pada frame (di tempat)."""
        if self.status().state != RUNNING:
            return
        boxes, line, size = self.analyzer.overlay()
        if size is None:
            return
        import cv2

        h, w = frame.shape[:2]
        sx, sy = w / size[0], h / size[1]
        thick = max(1, round(w / 640))
        font = 0.4 + w / 2400.0

        if line:
            p0 = (int(line[0][0] * sx), int(line[0][1] * sy))
            p1 = (int(line[1][0] * sx), int(line[1][1] * sy))
            cv2.line(frame, p0, p1, (255, 255, 255), thick, cv2.LINE_AA)

        for obj in boxes:
            x1, y1, x2, y2 = (int(obj["box"][0] * sx), int(obj["box"][1] * sy), int(obj["box"][2] * sx), int(obj["box"][3] * sy))
            color = ALERT_COLOR if obj["wrong"] else SPEED_COLOR if obj["speeding"] else BOX_COLORS.get(obj["cls"], (200, 200, 200))
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, thick + 1)
            label = obj["cls"].capitalize()
            if obj["wrong"]:
                label += " · LAWAN ARAH"
            elif obj["speed"] is not None:
                label += f" {round(obj['speed'])} km/j"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font, 1)
            cv2.rectangle(frame, (x1, max(0, y1 - th - 6)), (x1 + tw + 6, y1), color, -1)
            cv2.putText(frame, label, (x1 + 3, max(th, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, font, (255, 255, 255), 1, cv2.LINE_AA)

    # --- thread pekerja ---------------------------------------------------
    def _set(self, **changes):
        with self._cond:
            data = {**self._status.__dict__, **changes}
            self._status = PipelineStatus(**data)

    def _run(self):
        self._load_state()
        try:
            detector = self._detector_factory(self._config)
        except DetectorUnavailable as exc:
            self._set(state=UNAVAILABLE, message=str(exc))
            return
        except Exception:  # noqa: BLE001
            LOG.exception("Kamera %s: gagal membuat detektor", self.code)
            self._set(state=UNAVAILABLE, message="Detektor gagal dimuat. Lihat log server.")
            return
        self._set(state=RUNNING)

        errors = 0
        window_start, window_n = time.monotonic(), 0
        while True:
            with self._cond:
                self._cond.wait_for(lambda: self._pending is not None or self._stopping)
                if self._stopping:
                    return
                frame, t = self._pending
                self._pending = None
                self._busy = True
            try:
                started = time.monotonic()
                detections = detector.detect(frame)
                self.analyzer.process(detections, (frame.shape[1], frame.shape[0]), t)
                elapsed = (time.monotonic() - started) * 1000
                errors = 0
                window_n += 1
                now = time.monotonic()
                fps = self.status().fps
                if now - window_start >= 2.0:
                    fps, window_start, window_n = window_n / (now - window_start), now, 0
                self._set(state=RUNNING, message="", infer_ms=round(elapsed, 1), fps=round(fps, 1))
            except Exception:  # noqa: BLE001
                errors += 1
                LOG.exception("Kamera %s: inferensi gagal (%d)", self.code, errors)
                if errors >= MAX_CONSECUTIVE_ERRORS:
                    self._set(state=ERROR, message="Inferensi berulang kali gagal. Lihat log server.")
                    errors = 0
            finally:
                with self._cond:
                    self._busy = False
            if time.monotonic() - self._last_save >= SAVE_INTERVAL:
                self._save_state()

    # --- penyimpanan keadaan -----------------------------------------------
    def _load_state(self):
        if self._state_path is None or not self._state_path.exists():
            return
        try:
            self.analyzer.load_state(json.loads(self._state_path.read_text()))
        except (OSError, ValueError):
            LOG.warning("Kamera %s: berkas keadaan analitik tidak terbaca, mulai dari nol", self.code)

    def _save_state(self):
        self._last_save = time.monotonic()
        if self._state_path is None:
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self._state_path.parent, suffix=".tmp")
            with os.fdopen(fd, "w") as fh:
                json.dump(self.analyzer.export_state(), fh)
            os.replace(tmp, self._state_path)
        except OSError:
            LOG.exception("Kamera %s: gagal menyimpan keadaan analitik", self.code)

    def delete_state(self):
        if self._state_path is not None:
            try:
                self._state_path.unlink()
            except OSError:
                pass
