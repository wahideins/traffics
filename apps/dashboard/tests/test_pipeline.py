"""Tes pipeline: thread, penjatuhan frame, status model tak tersedia, penyimpanan keadaan."""
import tempfile
import time
import unittest
from pathlib import Path

try:
    import numpy as np
    import cv2  # noqa: F401
except ImportError:  # pragma: no cover
    np = None

from apps.dashboard.detection.analyzer import TrafficAnalyzer
from apps.dashboard.detection.config import DetectionConfig
from apps.dashboard.detection.detector import DetectorUnavailable
from apps.dashboard.detection.manager import DetectionManager
from apps.dashboard.detection.pipeline import DetectionPipeline
from apps.dashboard.services.camera_store import LiveCamera
from apps.dashboard.tests.test_detection import calibrated, car

CFG = DetectionConfig(detect_fps=1000.0, state_dir="")
CAM = LiveCamera(id="CAM-04", name="Uji", short="Uji", source_url="rtsp://h/x", speed_limit=60,
                 dir_a="A", dir_b="B", created_at="2026-01-01T00:00:00+00:00")


def wait_for(pred, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


class FakeDetector:
    def __init__(self, delay=0.0):
        self.calls, self.delay = 0, delay

    def detect(self, frame):
        self.calls += 1
        time.sleep(self.delay)
        return [car(100 + self.calls * 30, 400)]


@unittest.skipIf(np is None, "numpy/opencv tidak terpasang")
class PipelineTests(unittest.TestCase):
    def _pipeline(self, factory, state_path=None):
        analyzer = TrafficAnalyzer(speed_limit=60, calibration=calibrated())
        return DetectionPipeline("CAM-04", analyzer, factory, CFG, state_path=state_path)

    def test_memproses_frame_dan_menjadi_running(self):
        det = FakeDetector()
        p = self._pipeline(lambda cfg: det)
        p.start()
        try:
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            self.assertTrue(wait_for(lambda: (p.submit(frame), det.calls >= 3)[1]))
            self.assertEqual(p.status().state, "running")
            self.assertTrue(p.analyzer.snapshot()["ready"])
        finally:
            p.stop()
        self.assertEqual(p.status().state, "stopped")

    def test_frame_dijatuhkan_saat_sibuk(self):
        det = FakeDetector(delay=0.2)
        p = self._pipeline(lambda cfg: det)
        p.start()
        try:
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            self.assertTrue(wait_for(lambda: p.status().state == "running"))
            for _ in range(200):
                p.submit(frame)
                time.sleep(0.001)
            self.assertLessEqual(det.calls, 3)  # ~0,2 dtk per inferensi, bukan 200
        finally:
            p.stop()

    def test_model_tak_tersedia(self):
        def factory(cfg):
            raise DetectorUnavailable("Model tidak ada.")

        p = self._pipeline(factory)
        p.start()
        try:
            self.assertTrue(wait_for(lambda: p.status().state == "unavailable"))
            self.assertEqual(p.status().message, "Model tidak ada.")
            self.assertFalse(p.active)
        finally:
            p.stop()

    def test_galat_inferensi_tidak_mematikan_thread(self):
        class Flaky:
            n = 0

            def detect(self, frame):
                Flaky.n += 1
                if Flaky.n <= 2:
                    raise RuntimeError("rusak")
                return []

        p = self._pipeline(lambda cfg: Flaky())
        p.start()
        try:
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            self.assertTrue(wait_for(lambda: (p.submit(frame), Flaky.n >= 4)[1]))
            self.assertEqual(p.status().state, "running")
        finally:
            p.stop()

    def test_keadaan_disimpan_dan_dipulihkan(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "analytics" / "CAM-04.json"
            p1 = self._pipeline(lambda cfg: FakeDetector(), state_path=path)
            p1.analyzer._counts["a"]["mobil"] = 7
            p1.start()
            self.assertTrue(wait_for(lambda: p1.status().state == "running"))
            p1.stop()
            self.assertTrue(path.exists())
            p2 = self._pipeline(lambda cfg: FakeDetector(), state_path=path)
            p2.start()
            try:
                self.assertTrue(wait_for(lambda: p2.analyzer.snapshot()["counts"]["a"]["mobil"] == 7))
            finally:
                p2.stop()
            p2.delete_state()
            self.assertFalse(path.exists())

    def test_annotate_menggambar_kotak(self):
        p = self._pipeline(lambda cfg: FakeDetector())
        p.start()
        try:
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            for _ in range(8):
                p.submit(frame)
                time.sleep(0.02)
            self.assertTrue(wait_for(lambda: p.analyzer.overlay()[0] != []))
            canvas = np.zeros((720, 1280, 3), dtype=np.uint8)
            p.annotate(canvas)
            self.assertGreater(int(canvas.sum()), 0)
        finally:
            p.stop()


@unittest.skipIf(np is None, "numpy/opencv tidak terpasang")
class ManagerTests(unittest.TestCase):
    def test_tanpa_model_nonaktif_dengan_alasan(self):
        m = DetectionManager(DetectionConfig(model_path=""))
        self.assertFalse(m.enabled)
        self.assertIsNone(m.ensure(CAM))
        self.assertEqual(m.status("CAM-04").state, "unavailable")
        self.assertIn("TRAFFICSENSE_MODEL", m.status("CAM-04").message)

    def test_dengan_model_membuat_satu_pipeline_per_kamera(self):
        m = DetectionManager(DetectionConfig(model_path="x.onnx", state_dir=""), detector_factory=lambda cfg: FakeDetector())
        try:
            p = m.ensure(CAM)
            self.assertIs(p, m.ensure(CAM))
            self.assertTrue(wait_for(lambda: p.status().state == "running"))
        finally:
            m.shutdown()
        self.assertIsNone(m.get("CAM-04"))

    def test_kalibrasi_diterapkan_ke_analyzer_berjalan(self):
        m = DetectionManager(DetectionConfig(model_path="x.onnx", state_dir=""), detector_factory=lambda cfg: FakeDetector())
        try:
            p = m.ensure(CAM)
            from dataclasses import replace
            updated = replace(CAM, calibration=calibrated(one_way=True).to_dict())
            m.apply_calibration(updated)
            self.assertTrue(p.analyzer.calibration.one_way)
        finally:
            m.shutdown()


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(np is None, "numpy/opencv tidak terpasang")
class ZonesOnlyTests(unittest.TestCase):
    SQUARE = [[0.2, 0.5], [0.6, 0.5], [0.6, 0.9], [0.2, 0.9]]

    def _pipeline(self, zones_only=True):
        from apps.dashboard.detection.calibration import parse_calibration
        data = {**calibrated().to_dict(), "zones": [{"name": "Z", "color": "#3d8cff", "points": self.SQUARE}],
                "zones_only": zones_only}
        cal, errors = parse_calibration(data)
        self.assertEqual(errors, {})
        return DetectionPipeline("CAM-04", TrafficAnalyzer(speed_limit=60, calibration=cal), lambda c: None, CFG)

    def test_crop_topeng_saring_dan_geser_koordinat(self):
        seen = {}

        class Det:
            def detect(self, frame):
                seen["shape"] = frame.shape
                seen["outside_gray"] = bool((frame[0, 0] == 114).all())
                seen["inside_kept"] = bool((frame[frame.shape[0] // 2, frame.shape[1] // 2] == 255).all())
                h, w = frame.shape[:2]
                from apps.dashboard.detection.types import Detection
                # satu kendaraan di dalam zona (tapak di tengah crop), satu di sudut luar zona
                return [Detection((w * 0.4, h * 0.3, w * 0.6, h * 0.6), 0.9, "mobil"),
                        Detection((0, 0, 20, 20), 0.9, "motor")]

        p = self._pipeline()
        frame = np.full((720, 1280, 3), 255, dtype=np.uint8)
        dets, area = p._detect_in_zones(Det(), frame, p.analyzer.calibration)
        self.assertEqual([d.cls for d in dets], ["mobil"])
        self.assertLess(seen["shape"][0] * seen["shape"][1], 720 * 1280 * 0.35)  # jauh lebih kecil dari frame penuh
        self.assertTrue(seen["outside_gray"])
        self.assertTrue(seen["inside_kept"])
        x1, y1, x2, y2 = dets[0].box
        self.assertTrue(0.2 * 1280 <= (x1 + x2) / 2 <= 0.6 * 1280 and y2 <= 0.9 * 720 + 20)
        self.assertAlmostEqual(area, 0.4 * 0.4 * 1280 * 720, delta=0.02 * 1280 * 720)

    def test_dimatikan_memakai_frame_penuh(self):
        class Det:
            shape = None

            def detect(self, frame):
                Det.shape = frame.shape
                return []

        p = self._pipeline(zones_only=False)
        _, area = p._detect_in_roi(Det(), np.zeros((720, 1280, 3), dtype=np.uint8))
        self.assertEqual(Det.shape, (720, 1280, 3))
        self.assertEqual(area, 720 * 1280)
