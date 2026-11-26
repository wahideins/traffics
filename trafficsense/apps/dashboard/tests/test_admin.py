"""Tes pengaturan admin: validasi, penyimpanan, konfigurasi efektif, akses, dan tindakan."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from apps.dashboard.services import admin_actions, app_settings
from apps.dashboard.services.admin_access import (
    FORBIDDEN, LOGIN, OK, LoginThrottle, decide, password_matches,
)

try:
    import onnxruntime  # noqa: F401
    import numpy  # noqa: F401
    HAVE_ORT = True
except ImportError:  # pragma: no cover
    HAVE_ORT = False


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.store = app_settings.SettingsStore(self.dir / "settings.json", self.dir / "models")

    def tearDown(self):
        self.tmp.cleanup()

    def test_validasi_dan_satuan_persen(self):
        values, errors = self.store.validate({"conf": "0,5", "full_occupancy": "25", "imgsz": "960", "provider": "dml"})
        self.assertEqual(errors, {})
        self.assertEqual(values, {"conf": 0.5, "full_occupancy": 0.25, "imgsz": 960, "provider": "dml"})

    def test_galat_per_kolom(self):
        _, errors = self.store.validate({"conf": "2", "max_width": "abc", "provider": "tpu", "track_min_hits": "2,5", "detect_fps": "0"})
        self.assertEqual(set(errors), {"conf", "max_width", "provider", "track_min_hits", "detect_fps"})
        self.assertIn("antara", errors["conf"])

    def test_kolom_kosong_berarti_bawaan(self):
        values, errors = self.store.validate({"conf": "", "imgsz": ""})
        self.assertEqual((values, errors), ({}, {}))

    def test_model_harus_ada_di_folder(self):
        _, errors = self.store.validate({"model": "../../etc/passwd"})
        self.assertIn("model", errors)
        self.store.models_dir.mkdir(parents=True)
        (self.store.models_dir / "a.onnx").write_bytes(b"x")
        values, errors = self.store.validate({"model": "a.onnx"})
        self.assertEqual(values, {"model": "a.onnx"})

    def test_simpan_dan_konfigurasi_efektif(self):
        self.store.save({"conf": 0.5, "full_occupancy": 0.25, "max_width": 800, "transport": "udp"})
        det, stream = self.store.detection_config(), self.store.stream_config()
        self.assertEqual((det.conf, det.full_occupancy), (0.5, 0.25))
        self.assertEqual((stream.max_width, stream.transport), (800, "udp"))
        self.assertEqual(det.detect_fps, 5.0)  # tak diubah -> bawaan

    def test_lingkungan_dikalahkan_pengaturan_tersimpan(self):
        with mock.patch.dict(os.environ, {"TRAFFICSENSE_DETECT_CONF": "0.6", "TRAFFICSENSE_DETECT_FPS": "7"}):
            self.assertEqual(self.store.detection_config().conf, 0.6)
            self.store.save({"conf": 0.4})
            cfg = self.store.detection_config()
            self.assertEqual((cfg.conf, cfg.detect_fps), (0.4, 7.0))

    def test_nilai_rusak_atau_asing_dibuang(self):
        self.store.save({"conf": 9, "bogus": 1, "imgsz": 960, "provider": "tpu"})
        self.assertEqual(self.store.overrides(), {"imgsz": 960})
        self.store.path.write_text("{rusak")
        self.assertEqual(self.store.overrides(), {})

    def test_model_hilang_jatuh_ke_lingkungan(self):
        self.store.save({"model": "hilang.onnx"})
        with mock.patch.dict(os.environ, {"TRAFFICSENSE_MODEL": "/env/m.onnx"}):
            self.assertEqual(self.store.detection_config().model_path, "/env/m.onnx")

    def test_model_dipilih_menjadi_jalur_penuh(self):
        self.store.models_dir.mkdir(parents=True)
        (self.store.models_dir / "a.onnx").write_bytes(b"x")
        self.store.save({"model": "a.onnx"})
        self.assertEqual(self.store.detection_config().model_path, str(self.store.models_dir / "a.onnx"))

    def test_describe_menandai_sumber_nilai(self):
        self.store.save({"conf": 0.5})
        fields = {f["key"]: f for s in self.store.describe() for f in s["fields"]}
        self.assertEqual(fields["conf"]["source"], "disimpan")
        self.assertEqual(fields["conf"]["value"], "0,5")
        self.assertEqual(fields["nms_iou"]["source"], "bawaan")
        self.assertEqual(fields["full_occupancy"]["value"], "30")  # tampil dalam persen
        self.assertTrue(any(c["selected"] for c in fields["provider"]["choices"]))


class AccessTests(unittest.TestCase):
    def test_tanpa_sandi_hanya_localhost(self):
        kw = dict(password_set=False, forwarded=False, authenticated=False)
        self.assertEqual(decide(remote_addr="127.0.0.1", **kw), OK)
        self.assertEqual(decide(remote_addr="::1", **kw), OK)
        self.assertEqual(decide(remote_addr="192.168.1.9", **kw), FORBIDDEN)
        self.assertEqual(decide(remote_addr=None, **kw), FORBIDDEN)

    def test_localhost_lewat_proxy_ditolak(self):
        self.assertEqual(decide(password_set=False, remote_addr="127.0.0.1", forwarded=True, authenticated=False), FORBIDDEN)

    def test_dengan_sandi_wajib_login(self):
        self.assertEqual(decide(password_set=True, remote_addr="192.168.1.9", forwarded=False, authenticated=False), LOGIN)
        self.assertEqual(decide(password_set=True, remote_addr="192.168.1.9", forwarded=False, authenticated=True), OK)

    def test_sandi(self):
        self.assertTrue(password_matches("rahasia", "rahasia"))
        self.assertFalse(password_matches("salah", "rahasia"))
        self.assertFalse(password_matches("", ""))
        self.assertFalse(password_matches("x", ""))

    def test_pembatas_percobaan(self):
        now = [0.0]
        t = LoginThrottle(max_failures=3, window=60, clock=lambda: now[0])
        for _ in range(3):
            self.assertTrue(t.allowed("ip"))
            t.fail("ip")
        self.assertFalse(t.allowed("ip"))
        self.assertTrue(t.allowed("lain"))
        now[0] = 61
        self.assertTrue(t.allowed("ip"))
        t.fail("ip"); t.reset("ip")
        self.assertTrue(t.allowed("ip"))


class ActionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        app_settings.configure(base / "settings.json", base / "models")
        patcher = mock.patch("apps.dashboard.services.admin_actions.runtime.restart_all")
        self.restart = patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        app_settings.configure(Path.cwd() / "data" / "settings.json", Path.cwd() / "data" / "models")
        self.tmp.cleanup()

    def test_apply_menyimpan_dan_memulai_ulang(self):
        result, errors = admin_actions.apply_settings({"conf": "0,5", "imgsz": "960"})
        self.assertEqual(errors, {})
        self.assertTrue(result["restarted"])
        self.assertEqual(app_settings.get_store().overrides(), {"conf": 0.5, "imgsz": 960})
        self.restart.assert_called_once()

    def test_apply_tanpa_perubahan_tidak_memulai_ulang(self):
        admin_actions.apply_settings({"conf": "0,5"})
        self.restart.reset_mock()
        result, _ = admin_actions.apply_settings({"conf": "0,5"})
        self.assertFalse(result["restarted"])
        self.restart.assert_not_called()

    def test_apply_galat_tidak_menyimpan(self):
        result, errors = admin_actions.apply_settings({"conf": "5"})
        self.assertIsNone(result)
        self.assertIn("conf", errors)
        self.assertEqual(app_settings.get_store().overrides(), {})
        self.restart.assert_not_called()

    def test_mengosongkan_semua_menghapus_berkas(self):
        admin_actions.apply_settings({"conf": "0,5"})
        admin_actions.apply_settings({"conf": ""})
        self.assertFalse(app_settings.get_store().path.exists())

    def test_set_model_hanya_dari_folder(self):
        from apps.dashboard.detection.model_tools import ModelError

        with self.assertRaises(ModelError):
            admin_actions.set_active_model("../x.onnx")
        with self.assertRaises(ModelError):
            admin_actions.set_active_model("tidak-ada.onnx")

    @unittest.skipUnless(HAVE_ORT, "onnxruntime tidak terpasang")
    def test_unggah_uji_pilih_hapus(self):
        from apps.dashboard.detection.model_tools import ModelError
        from apps.dashboard.tests.onnx_builder import build_constant_yolo_model

        data = build_constant_yolo_model()
        info = admin_actions.upload_model("kecil.onnx", iter([data]))
        self.assertEqual(info["layout"].split()[0], "YOLOv8/v11")
        admin_actions.set_active_model("kecil.onnx")
        self.assertEqual(app_settings.get_store().overrides()["model"], "kecil.onnx")
        with self.assertRaises(ModelError):
            admin_actions.remove_model("kecil.onnx")  # sedang aktif
        self.assertEqual(admin_actions.test_model("kecil.onnx")["output"], [1, 84, 8400])

    @unittest.skipUnless(HAVE_ORT, "onnxruntime tidak terpasang")
    def test_unggahan_rusak_dihapus_otomatis(self):
        from apps.dashboard.detection.model_tools import ModelError

        with self.assertRaises(ModelError):
            admin_actions.upload_model("rusak.onnx", iter([b"bukan model"]))
        self.assertEqual(app_settings.get_store().model_names(), [])

    def test_info_sistem(self):
        info = admin_actions.system_info()
        self.assertIn("Python", info)
        self.assertIn("Folder model", info)


if __name__ == "__main__":
    unittest.main()
