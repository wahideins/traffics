"""Tes penyimpanan kamera berbasis berkas JSON."""
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from apps.dashboard.services.camera_store import CameraStore

ARGS = dict(name="Simpang", source_url="rtsp://u:pw@10.0.0.5/x", dir_a="A", dir_b="B", speed_limit=60)


class CameraStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "data" / "cameras.json"
        self.store = CameraStore(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_kosong_bila_berkas_belum_ada(self):
        self.assertEqual(self.store.list(), [])

    def test_tambah_dan_bertahan_setelah_dimuat_ulang(self):
        cam = self.store.add(reserved_codes=["CAM-01", "CAM-02", "CAM-03"], **ARGS)
        self.assertEqual(cam.id, "CAM-04")
        again = CameraStore(self.path).get("CAM-04")
        self.assertEqual(again.source_url, ARGS["source_url"])

    def test_kode_tidak_dipakai_ulang_untuk_kode_cadangan(self):
        self.store.add(reserved_codes=["CAM-01"], **ARGS)
        second = self.store.add(reserved_codes=["CAM-01"], **ARGS)
        self.assertEqual(second.id, "CAM-03")

    def test_hapus(self):
        cam = self.store.add(**ARGS)
        self.assertTrue(self.store.delete(cam.id))
        self.assertFalse(self.store.delete(cam.id))
        self.assertEqual(self.store.list(), [])

    @unittest.skipIf(os.name == "nt", "izin POSIX")
    def test_izin_berkas_0600(self):
        self.store.add(**ARGS)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_berkas_rusak_dicadangkan_bukan_dihapus(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{bukan json")
        self.assertEqual(self.store.list(), [])
        self.assertTrue(self.path.with_suffix(".json.corrupt").exists())

    def test_repr_tidak_membocorkan_url(self):
        cam = self.store.add(**ARGS)
        self.assertNotIn("pw", repr(cam))
        self.assertNotIn("pw", cam.display_url)

    def test_tidak_ada_berkas_sementara_tersisa(self):
        self.store.add(**ARGS)
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["cameras.json"])

    def test_berkas_valid_json(self):
        self.store.add(**ARGS)
        self.assertEqual(json.loads(self.path.read_text())["version"], 1)


if __name__ == "__main__":
    unittest.main()
