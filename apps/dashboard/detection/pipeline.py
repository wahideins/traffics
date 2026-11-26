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

import numpy as np

from .calibration import polygon_area, zones_bbox
from .detector import DetectorUnavailable
from .types import Detection

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
    provider: str = ""


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
        self._zone_mask_key, self._zone_mask, self._zone_area = None, None, 0.0
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

        roi = self.analyzer.calibration.roi

        h, w = frame.shape[:2]
        sx, sy = w / size[0], h / size[1]
        thick = max(1, round(w / 640))
        font = 0.4 + w / 2400.0

        if roi and not self.analyzer.calibration.detect_in_zones:
            cv2.rectangle(
                frame, (int(roi[0][0] * w), int(roi[0][1] * h)), (int(roi[1][0] * w), int(roi[1][1] * h)),
                (255, 200, 120), 1, cv2.LINE_AA,
            )
        self._draw_zones(frame, cv2, thick, font)
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
                label += " - LAWAN ARAH"
            elif obj["speed"] is not None:
                label += f" {round(obj['speed'])} km/j"
            if obj.get("zone") is not None and obj.get("dwell") is not None:
                label += " | zona " + f"{obj['dwell']:.1f}".replace(".", ",") + " dtk"  # Hershey hanya ASCII
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font, 1)
            cv2.rectangle(frame, (x1, max(0, y1 - th - 6)), (x1 + tw + 6, y1), color, -1)
            cv2.putText(frame, label, (x1 + 3, max(th, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, font, (255, 255, 255), 1, cv2.LINE_AA)

    def _draw_zones(self, frame, cv2, thick, font):
        """Isi poligon zona secara tembus pandang, garis tepi, dan nama zona."""
        zones = self.analyzer.calibration.zones
        if not zones:
            return
        h, w = frame.shape[:2]
        polys = [np.array([[int(x * w), int(y * h)] for x, y in z.points], dtype=np.int32) for z in zones]
        layer = frame.copy()
        for zone, poly in zip(zones, polys):
            cv2.fillPoly(layer, [poly], zone.bgr)
        cv2.addWeighted(layer, 0.28, frame, 0.72, 0, frame)
        for zone, poly in zip(zones, polys):
            cv2.polylines(frame, [poly], True, zone.bgr, thick, cv2.LINE_AA)
            (tw, th), _ = cv2.getTextSize(zone.name, cv2.FONT_HERSHEY_SIMPLEX, font, 1)
            x, y = int(poly[:, 0].mean() - tw / 2), int(poly[:, 1].min()) + th + 8
            x, y = max(2, min(x, w - tw - 8)), max(th + 4, min(y, h - 4))
            cv2.rectangle(frame, (x - 3, y - th - 4), (x + tw + 3, y + 4), zone.bgr, -1)
            cv2.putText(frame, zone.name, (x, y), cv2.FONT_HERSHEY_SIMPLEX, font, (255, 255, 255), 1, cv2.LINE_AA)

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
        self._set(state=RUNNING, provider=getattr(detector, "provider", ""))

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
                detections, area = self._detect_in_roi(detector, frame)
                self.analyzer.process(detections, (frame.shape[1], frame.shape[0]), t, area=area)
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

    def _detect_in_roi(self, detector, frame):
        """Jalankan detektor hanya pada area deteksi (bila diatur). Kembalikan (deteksi pada koordinat frame penuh, luas area)."""
        h, w = frame.shape[:2]
        cal = self.analyzer.calibration
        if cal.detect_in_zones:
            return self._detect_in_zones(detector, frame, cal)
        roi = cal.roi
        if not roi:
            return detector.detect(frame), float(w * h)
        x0, y0 = int(roi[0][0] * w), int(roi[0][1] * h)
        x1, y1 = max(x0 + 1, int(roi[1][0] * w)), max(y0 + 1, int(roi[1][1] * h))
        found = detector.detect(frame[y0:y1, x0:x1])
        shifted = [
            Detection((d.box[0] + x0, d.box[1] + y0, d.box[2] + x0, d.box[3] + y0), d.score, d.cls) for d in found
        ]
        return shifted, float((x1 - x0) * (y1 - y0))

    def _detect_in_zones(self, detector, frame, cal):
        """Deteksi hanya di dalam zona: crop ke kotak pembatas zona, tutup piksel di luar zona, saring hasilnya.

        Kembalikan (deteksi pada koordinat frame penuh, luas gabungan zona dalam piksel).
        """
        import cv2

        h, w = frame.shape[:2]
        (nx0, ny0), (nx1, ny1) = zones_bbox(cal.zones)
        x0, y0 = int(nx0 * w), int(ny0 * h)
        x1, y1 = max(x0 + 2, int(nx1 * w)), max(y0 + 2, int(ny1 * h))
        key = (cal.zones, w, h)
        if self._zone_mask_key != key:
            mask = np.zeros((h, w), dtype=np.uint8)
            for z in cal.zones:
                cv2.fillPoly(mask, [np.array([[int(px * w), int(py * h)] for px, py in z.points], dtype=np.int32)], 255)
            self._zone_area = float(np.count_nonzero(mask))
            grow = max(3, int(0.012 * min(w, h)))  # sisa kecil agar kendaraan di tepi zona tidak terpotong
            mask = cv2.dilate(mask, np.ones((grow, grow), np.uint8))
            self._zone_mask, self._zone_mask_key = mask, key
        crop = frame[y0:y1, x0:x1].copy()
        crop[self._zone_mask[y0:y1, x0:x1] == 0] = 114  # abu-abu netral seperti padding letterbox
        found = detector.detect(crop)
        kept = []
        for d in found:
            box = (d.box[0] + x0, d.box[1] + y0, d.box[2] + x0, d.box[3] + y0)
            gx, gy = (box[0] + box[2]) / 2 / w, box[3] / h
            if any(z.contains(gx, gy) for z in cal.zones):
                kept.append(Detection(box, d.score, d.cls))
        return kept, max(self._zone_area, 1.0)

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

    def save_now(self):
        self._save_state()

    def delete_state(self):
        if self._state_path is not None:
            try:
                self._state_path.unlink()
            except OSError:
                pass
