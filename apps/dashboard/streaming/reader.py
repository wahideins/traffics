"""Pembaca stream satu kamera: thread latar yang menjaga frame terbaru tetap tersedia."""
import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace

from .capture import CaptureUnavailable, open_capture
from .frames import encode_jpeg

LOG = logging.getLogger(__name__)

IDLE, CONNECTING, LIVE, ERROR, STOPPED = "idle", "connecting", "live", "error", "stopped"


@dataclass(frozen=True)
class StreamStatus:
    state: str = IDLE
    message: str = ""
    width: int = 0
    height: int = 0
    fps: float = 0.0
    frames: int = 0
    retry_in: float = 0.0
    fatal: bool = False  # True: tidak akan dicoba ulang (mis. OpenCV tidak terpasang)


_POS_MSEC = 0  # cv2.CAP_PROP_POS_MSEC


def _is_hls(url):
    from ..services.rtsp_url import is_hls_url

    return is_hls_url(url)


class RtspReader:
    """Membaca stream di thread sendiri dan menyimpan JPEG frame terbaru.

    Pesan status tidak pernah memuat URL maupun kredensial.
    `on_frame(frame)` dipanggil untuk setiap frame penuh (numpy BGR): titik
    sambung untuk modul deteksi nanti.
    """

    def __init__(self, code, url, config, *, capture_factory=open_capture, on_frame=None, annotate=None):
        self.code = code
        self._url = url
        self._config = config
        self._factory = capture_factory
        self._on_frame = on_frame
        self._annotate = annotate  # menggambar overlay pada frame sebelum di-encode

        self._cond = threading.Condition()
        self._wake = threading.Event()
        self._thread = None
        self._stopping = False
        self._reconnect = False

        self._status = StreamStatus()
        self._frame_id = 0
        self._jpeg = None
        self._clean_jpeg = None  # frame tanpa overlay, hanya di-encode bila diminta (kalibrasi)
        self._clean_until = 0.0
        self._clean_at = 0.0

        self._viewers = 0
        self._idle_since = time.monotonic()
        self.started_at = time.monotonic()

    # --- kontrol ------------------------------------------------------
    def start(self):
        with self._cond:
            if self._thread is not None:
                return
            self._thread = threading.Thread(target=self._run, name=f"rtsp-{self.code}", daemon=True)
            self._thread.start()

    def stop(self):
        with self._cond:
            self._stopping = True
            self._cond.notify_all()
        self._wake.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def reconnect(self):
        """Putuskan dan sambung ulang sekarang juga (melewati jeda percobaan)."""
        self._reconnect = True
        self._wake.set()

    @property
    def stopped(self):
        return self._stopping or (self._thread is not None and not self._thread.is_alive())

    # --- status dan frame ----------------------------------------------
    def status(self):
        with self._cond:
            return self._status

    def latest_jpeg(self):
        with self._cond:
            return self._jpeg

    def wait_for_first_frame(self, timeout):
        """Tunggu sampai ada frame pertama (pembaca baru butuh beberapa detik untuk tersambung)."""
        with self._cond:
            self._cond.wait_for(lambda: self._jpeg is not None or self._stopping, timeout)
            return self._jpeg is not None

    def latest_clean_jpeg(self, timeout=2.0):
        """Frame tanpa overlay deteksi (untuk kalibrasi). Meminta reader meng-encode-nya selama beberapa detik."""
        with self._cond:
            if self._annotate is None:
                return self._jpeg
            self._clean_until = time.monotonic() + 15.0
            self._cond.wait_for(
                lambda: self._clean_jpeg is not None and time.monotonic() - self._clean_at < 3.0, timeout
            )
            return self._clean_jpeg if self._clean_jpeg is not None else self._jpeg

    def wait_for_frame(self, last_id, timeout):
        """Tunggu frame yang lebih baru dari last_id. Kembalikan (id, jpeg) atau None."""
        with self._cond:
            self._cond.wait_for(lambda: self._frame_id != last_id or self._stopping, timeout)
            if self._frame_id != last_id and self._jpeg is not None:
                return self._frame_id, self._jpeg
            return None

    # --- penonton ------------------------------------------------------
    @contextmanager
    def viewer(self):
        with self._cond:
            self._viewers += 1
        try:
            yield
        finally:
            with self._cond:
                self._viewers -= 1
                if self._viewers == 0:
                    self._idle_since = time.monotonic()

    def idle_seconds(self):
        """Sudah berapa lama tanpa penonton (0 bila sedang ditonton)."""
        with self._cond:
            if self._viewers > 0:
                return 0.0
            return time.monotonic() - max(self._idle_since, self.started_at)

    # --- thread --------------------------------------------------------
    def _set_status(self, **changes):
        with self._cond:
            self._status = replace(self._status, **changes)
            self._cond.notify_all()

    def _pace(self, capture, origin):
        """HLS: segmen diunduh serentak lalu didekode sangat cepat. Tahan frame
        sampai waktu dinding sesuai waktu stream agar kecepatan/dwell tidak kacau."""
        try:
            pos_ms = float(capture.get(_POS_MSEC))
        except Exception:  # noqa: BLE001
            return origin
        if pos_ms != pos_ms or pos_ms <= 0:
            return origin
        now = time.monotonic()
        if origin is None:
            return (now, pos_ms)
        ahead = (pos_ms - origin[1]) / 1000.0 - (now - origin[0])
        if ahead > 0:
            self._sleep(min(ahead, 2.0))
        elif ahead < -2.0:
            return (now, pos_ms)  # tertinggal jauh: sinkron ulang
        return origin

    def _sleep(self, seconds):
        """Tidur sampai waktunya habis atau dibangunkan (stop/reconnect)."""
        self._wake.clear()
        if self._stopping or self._reconnect:
            return
        self._wake.wait(seconds)

    def _run(self):
        cfg = self._config
        delay = cfg.retry_min
        try:
            while not self._stopping:
                self._reconnect = False
                self._set_status(state=CONNECTING, message="Menghubungkan ke kamera...", retry_in=0.0)

                capture = None
                try:
                    capture = self._factory(self._url, cfg)
                except CaptureUnavailable as exc:
                    self._set_status(state=ERROR, message=str(exc), fatal=True)
                    return
                except Exception:  # noqa: BLE001 - pesan asli bisa memuat URL, jangan dilog mentah
                    LOG.warning("Kamera %s: gagal membuka stream", self.code)

                if capture is None or not capture.isOpened():
                    self._release(capture)
                    self._set_status(
                        state=ERROR,
                        message="Tidak dapat terhubung. Periksa URL, kredensial, dan jaringan.",
                        retry_in=delay,
                    )
                    self._sleep(delay)
                    delay = cfg.retry_min if self._reconnect else min(delay * 2, cfg.retry_max)
                    continue

                got_frame = self._read_loop(capture)
                self._release(capture)
                if self._stopping:
                    break
                if got_frame:
                    delay = cfg.retry_min
                self._set_status(
                    state=ERROR, message="Koneksi terputus. Mencoba lagi...", retry_in=delay, fps=0.0
                )
                self._sleep(delay)
                if self._reconnect:
                    delay = cfg.retry_min
                elif not got_frame:
                    delay = min(delay * 2, cfg.retry_max)
        finally:
            self._set_status(state=STOPPED, message="Dihentikan.")

    def _read_loop(self, capture):
        cfg = self._config
        min_interval = 1.0 / cfg.max_fps if cfg.max_fps > 0 else 0.0
        got_frame = False
        last_emit = 0.0
        fps = 0.0
        frames = 0
        window_start = time.monotonic()
        window_frames = 0

        paced = _is_hls(self._url)
        pace_origin = None  # (waktu dinding, waktu stream ms) pada frame pertama

        while not self._stopping and not self._reconnect:
            ok, frame = capture.read()
            if not ok or frame is None:
                return got_frame
            if paced:
                pace_origin = self._pace(capture, pace_origin)

            now = time.monotonic()
            frames += 1
            # fps dihitung per jendela >= 1 detik (rata-rata antar-frame sesaat
            # akan melonjak saat buffer awal dikuras).
            window_frames += 1
            if now - window_start >= 1.0:
                fps = window_frames / (now - window_start)
                window_start, window_frames = now, 0

            if not got_frame:
                got_frame = True
                height, width = frame.shape[:2]
                self._set_status(state=LIVE, message="", width=width, height=height)

            if self._on_frame is not None:
                try:
                    self._on_frame(frame)
                except Exception:  # noqa: BLE001
                    LOG.exception("Kamera %s: on_frame gagal", self.code)

            # Selalu baca semua frame (agar buffer tidak menumpuk), tapi encode hanya sesuai batas fps.
            if now - last_emit >= min_interval:
                clean = None
                if self._annotate is not None and time.monotonic() < self._clean_until:
                    try:
                        clean = encode_jpeg(frame, cfg.jpeg_quality, cfg.max_width)
                    except CaptureUnavailable:
                        clean = None
                if self._annotate is not None:
                    try:
                        self._annotate(frame)
                    except Exception:  # noqa: BLE001
                        LOG.exception("Kamera %s: annotate gagal", self.code)
                try:
                    jpeg = encode_jpeg(frame, cfg.jpeg_quality, cfg.max_width)
                except CaptureUnavailable as exc:
                    self._set_status(state=ERROR, message=str(exc), fatal=True)
                    self._stopping = True
                    return got_frame
                last_emit = now
                with self._cond:
                    self._frame_id += 1
                    self._jpeg = jpeg
                    if clean is not None:
                        self._clean_jpeg, self._clean_at = clean, time.monotonic()
                    self._status = replace(self._status, fps=round(fps, 1), frames=frames)
                    self._cond.notify_all()
        return got_frame

    @staticmethod
    def _release(capture):
        if capture is not None:
            try:
                capture.release()
            except Exception:  # noqa: BLE001
                pass
