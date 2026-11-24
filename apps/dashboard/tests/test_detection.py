"""Tes modul deteksi dengan deteksi skrip (tanpa model, tanpa jaringan)."""
import json
import unittest

import numpy as np

from apps.dashboard.detection.analyzer import TrafficAnalyzer
from apps.dashboard.detection.calibration import Calibration, RoadModel, parse_calibration
from apps.dashboard.detection.detector import COCO_TO_CLASS, YoloOnnxDetector, decode_output, nms
from apps.dashboard.detection.config import DetectionConfig
from apps.dashboard.detection.tracker import Tracker
from apps.dashboard.detection.types import Detection

W, H = 1280, 720
FPS = 5.0


def car(x, y, cls="mobil", w=110, h=70):
    """Kotak dengan titik tapak (tengah-bawah) di (x, y)."""
    return Detection((x - w / 2, y - h, x + w / 2, y), 0.9, cls)


def calibrated(**over):
    data = {"axis": [[0.1, 0.5], [0.9, 0.5]], "line_pos": 0.5,
            "ref": [[0.2, 0.9], [0.7, 0.9]], "ref_m": 25.0}  # 640 px = 25 m -> 0.039 m/px
    data.update(over)
    cal, errors = parse_calibration(data)
    assert not errors, errors
    return cal


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def drive(analyzer, clock, vehicles, seconds, fps=FPS):
    """vehicles: daftar (cls, x0, y, px_per_detik). Jalankan simulasi selama `seconds`."""
    for i in range(int(seconds * fps) + 1):
        t = i / fps
        clock.t = 1_800_000_000.0 + t
        dets = []
        for cls, x0, y, v in vehicles:
            x = x0 + v * t
            if -100 < x < W + 100:
                dets.append(car(x, y, cls))
        analyzer.process(dets, (W, H), clock.t)


def make(cal=None, limit=60, clock=None):
    clock = clock or Clock()
    return TrafficAnalyzer(speed_limit=limit, calibration=cal or calibrated(), clock=clock), clock


class DecodeTests(unittest.TestCase):
    def _tensor(self, rows, nc=80):
        out = np.zeros((1, 4 + nc, max(300, len(rows))), dtype=np.float32)  # N model nyata: ribuan
        for i, (cx, cy, w, h, cls, score) in enumerate(rows):
            out[0, :4, i] = (cx, cy, w, h)
            out[0, 4 + cls, i] = score
        return out

    def test_yolov8_dikonversi_ke_koordinat_frame(self):
        # letterbox 1280x720 -> 640x640: skala 0.5, pad_y 140
        out = self._tensor([(320, 320, 100, 60, 2, 0.9)])
        dets = decode_output(out, conf=0.35, nms_iou=0.5, scale=0.5, pad_x=0, pad_y=140, frame_w=W, frame_h=H)
        self.assertEqual(len(dets), 1)
        x1, y1, x2, y2 = dets[0].box
        self.assertEqual(dets[0].cls, "mobil")
        self.assertAlmostEqual(x1, 540, delta=1)
        self.assertAlmostEqual(x2, 740, delta=1)
        self.assertAlmostEqual(y1, 300, delta=1)
        self.assertAlmostEqual(y2, 420, delta=1)

    def test_kelas_bukan_kendaraan_dan_skor_rendah_dibuang(self):
        out = self._tensor([(100, 100, 50, 50, 0, 0.9), (300, 300, 50, 50, 2, 0.1), (200, 200, 50, 50, 7, 0.8)])
        dets = decode_output(out, conf=0.35, nms_iou=0.5, scale=1, pad_x=0, pad_y=0, frame_w=W, frame_h=H)
        self.assertEqual([d.cls for d in dets], ["truk"])

    def test_nms_membuang_kotak_ganda(self):
        out = self._tensor([(300, 300, 100, 100, 2, 0.9), (305, 302, 100, 100, 2, 0.8), (700, 300, 100, 100, 3, 0.7)])
        dets = decode_output(out, conf=0.35, nms_iou=0.5, scale=1, pad_x=0, pad_y=0, frame_w=W, frame_h=H)
        self.assertEqual(sorted(d.cls for d in dets), ["mobil", "motor"])

    def test_tata_letak_transpos_dan_end_to_end(self):
        out = self._tensor([(300, 300, 100, 100, 5, 0.9)]).transpose(0, 2, 1)  # (1, N, 84)
        dets = decode_output(out, conf=0.35, nms_iou=0.5, scale=1, pad_x=0, pad_y=0, frame_w=W, frame_h=H)
        self.assertEqual(dets[0].cls, "bus")
        e2e = np.array([[[10, 10, 110, 90, 0.8, 2], [0, 0, 0, 0, 0.0, 0]]], dtype=np.float32)
        dets = decode_output(e2e, conf=0.35, nms_iou=0.5, scale=1, pad_x=0, pad_y=0, frame_w=W, frame_h=H)
        self.assertEqual([d.cls for d in dets], ["mobil"])

    def test_nms_fungsi(self):
        boxes = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], dtype=np.float32)
        self.assertEqual(nms(boxes, np.array([0.9, 0.8, 0.7]), 0.5), [0, 2])

    def test_detektor_dengan_sesi_palsu(self):
        class Inp:
            name, shape = "images", [1, 3, 640, 640]

        class Session:
            def get_inputs(self):
                return [Inp()]

            def run(self, _, feed):
                blob = feed["images"]
                assert blob.shape == (1, 3, 640, 640) and blob.dtype == np.float32
                out = np.zeros((1, 84, 300), dtype=np.float32)
                out[0, :4, 0] = (320, 320, 100, 60)
                out[0, 4 + 3, 0] = 0.9  # motorcycle
                return [out]

        det = YoloOnnxDetector(DetectionConfig(), session=Session())
        frame = np.zeros((H, W, 3), dtype=np.uint8)
        result = det.detect(frame)
        self.assertEqual([d.cls for d in result], ["motor"])
        self.assertEqual(COCO_TO_CLASS[3], "motor")


class TrackerTests(unittest.TestCase):
    def test_id_tetap_untuk_objek_bergerak(self):
        tracker = Tracker(min_hits=1)
        ids = set()
        for i in range(10):
            tracks = tracker.update([car(100 + i * 60, 300)], i / FPS)
            ids.update(tr.id for tr in tracks)
        self.assertEqual(len(ids), 1)

    def test_dua_objek_berlawanan_arah_tidak_tertukar(self):
        tracker = Tracker(min_hits=1)
        seen = {}
        for i in range(12):
            t = i / FPS
            tracks = tracker.update([car(100 + i * 60, 300), car(1100 - i * 60, 500)], t)
            for tr in tracks:
                seen.setdefault(tr.id, []).append(tr.ground[1])
        self.assertEqual(len(seen), 2)
        for ys in seen.values():
            self.assertEqual(len(set(ys)), 1)

    def test_objek_hilang_dibuang_setelah_max_age(self):
        tracker = Tracker(min_hits=1, max_age=1.0)
        tracker.update([car(100, 300)], 0)
        tracker.update([], 0.5)
        self.assertEqual(len(tracker.tracks), 1)
        tracker.update([], 2.0)
        self.assertEqual(len(tracker.tracks), 0)

    def test_belum_terkonfirmasi_tidak_dikembalikan(self):
        tracker = Tracker(min_hits=3)
        self.assertEqual(tracker.update([car(100, 300)], 0), [])


class CalibrationTests(unittest.TestCase):
    def test_skala_meter_per_piksel(self):
        road = RoadModel(calibrated(), W, H)
        self.assertAlmostEqual(road.mpp, 25.0 / 640, places=5)

    def test_panah_pendek_dan_titik_di_luar_ditolak(self):
        self.assertIn("axis", parse_calibration({"axis": [[0.1, 0.5], [0.12, 0.5]]})[1])
        self.assertIn("axis", parse_calibration({"axis": [[0.1, 0.5], [1.5, 0.5]]})[1])

    def test_jarak_asli_wajib_masuk_akal(self):
        self.assertIn("ref_m", parse_calibration({"axis": [[0.1, 0.5], [0.9, 0.5]], "ref": [[0.2, 0.9], [0.7, 0.9]], "ref_m": 0.1})[1])

    def test_sisi_arah_a_ditentukan_dari_panah_dan_median(self):
        # Panah di y=0.7 (bawah), median di y=0.5 -> Arah A di sisi bawah.
        cal = calibrated(axis=[[0.1, 0.7], [0.9, 0.7]], median=[0.5, 0.5])
        road = RoadModel(cal, W, H)
        self.assertGreater(road.a_side * (road.t(600, 0.7 * H) - road.median_t), 0)
        self.assertLess(road.a_side * (road.t(600, 0.3 * H) - road.median_t), 0)


class AnalyzerCountTests(unittest.TestCase):
    def test_menghitung_per_arah_dan_kelas(self):
        a, clock = make()
        drive(a, clock, [("mobil", 100, 600, 300), ("motor", 1180, 300, -300), ("mobil", 20, 690, 300)], 3.5)
        snap = a.snapshot(clock.t)
        self.assertEqual(snap["counts"]["a"]["mobil"], 2)
        self.assertEqual(snap["counts"]["b"]["motor"], 1)
        self.assertEqual(snap["counts"]["a"]["motor"], 0)

    def test_kendaraan_dihitung_sekali(self):
        a, clock = make()
        drive(a, clock, [("mobil", 100, 600, 100)], 12)
        self.assertEqual(sum(a.snapshot(clock.t)["counts"]["a"].values()), 1)

    def test_kecepatan_sesuai_skala(self):
        a, clock = make()
        drive(a, clock, [("mobil", 100, 600, 384)], 3.0)  # 384 px/dtk * 0.0390625 m/px = 15 m/s = 54 km/j
        snap = a.snapshot(clock.t)
        self.assertTrue(snap["speed_ready"])
        self.assertAlmostEqual(snap["speed"]["avg"], 54, delta=5)

    def test_tanpa_skala_kecepatan_tidak_dikarang(self):
        a, clock = make(cal=calibrated(ref=None, ref_m=None))
        drive(a, clock, [("mobil", 100, 600, 384)], 3.0)
        snap = a.snapshot(clock.t)
        self.assertFalse(snap["speed_ready"])
        self.assertIsNone(snap["speed"]["avg"])
        self.assertEqual(snap["speed"]["speeding"], 0)
        self.assertEqual(sum(snap["counts"]["a"].values()), 1)  # hitungan tetap jalan

    def test_melebihi_batas_tercatat_sebagai_kejadian(self):
        a, clock = make(limit=40)
        drive(a, clock, [("mobil", 100, 600, 384)], 3.0)  # ~54 km/j > 40
        snap = a.snapshot(clock.t)
        self.assertEqual(snap["speed"]["speeding"], 1)
        events = [e for e in snap["events"] if e["type"] == "speed"]
        self.assertEqual(len(events), 1)
        self.assertIn("batas 40", events[0]["detail"])

    def test_histogram_kecepatan(self):
        a, clock = make()
        drive(a, clock, [("mobil", 100, 600, 384)], 3.0)
        bins = a.snapshot(clock.t)["speed"]["bins"]
        self.assertEqual(sum(bins), 1)
        self.assertEqual(bins[2], 1)  # 40-60

    def test_hitungan_berganti_hari(self):
        a, clock = make()
        drive(a, clock, [("mobil", 100, 600, 300)], 3.0)
        self.assertEqual(sum(a.snapshot(clock.t)["counts"]["a"].values()), 1)
        later = clock.t + 26 * 3600
        self.assertEqual(sum(a.snapshot(later)["counts"]["a"].values()), 0)


class WrongWayTests(unittest.TestCase):
    CAL = dict(axis=[[0.1, 0.7], [0.9, 0.7]], median=[0.5, 0.5])  # A ke kanan di sisi bawah

    def test_kendaraan_melawan_arah_terdeteksi(self):
        a, clock = make(cal=calibrated(**self.CAL))
        drive(a, clock, [("mobil", 1100, 560, -300)], 3.5)  # di jalur A (bawah) tapi ke kiri
        snap = a.snapshot(clock.t)
        self.assertEqual(snap["wrong_today"], 1)
        self.assertEqual([e["type"] for e in snap["events"] if e["type"] == "wrong"], ["wrong"])
        self.assertTrue(snap["wrong_active"])

    def test_arah_benar_di_kedua_jalur_tidak_dianggap_salah(self):
        a, clock = make(cal=calibrated(**self.CAL))
        drive(a, clock, [("mobil", 100, 600, 300), ("mobil", 1100, 330, -300)], 3.5)
        self.assertEqual(a.snapshot(clock.t)["wrong_today"], 0)

    def test_tanpa_median_atau_satu_arah_fitur_nonaktif(self):
        a, clock = make()
        drive(a, clock, [("mobil", 1100, 560, -300)], 3.5)
        snap = a.snapshot(clock.t)
        self.assertFalse(snap["can_wrong_way"])
        self.assertEqual(snap["wrong_today"], 0)

    def test_jalan_satu_arah(self):
        a, clock = make(cal=calibrated(one_way=True))
        drive(a, clock, [("mobil", 1100, 560, -300)], 3.5)
        self.assertEqual(a.snapshot(clock.t)["wrong_today"], 1)

    def test_dilaporkan_sekali_per_kendaraan(self):
        a, clock = make(cal=calibrated(**self.CAL))
        drive(a, clock, [("mobil", 1200, 560, -100)], 10)
        self.assertEqual(a.snapshot(clock.t)["wrong_today"], 1)


class CongestionTests(unittest.TestCase):
    def test_kepadatan_tinggi_menjadi_macet_dan_dicatat(self):
        a, clock = make()
        # Frame penuh kendaraan yang nyaris diam.
        for i in range(int(40 * FPS)):
            clock.t = 1_800_000_000.0 + i / FPS
            dets = [Detection((x, y, x + 150, y + 110), 0.9, "mobil") for x in range(0, W, 160) for y in range(100, 700, 120)]
            a.process(dets, (W, H), clock.t)
        snap = a.snapshot(clock.t)
        self.assertEqual(snap["level"], "macet")
        self.assertEqual(len([e for e in snap["events"] if e["type"] == "cong"]), 1)

    def test_jalan_kosong_lancar(self):
        a, clock = make()
        for i in range(20):
            clock.t += 1 / FPS
            a.process([], (W, H), clock.t)
        self.assertEqual(a.snapshot(clock.t)["level"], "lancar")


class SeriesAndStateTests(unittest.TestCase):
    def test_deret_waktu_per_menit(self):
        a, clock = make()
        drive(a, clock, [("mobil", 100, 600, 300)], 3.0)
        series = a.series(15, 1, clock.t)
        self.assertEqual(len(series), 15)
        self.assertEqual(series[-1]["total"], 1)
        self.assertEqual(sum(p["total"] for p in series[:-1]), 0)
        self.assertIsNotNone(series[-1]["density"])
        self.assertIsNone(series[0]["density"])

    def test_simpan_dan_pulihkan_keadaan(self):
        a, clock = make(limit=40)
        drive(a, clock, [("mobil", 100, 600, 384)], 3.0)
        state = json.loads(json.dumps(a.export_state()))
        b, _ = make(limit=40, clock=clock)
        self.assertTrue(b.load_state(state, clock.t))
        snap = b.snapshot(clock.t)
        self.assertEqual(sum(snap["counts"]["a"].values()), 1)
        self.assertEqual(snap["speed"]["speeding"], 1)
        self.assertEqual(len(b.series(15, 1, clock.t)), 15)

    def test_keadaan_hari_lain_tidak_memulihkan_hitungan(self):
        a, clock = make()
        drive(a, clock, [("mobil", 100, 600, 300)], 3.0)
        state = a.export_state()
        b, _ = make(clock=clock)
        b.load_state(state, clock.t + 26 * 3600)
        self.assertEqual(sum(b.snapshot(clock.t + 26 * 3600)["counts"]["a"].values()), 0)

    def test_keadaan_rusak_ditolak(self):
        a, _ = make()
        self.assertFalse(a.load_state({"version": 99}))
        self.assertFalse(a.load_state({"version": 1}))


if __name__ == "__main__":
    unittest.main()
