"""Mengelola pipeline deteksi untuk banyak kamera."""
import logging
import threading
from pathlib import Path

from .analyzer import TrafficAnalyzer
from .calibration import from_stored
from .config import DetectionConfig, load_config
from .detector import load_detector
from .pipeline import UNAVAILABLE, DetectionPipeline, PipelineStatus

LOG = logging.getLogger(__name__)

def _effective_config():
    from ..services import app_settings

    return app_settings.effective_detection_config()


NO_MODEL = "Model deteksi belum diatur (variabel TRAFFICSENSE_MODEL)."


class DetectionManager:
    def __init__(self, config=None, *, detector_factory=load_detector, pipeline_factory=DetectionPipeline):
        self._config = config or _effective_config()
        self._detector_factory = detector_factory
        self._pipeline_factory = pipeline_factory
        self._pipelines = {}
        self._lock = threading.RLock()

    @property
    def config(self) -> DetectionConfig:
        return self._config

    @property
    def enabled(self):
        return bool(self._config.model_path)

    def ensure(self, camera):
        """Pipeline untuk kamera RTSP, dibuat dan dimulai bila perlu. None bila deteksi tidak aktif."""
        if not self.enabled:
            return None
        with self._lock:
            pipeline = self._pipelines.get(camera.id)
            if pipeline is None:
                analyzer = TrafficAnalyzer(
                    speed_limit=camera.speed_limit,
                    calibration=from_stored(camera.calibration),
                    dir_a=camera.dir_a,
                    dir_b=camera.dir_b,
                    track_max_age=self._config.track_max_age,
                    track_min_hits=self._config.track_min_hits,
                    track_high_conf=self._config.conf,
                    track_low_conf=self._config.low_conf,
                    full_occupancy=self._config.full_occupancy,
                )
                state_path = Path(self._config.state_dir) / f"{camera.id}.json" if self._config.state_dir else None
                pipeline = self._pipeline_factory(camera.id, analyzer, self._detector_factory, self._config, state_path=state_path)
                self._pipelines[camera.id] = pipeline
                pipeline.start()
            return pipeline

    def get(self, code):
        with self._lock:
            return self._pipelines.get(code)

    def status(self, code):
        """Status pipeline; bila deteksi mati secara konfigurasi, status 'unavailable' dengan alasannya."""
        pipeline = self.get(code)
        if pipeline is not None:
            return pipeline.status()
        if not self.enabled:
            return PipelineStatus(state=UNAVAILABLE, message=NO_MODEL)
        return PipelineStatus(state="loading", message="")

    def snapshot(self, code):
        pipeline = self.get(code)
        return pipeline.analyzer.snapshot() if pipeline else None

    def series(self, code, points, step_minutes):
        pipeline = self.get(code)
        return pipeline.analyzer.series(points, step_minutes) if pipeline else None

    def apply_calibration(self, camera):
        """Terapkan kalibrasi terbaru ke analyzer yang berjalan (tanpa memulai ulang stream)."""
        pipeline = self.get(camera.id)
        if pipeline is not None:
            pipeline.analyzer.set_calibration(
                from_stored(camera.calibration), dir_a=camera.dir_a, dir_b=camera.dir_b, speed_limit=camera.speed_limit
            )

    def remove(self, code, *, delete_state=False):
        with self._lock:
            pipeline = self._pipelines.pop(code, None)
        if pipeline is not None:
            pipeline.stop()
            if delete_state:
                pipeline.delete_state()

    def shutdown(self):
        with self._lock:
            codes = list(self._pipelines)
        for code in codes:
            self.remove(code)


_manager = None
_lock = threading.Lock()


def reset_detection_manager():
    """Hentikan semua pipeline dan buang singleton; pembuatan berikutnya membaca pengaturan terbaru."""
    global _manager
    with _lock:
        old, _manager = _manager, None
    if old is not None:
        old.shutdown()


def get_detection_manager() -> DetectionManager:
    global _manager
    with _lock:
        if _manager is None:
            _manager = DetectionManager()
        return _manager
