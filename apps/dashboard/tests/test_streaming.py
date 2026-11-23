"""Tes pembaca stream dengan capture palsu (tanpa jaringan). Dilewati bila numpy/cv2 tidak ada."""
import time
import unittest

try:
    import numpy as np
    import cv2  # noqa: F401
except ImportError:  # pragma: no cover
    np = None

from apps.dashboard.streaming.config import StreamConfig
from apps.dashboard.streaming.manager import StreamManager
from apps.dashboard.streaming.reader import RtspReader

CFG = StreamConfig(max_fps=100, retry_min=0.05, retry_max=0.1, idle_stop_seconds=0.2)


class FakeCapture:
    def __init__(self, frames=None, opened=True):
        self.frames, self.opened, self.released = frames, opened, False

    def isOpened(self):
        return self.opened

    def read(self):
        if self.frames is None or self.frames <= 0:
            time.sleep(0.01)
            return False, None
        self.frames -= 1
        time.sleep(0.005)
        return True, np.zeros((72, 128, 3), dtype=np.uint8)

    def release(self):
        self.released = True


def wait_for(predicate, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


@unittest.skipIf(np is None, "numpy/opencv tidak terpasang")
class ReaderTests(unittest.TestCase):
    def test_menjadi_live_dan_menyimpan_jpeg(self):
        reader = RtspReader("CAM-X", "rtsp://secret:pw@h/x", CFG, capture_factory=lambda u, c: FakeCapture(frames=10**6))
        reader.start()
        try:
            self.assertTrue(wait_for(lambda: reader.status().state == "live"))
            self.assertTrue(wait_for(lambda: reader.latest_jpeg() is not None))
            self.assertTrue(reader.latest_jpeg().startswith(b"\xff\xd8"))
            self.assertEqual((reader.status().width, reader.status().height), (128, 72))
        finally:
            reader.stop()
        self.assertEqual(reader.status().state, "stopped")

    def test_gagal_buka_menjadi_error_tanpa_membocorkan_url(self):
        reader = RtspReader("CAM-X", "rtsp://secret:pw@h/x", CFG, capture_factory=lambda u, c: FakeCapture(opened=False))
        reader.start()
        try:
            self.assertTrue(wait_for(lambda: reader.status().state == "error"))
            self.assertNotIn("pw", reader.status().message)
            self.assertNotIn("secret", reader.status().message)
        finally:
            reader.stop()

    def test_putus_lalu_sambung_ulang(self):
        calls = []

        def factory(url, cfg):
            calls.append(1)
            return FakeCapture(frames=5 if len(calls) == 1 else 10**6)

        reader = RtspReader("CAM-X", "rtsp://h/x", CFG, capture_factory=factory)
        reader.start()
        try:
            self.assertTrue(wait_for(lambda: len(calls) >= 2, 5))
            self.assertTrue(wait_for(lambda: reader.status().state == "live"))
        finally:
            reader.stop()

    def test_reconnect_manual(self):
        calls = []
        reader = RtspReader("CAM-X", "rtsp://h/x", CFG, capture_factory=lambda u, c: (calls.append(1), FakeCapture(frames=10**6))[1])
        reader.start()
        try:
            self.assertTrue(wait_for(lambda: reader.status().state == "live"))
            reader.reconnect()
            self.assertTrue(wait_for(lambda: len(calls) >= 2))
        finally:
            reader.stop()


@unittest.skipIf(np is None, "numpy/opencv tidak terpasang")
class ManagerTests(unittest.TestCase):
    def _manager(self):
        return StreamManager(
            CFG,
            reader_factory=lambda code, url, cfg: RtspReader(code, url, cfg, capture_factory=lambda u, c: FakeCapture(frames=10**6)),
            reap_interval=0.05,
        )

    def test_ensure_memakai_ulang_pembaca(self):
        m = self._manager()
        try:
            self.assertIs(m.ensure("CAM-A", "rtsp://h/x"), m.ensure("CAM-A", "rtsp://h/x"))
        finally:
            m.shutdown()

    def test_url_berubah_membuat_pembaca_baru(self):
        m = self._manager()
        try:
            a = m.ensure("CAM-A", "rtsp://h/x")
            b = m.ensure("CAM-A", "rtsp://h/y")
            self.assertIsNot(a, b)
        finally:
            m.shutdown()

    def test_pembaca_tanpa_penonton_dihentikan(self):
        m = self._manager()
        try:
            r = m.ensure("CAM-A", "rtsp://h/x")
            self.assertTrue(wait_for(lambda: m.get("CAM-A") is None, 3))
            self.assertTrue(r.stopped)
        finally:
            m.shutdown()

    def test_pembaca_dengan_penonton_tetap_hidup(self):
        m = self._manager()
        try:
            r = m.ensure("CAM-A", "rtsp://h/x")
            with r.viewer():
                time.sleep(0.6)
                self.assertIsNotNone(m.get("CAM-A"))
        finally:
            m.shutdown()


if __name__ == "__main__":
    unittest.main()
