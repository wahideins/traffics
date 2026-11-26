"""Tes alat model dengan ONNX sungguhan (dibuat tangan) lewat onnxruntime. Dilewati bila ORT/numpy tak ada."""
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
    import onnxruntime  # noqa: F401
except ImportError:  # pragma: no cover
    np = None

from apps.dashboard.detection.config import DetectionConfig
from apps.dashboard.detection.model_tools import (
    ModelError, check_name, classify_output, delete_model, inspect_model, list_models, save_model,
)

if np is not None:
    from apps.dashboard.detection.detector import YoloOnnxDetector
    from apps.dashboard.tests.onnx_builder import build_constant_yolo_model


class NameAndLayoutTests(unittest.TestCase):
    def test_nama_aman(self):
        self.assertEqual(check_name("yolov8n.onnx"), "yolov8n.onnx")
        for bad in ("../x.onnx", "a/b.onnx", "x.pt", "x.onnx.exe", ".onnx", "a b.onnx", "", None, "x\\y.onnx"):
            with self.assertRaises(ModelError, msg=str(bad)):
                check_name(bad)

    def test_tata_letak(self):
        self.assertEqual(classify_output([1, 84, 8400])[1], 80)
        self.assertEqual(classify_output([1, 8400, 84])[1], 80)
        self.assertEqual(classify_output([1, 300, 6])[0].split()[0], "end-to-end")
        self.assertEqual(classify_output([1, "x", "y"])[0], "tidak dikenali")
        self.assertEqual(classify_output([1, 5, 8400])[1], 1)


@unittest.skipIf(np is None, "numpy/onnxruntime tidak terpasang")
class RealOnnxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _model(self, name="tiny.onnx", **kw):
        path = self.dir / name
        path.write_bytes(build_constant_yolo_model(**kw))
        return path

    def test_detektor_asli_memetakan_koordinat_ke_frame(self):
        path = self._model()
        det = YoloOnnxDetector(DetectionConfig(model_path=str(path)))
        result = det.detect(np.zeros((720, 1280, 3), dtype=np.uint8))
        self.assertEqual([d.cls for d in result], ["mobil"])
        x1, y1, x2, y2 = result[0].box
        self.assertAlmostEqual(x1, 540, delta=1)
        self.assertAlmostEqual(x2, 740, delta=1)
        self.assertAlmostEqual(y1, 300, delta=1)
        self.assertAlmostEqual(y2, 420, delta=1)
        self.assertEqual(det.provider, "cpu")

    def test_detektor_asli_end_to_end(self):
        path = self._model(layout="e2e", boxes=((320.0, 320.0, 100.0, 60.0, 7, 0.8),))
        det = YoloOnnxDetector(DetectionConfig(model_path=str(path)))
        self.assertEqual([d.cls for d in det.detect(np.zeros((720, 1280, 3), dtype=np.uint8))], ["truk"])

    def test_inspect_model(self):
        info = inspect_model(self._model(), DetectionConfig())
        self.assertEqual(info["input"], [1, 3, 640, 640])
        self.assertEqual(info["output"], [1, 84, 8400])
        self.assertEqual(info["provider"], "CPU")
        self.assertGreater(info["ms"], 0)
        self.assertEqual(info["warnings"], [])

    def test_inspect_menandai_model_bukan_coco(self):
        info = inspect_model(self._model(nc=3, boxes=((100.0, 100.0, 50.0, 50.0, 1, 0.9),)), DetectionConfig())
        self.assertIn("3 kelas", info["warnings"][0])

    def test_berkas_rusak_ditolak_dengan_pesan(self):
        bad = self.dir / "rusak.onnx"
        bad.write_bytes(b"bukan onnx")
        with self.assertRaises(ModelError):
            inspect_model(bad, DetectionConfig())

    def test_simpan_daftar_hapus(self):
        data = build_constant_yolo_model()
        saved = save_model(self.dir / "models", "baru.onnx", iter([data[:1000], data[1000:]]))
        self.assertEqual([m["name"] for m in list_models(self.dir / "models")], ["baru.onnx"])
        self.assertEqual(saved.read_bytes(), data)
        with self.assertRaises(ModelError):
            save_model(self.dir / "models", "baru.onnx", iter([b"x"]))  # sudah ada
        with self.assertRaises(ModelError):
            delete_model(self.dir / "models", "baru.onnx", active_name="baru.onnx")
        delete_model(self.dir / "models", "baru.onnx")
        self.assertEqual(list_models(self.dir / "models"), [])

    def test_unggah_terlalu_besar_tidak_meninggalkan_sisa(self):
        with self.assertRaises(ModelError):
            save_model(self.dir / "models", "besar.onnx", iter([b"x" * 600, b"x" * 600]), max_bytes=1000)
        self.assertEqual(list((self.dir / "models").iterdir()), [])

    def test_unggah_kosong_ditolak(self):
        with self.assertRaises(ModelError):
            save_model(self.dir / "models", "kosong.onnx", iter([]))
        self.assertEqual(list((self.dir / "models").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
