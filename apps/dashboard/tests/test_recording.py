"""Tes perekaman: indeks SQLite, perekam segmen, Range, dan penulis video sungguhan."""
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

from apps.dashboard.recording.config import RecordingConfig
from apps.dashboard.recording.recorder import CameraRecorder
from apps.dashboard.recording.store import RecordingStore
from apps.dashboard.services.app_settings import SettingsStore
from apps.dashboard.services.recordings_view import human_size, parse_range


class FakeWriter:
    codec = "h264"

    def __init__(self, path, w, h, fps, log):
        self.path, self.log = path, log
        Path(path).write_bytes(b"")
        log.append(("open", w, h))

    def write(self, frame):
        with open(self.path, "ab") as fh:
            fh.write(b"x" * 10)

    def close(self):
        self.log.append(("close",))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = RecordingStore(Path(self.tmp) / "r.sqlite3", Path(self.tmp) / "rec")

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)


class StoreTests(Base):
    def _make(self, camera="CAM", t=1000.0, size=100):
        rel = f"{camera}/{int(t)}.mp4"
        path = self.store.full_path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        rid = self.store.start(camera, t, rel, 640, 360, 10, "h264")
        self.store.finish(rid, t + 60, 600)
        return rid

    def test_catat_dan_baca(self):
        rid = self._make()
        rec = self.store.get(rid)
        self.assertEqual((rec["status"], rec["frames"], rec["size_bytes"]), ("done", 600, 100))
        self.assertAlmostEqual(rec["duration"], 60.0)

    def test_hapus_menghapus_berkas(self):
        rid = self._make()
        path = self.store.full_path(self.store.get(rid)["path"])
        self.assertTrue(self.store.delete(rid))
        self.assertFalse(path.exists())
        self.assertIsNone(self.store.get(rid))

    def test_tidak_bisa_hapus_yang_sedang_direkam(self):
        rid = self.store.start("CAM", 1.0, "CAM/a.mp4", 1, 1, 1, "h264")
        self.assertFalse(self.store.delete(rid))

    def test_batas_penyimpanan_hapus_tertua(self):
        old, mid, new = (self._make(t=t, size=100) for t in (1000.0, 2000.0, 3000.0))
        self.assertEqual(self.store.enforce_limit(250), 1)
        self.assertIsNone(self.store.get(old))
        self.assertIsNotNone(self.store.get(mid))
        self.assertIsNotNone(self.store.get(new))

    def test_pemulihan_setelah_mati_mendadak(self):
        rel = "CAM/a.mp4"
        path = self.store.full_path(rel)
        path.parent.mkdir(parents=True)
        path.write_bytes(b"x" * 55)
        rid = self.store.start("CAM", 1.0, rel, 1, 1, 1, "h264")
        db, root = self.store.db_path, self.store.root
        self.store.close()
        self.store = RecordingStore(db, root)
        rec = self.store.get(rid)
        self.assertEqual((rec["status"], rec["size_bytes"]), ("interrupted", 55))

    def test_path_traversal_ditolak(self):
        with self.assertRaises(ValueError):
            self.store.full_path("../../etc/passwd")

    def test_daftar_terbaru_dulu_dan_per_kamera(self):
        a = self._make("A", 1000.0)
        b = self._make("B", 2000.0)
        self.assertEqual([r["id"] for r in self.store.list()], [b, a])
        self.assertEqual([r["id"] for r in self.store.list(camera="A")], [a])


class RecorderTests(Base):
    def setUp(self):
        super().setUp()
        self.log = []
        self.now = [1_800_000_000.0]
        self.mono = [0.0]

    def make(self, **kw):
        cfg = RecordingConfig(record_fps=10, record_segment_minutes=1, record_max_gb=0, idle_close_seconds=0.2, **kw)
        return CameraRecorder("CAM", self.store, cfg,
                              writer_factory=lambda p, w, h, f: FakeWriter(p, w, h, f, self.log),
                              clock=lambda: self.now[0], mono=lambda: self.mono[0])

    def feed(self, rec, n, size=(320, 240)):
        for _ in range(n):
            self.mono[0] += 0.12
            self.now[0] += 0.1
            rec.submit(np.zeros((size[1], size[0], 3), np.uint8))
            time.sleep(0.01)

    def wait_idle(self, rec):
        for _ in range(100):
            if rec._q.empty():
                break
            time.sleep(0.02)
        time.sleep(0.05)

    def test_merekam_dan_menutup_saat_berhenti(self):
        rec = self.make()
        self.feed(rec, 20)
        self.wait_idle(rec)
        self.assertTrue(rec.recording)
        rec.stop()
        rows = self.store.list()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["status"], rows[0]["frames"]), ("done", 20))
        self.assertEqual(rows[0]["codec"], "h264")

    def test_dibatasi_fps_rekaman(self):
        rec = self.make()
        for _ in range(50):  # 50 frame dalam 0,5 detik (100 fps) -> ~5 tersimpan
            self.mono[0] += 0.01
            rec.submit(np.zeros((240, 320, 3), np.uint8))
        self.wait_idle(rec)
        rec.stop()
        self.assertLessEqual(self.store.list()[0]["frames"], 6)

    def test_potong_segmen_per_menit(self):
        rec = self.make()
        self.feed(rec, 10)
        self.wait_idle(rec)
        self.now[0] += 61
        self.feed(rec, 10)
        self.wait_idle(rec)
        rec.stop()
        self.assertEqual(len(self.store.list()), 2)

    def test_ukuran_berubah_membuka_berkas_baru(self):
        rec = self.make()
        self.feed(rec, 5, (320, 240))
        self.wait_idle(rec)
        self.feed(rec, 5, (640, 480))
        self.wait_idle(rec)
        rec.stop()
        self.assertEqual(len(self.store.list()), 2)

    def test_ukuran_ganjil_dibulatkan_genap(self):
        rec = self.make()
        self.feed(rec, 3, (321, 241))
        self.wait_idle(rec)
        rec.stop()
        self.assertIn(("open", 320, 240), self.log)

    def test_tertutup_bila_frame_berhenti(self):
        rec = self.make()
        self.feed(rec, 5)
        self.wait_idle(rec)
        self.mono[0] += 10  # stream mati
        time.sleep(1.4)
        self.assertFalse(rec.recording)
        rec.stop()
        self.assertEqual(self.store.list()[0]["status"], "done")

    def test_gagal_membuka_penulis_tidak_menjatuhkan_thread(self):
        from apps.dashboard.recording.writers import WriterError

        def boom(*a):
            raise WriterError("tidak ada")

        cfg = RecordingConfig(record_fps=10)
        rec = CameraRecorder("CAM", self.store, cfg, writer_factory=boom, clock=lambda: 1.0, mono=lambda: self.mono[0])
        self.feed(rec, 3)
        self.wait_idle(rec)
        rec.stop()
        self.assertEqual(self.store.list(), [])
        self.assertGreaterEqual(rec.errors, 1)


class RangeTests(unittest.TestCase):
    def test_range(self):
        self.assertIsNone(parse_range("", 100))
        self.assertEqual(parse_range("bytes=0-9", 100), (0, 9))
        self.assertEqual(parse_range("bytes=90-", 100), (90, 99))
        self.assertEqual(parse_range("bytes=-10", 100), (90, 99))
        self.assertEqual(parse_range("bytes=50-500", 100), (50, 99))

    def test_range_tidak_sah(self):
        for bad in ("bytes=100-", "bytes=9-1", "items=0-1", "bytes=0-1,5-6", "bytes=a-b", "bytes=-0"):
            with self.assertRaises(ValueError, msg=bad):
                parse_range(bad, 100)

    def test_ukuran_manusia(self):
        self.assertEqual(human_size(512), "512 B")
        self.assertEqual(human_size(1536), "1,5 KB")


class PengaturanTests(unittest.TestCase):
    def test_bidang_rekaman_bisa_disimpan_dan_dibaca(self):
        tmp = tempfile.mkdtemp()
        try:
            st = SettingsStore(Path(tmp) / "s.json", Path(tmp) / "m")
            values, errors = st.validate({"record": "0", "record_fps": "5", "record_segment_minutes": "2", "record_max_gb": "0"})
            self.assertEqual(errors, {})
            st.save(values)
            cfg = st.recording_config()
            self.assertFalse(cfg.enabled)
            self.assertEqual((cfg.record_fps, cfg.record_segment_minutes, cfg.record_max_gb), (5.0, 2, 0.0))
            section = next(s for s in st.describe() if s["id"] == "recording")
            self.assertEqual({f["key"] for f in section["fields"]},
                             {"record", "record_fps", "record_segment_minutes", "record_max_width", "record_max_gb"})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_validasi_menolak_di_luar_rentang(self):
        st = SettingsStore("/tmp/x.json", "/tmp/m")
        _, errors = st.validate({"record_fps": "99", "record_segment_minutes": "0"})
        self.assertEqual(set(errors), {"record_fps", "record_segment_minutes"})


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg tidak ada")
class FfmpegSungguhanTests(Base):
    def test_hasil_bisa_dibaca_kembali(self):
        import cv2

        rec = CameraRecorder("CAM", self.store, RecordingConfig(record_fps=10, record_max_gb=0))
        for i in range(30):
            frame = np.full((240, 320, 3), i * 8, np.uint8)
            rec._last_accept = 0.0
            rec.submit(frame)
        rec.stop()
        row = self.store.list()[0]
        self.assertEqual((row["status"], row["codec"]), ("done", "h264"))
        self.assertGreater(row["size_bytes"], 500)
        cap = cv2.VideoCapture(str(self.store.full_path(row["path"])))
        n = 0
        while cap.read()[0]:
            n += 1
        self.assertGreaterEqual(n, 25)


if __name__ == "__main__":
    unittest.main()
