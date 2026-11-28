"""Satu perekam per kamera, plus toko indeks bersama."""
import threading

from .config import RecordingConfig, load_config
from .recorder import CameraRecorder
from .store import RecordingStore

_lock = threading.RLock()
_manager = None
_paths = {"db": None, "root": None}


def configure(db_path, root):
    """Set lokasi basis data dan folder rekaman (dipanggil dari pengaturan Django)."""
    _paths["db"], _paths["root"] = db_path, root
    reset_recording_manager()


def _effective_config() -> RecordingConfig:
    try:
        from ..services import app_settings

        return app_settings.effective_recording_config()
    except ImportError:
        return load_config()


class RecordingManager:
    def __init__(self, config=None, store=None, recorder_factory=CameraRecorder):
        self.config = config or _effective_config()
        self._store = store
        self._factory = recorder_factory
        self._recorders = {}
        self._lock = threading.RLock()

    @property
    def enabled(self):
        return self.config.enabled

    @property
    def store(self) -> RecordingStore:
        with self._lock:
            if self._store is None:
                from pathlib import Path

                root = Path(_paths["root"] or Path.cwd() / "data" / "recordings")
                db = Path(_paths["db"] or root.parent / "recordings.sqlite3")
                self._store = RecordingStore(db, root)
            return self._store

    def recorder(self, camera):
        """Perekam kamera (dibuat bila perlu). None bila perekaman dimatikan."""
        if not self.enabled:
            return None
        with self._lock:
            rec = self._recorders.get(camera)
            if rec is None:
                rec = self._recorders[camera] = self._factory(camera, self.store, self.config)
            return rec

    def is_recording(self, camera):
        rec = self._recorders.get(camera)
        return bool(rec and rec.recording)

    def stop(self, camera):
        with self._lock:
            rec = self._recorders.pop(camera, None)
        if rec is not None:
            rec.stop()

    def shutdown(self):
        with self._lock:
            codes = list(self._recorders)
        for code in codes:
            self.stop(code)
        with self._lock:
            if self._store is not None:
                self._store.close()
                self._store = None


def get_recording_manager() -> RecordingManager:
    global _manager
    with _lock:
        if _manager is None:
            _manager = RecordingManager()
        return _manager


def reset_recording_manager():
    global _manager
    with _lock:
        old, _manager = _manager, None
    if old is not None:
        old.shutdown()
