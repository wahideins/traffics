"""Perekam satu kamera: frame masuk lewat antrean, ditulis oleh thread sendiri agar
pembacaan stream dan deteksi tidak terhambat encode video."""
import logging
import queue
import threading
import time
from datetime import datetime

from .writers import WriterError, default_writer_factory

LOG = logging.getLogger(__name__)
_STOP = object()


def _even(n):
    return max(2, int(n) // 2 * 2)


class CameraRecorder:
    def __init__(self, camera, store, config, *, writer_factory=default_writer_factory, clock=time.time, mono=time.monotonic):
        self.camera = camera
        self._store = store
        self._cfg = config
        self._factory = writer_factory
        self._clock = clock
        self._mono = mono
        self._q = queue.Queue(maxsize=config.queue_size)
        self._interval = 1.0 / max(config.record_fps, 0.1)
        self._last_accept = 0.0
        self.dropped = 0
        self.errors = 0
        self._writer = None
        self._rec_id = None
        self._frames = 0
        self._seg_start = 0.0
        self._size = None
        self._thread = threading.Thread(target=self._run, name=f"rec-{camera}", daemon=True)
        self._thread.start()

    # --- dipanggil dari thread pembaca --------------------------------------
    def submit(self, frame):
        now = self._mono()
        if now - self._last_accept < self._interval:
            return
        self._last_accept = now
        h, w = frame.shape[:2]
        limit = self._cfg.record_max_width
        if limit and w > limit:
            import cv2

            frame = cv2.resize(frame, (limit, int(h * limit / w)), interpolation=cv2.INTER_AREA)
        else:
            frame = frame.copy()  # frame asli masih digambari overlay setelah ini
        try:
            self._q.put_nowait(frame)
        except queue.Full:
            self.dropped += 1

    def stop(self, timeout=20.0):
        try:
            self._q.put(_STOP, timeout=2)
        except queue.Full:
            pass
        self._thread.join(timeout)

    @property
    def recording(self):
        return self._writer is not None

    # --- thread penulis -------------------------------------------------------
    def _run(self):
        try:
            while True:
                try:
                    item = self._q.get(timeout=1.0)
                except queue.Empty:
                    if self._writer is not None and self._mono() - self._last_write > self._cfg.idle_close_seconds:
                        self._close("done")
                    continue
                if item is _STOP:
                    break
                self._write(item)
        finally:
            self._close("done")

    _last_write = 0.0

    def _write(self, frame):
        h, w = frame.shape[:2]
        size = (_even(w), _even(h))
        if self._writer is not None and (size != self._size or self._clock() - self._seg_start >= self._cfg.record_segment_minutes * 60):
            self._close("done")
        if self._writer is None and not self._open(size):
            return
        if (w, h) != size:
            frame = frame[: size[1], : size[0]]
        try:
            self._writer.write(frame)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("Kamera %s: gagal menulis rekaman (%s)", self.camera, exc)
            self.errors += 1
            self._close("error")
            return
        self._frames += 1
        self._last_write = self._mono()

    def _open(self, size):
        started = self._clock()
        stamp = datetime.fromtimestamp(started)
        rel = f"{self.camera}/{stamp:%Y%m%d}/{self.camera}_{stamp:%H%M%S}.mp4"
        path = self._store.full_path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._writer = self._factory(path, size[0], size[1], self._cfg.record_fps)
        except (WriterError, OSError, ImportError) as exc:
            LOG.warning("Kamera %s: tidak bisa mulai merekam (%s)", self.camera, exc)
            self.errors += 1
            self._writer = None
            time.sleep(1.0)  # jangan memukul ffmpeg yang rusak tiap frame
            return False
        self._size, self._frames, self._seg_start = size, 0, started
        self._rec_id = self._store.start(self.camera, started, rel, size[0], size[1], self._cfg.record_fps,
                                         getattr(self._writer, "codec", ""))
        self._last_write = self._mono()
        return True

    def _close(self, status):
        if self._writer is None:
            return
        try:
            self._writer.close()
        except Exception:  # noqa: BLE001
            LOG.exception("Kamera %s: gagal menutup berkas rekaman", self.camera)
        self._writer = None
        if self._rec_id is not None:
            self._store.finish(self._rec_id, self._clock(), self._frames, status if self._frames else "empty")
            if not self._frames:
                self._store.delete(self._rec_id)
        self._rec_id = None
        limit = int(self._cfg.record_max_gb * 1024 ** 3)
        if limit > 0:
            self._store.enforce_limit(limit)
