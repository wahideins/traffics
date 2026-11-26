"""Mengelola pembaca stream untuk banyak kamera."""
import threading
import time

from .config import StreamConfig, load_config
from .reader import RtspReader


def _effective_config():
    try:
        from ..services import app_settings

        return app_settings.effective_stream_config()
    except ImportError:  # modul streaming dipakai tanpa aplikasi dashboard
        return load_config()


class StreamManager:
    """Satu RtspReader per kamera. Reader dimulai saat ada yang menonton dan
    dihentikan otomatis bila tak ada penonton selama `idle_stop_seconds`,
    supaya kamera yang tidak dibuka tidak menghabiskan CPU dan bandwidth.
    """

    def __init__(self, config=None, *, reader_factory=RtspReader, reap_interval=5.0):
        self._config = config or _effective_config()
        self._reader_factory = reader_factory
        self._readers = {}
        self._urls = {}
        self._keep = set()  # kamera yang harus terus berjalan tanpa penonton (deteksi)
        self._lock = threading.RLock()
        self._reap_interval = reap_interval
        self._reaper = None

    @property
    def config(self) -> StreamConfig:
        return self._config

    def ensure(self, code, url, *, on_frame=None, annotate=None, keep_alive=False):
        """Kembalikan reader yang berjalan untuk kamera (mulai bila perlu).

        `keep_alive=True`: jangan dihentikan saat tak ada penonton (untuk kamera yang dianalisis terus-menerus).
        `on_frame`/`annotate` hanya dipakai saat reader baru dibuat.
        """
        with self._lock:
            reader = self._readers.get(code)
            if reader is not None and (self._urls.get(code) != url or reader.stopped):
                reader.stop()
                reader = None
            if reader is None:
                extra = {}
                if on_frame is not None:
                    extra["on_frame"] = on_frame
                if annotate is not None:
                    extra["annotate"] = annotate
                reader = self._reader_factory(code, url, self._config, **extra)
                self._readers[code] = reader
                self._urls[code] = url
                reader.start()
            (self._keep.add if keep_alive else self._keep.discard)(code)
            self._ensure_reaper()
            return reader

    def get(self, code):
        with self._lock:
            return self._readers.get(code)

    def status(self, code):
        reader = self.get(code)
        return reader.status() if reader else None

    def reconnect(self, code):
        reader = self.get(code)
        if reader is None:
            return False
        reader.reconnect()
        return True

    def stop(self, code):
        with self._lock:
            reader = self._readers.pop(code, None)
            self._urls.pop(code, None)
            self._keep.discard(code)
        if reader is not None:
            reader.stop()

    def shutdown(self):
        with self._lock:
            codes = list(self._readers)
        for code in codes:
            self.stop(code)

    # --- pembersih -----------------------------------------------------
    def reap_idle(self):
        """Hentikan reader yang tak ditonton melebihi batas. Kembalikan kode yang dihentikan."""
        limit = self._config.idle_stop_seconds
        with self._lock:
            idle = [code for code, reader in self._readers.items() if code not in self._keep and reader.idle_seconds() > limit]
        for code in idle:
            self.stop(code)
        return idle

    def _ensure_reaper(self):
        if self._reaper is not None and self._reaper.is_alive():
            return
        self._reaper = threading.Thread(target=self._reap_loop, name="rtsp-reaper", daemon=True)
        self._reaper.start()

    def _reap_loop(self):
        while True:
            time.sleep(self._reap_interval)
            self.reap_idle()


_manager = None
_manager_lock = threading.Lock()


def reset_manager():
    """Hentikan semua pembaca dan buang singleton (dipakai saat pengaturan stream berubah)."""
    global _manager
    with _manager_lock:
        old, _manager = _manager, None
    if old is not None:
        old.shutdown()


def get_manager() -> StreamManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = StreamManager()
        return _manager
