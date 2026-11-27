"""Tes modul deteksi dengan deteksi skrip (tanpa model, tanpa jaringan)."""
import json
import unittest

import numpy as np

from apps.dashboard.detection.analyzer import TrafficAnalyzer
from apps.dashboard.detection.calibration import Calibration, RoadModel, parse_calibration
from apps.dashboard.detection.detector import COCO_TO_CLASS, YoloOnnxDetector, decode_output, nms
from apps.dashboard.detection.config import DetectionConfig
from apps.dashboard.detection.bytetrack import ByteTracker, linear_assignment
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
        tracker = ByteTracker(min_hits=1)
        ids = set()
        for i in range(10):
            tracks = tracker.update([car(100 + i * 60, 300)], i / FPS)
            ids.update(tr.id for tr in tracks)
        self.assertEqual(len(ids), 1)

    def test_dua_objek_berlawanan_arah_tidak_tertukar(self):
        tracker = ByteTracker(min_hits=1)
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
        tracker = ByteTracker(min_hits=1, max_age=1.0)
        tracker.update([car(100, 300)], 0)
        tracker.update([], 0.5)
        self.assertEqual(len(tracker.tracks), 1)
        tracker.update([], 2.0)
        self.assertEqual(len(tracker.tracks), 0)

    def test_belum_terkonfirmasi_tidak_dikembalikan(self):
        tracker = ByteTracker(min_hits=3)
        self.assertEqual(tracker.update([car(100, 300)], 0), [])


class ByteTrackTests(unittest.TestCase):
    def test_hungarian_sama_dengan_brute_force(self):
        import itertools
        rng = np.random.default_rng(3)
        for n, m in [(3, 3), (2, 4), (4, 2), (5, 5), (1, 3)]:
            for _ in range(20):
                cost = rng.random((n, m))
                pairs = linear_assignment(cost)
                self.assertEqual(len(pairs), min(n, m))
                got = sum(cost[i, j] for i, j in pairs)
                k = min(n, m)
                best = min(
                    sum(cost[r, c] for r, c in zip(rows, cols))
                    for rows in itertools.combinations(range(n), k)
                    for cols in itertools.permutations(range(m), k)
                )
                self.assertAlmostEqual(got, best, places=9)

    def test_deteksi_skor_rendah_mempertahankan_id(self):
        tracker = ByteTracker(min_hits=2, high_conf=0.5, low_conf=0.1)
        ids = set()
        for i in range(12):
            d = car(100 + i * 40, 300)
            score = 0.9 if i < 5 or i > 8 else 0.25  # kendaraan "kabur" di tengah
            tracks = tracker.update([Detection(d.box, score, d.cls)], i / FPS)
            ids.update(tr.id for tr in tracks)
            if 5 <= i <= 8:
                self.assertEqual(len(tracks), 1, f"track hilang pada frame {i}")
        self.assertEqual(len(ids), 1)

    def test_skor_rendah_tidak_membuka_track_baru(self):
        tracker = ByteTracker(min_hits=1, high_conf=0.5, low_conf=0.1)
        d = car(200, 300)
        self.assertEqual(tracker.update([Detection(d.box, 0.3, d.cls)], 0), [])
        self.assertEqual(len(tracker.tracks), 0)

    def test_skor_di_bawah_low_conf_diabaikan(self):
        tracker = ByteTracker(min_hits=1, high_conf=0.5, low_conf=0.2)
        d = car(200, 300)
        tracker.update([Detection(d.box, 0.9, d.cls)], 0)
        tracker.update([Detection(d.box, 0.1, d.cls)], 0.2)
        self.assertEqual(tracker.tracks[0].missed, 1)

    def test_pulih_setelah_hilang_sebentar_dengan_id_sama(self):
        tracker = ByteTracker(min_hits=2, max_age=1.5)
        first = set()
        for i in range(5):
            first.update(tr.id for tr in tracker.update([car(100 + i * 50, 300)], i / FPS))
        for i in range(5, 8):  # hilang 3 frame
            self.assertEqual(tracker.update([], i / FPS), [])
        back = tracker.update([car(100 + 8 * 50, 300)], 8 / FPS)
        self.assertEqual({tr.id for tr in back}, first)

    def test_track_baru_tak_terkonfirmasi_dibuang_bila_tak_cocok(self):
        tracker = ByteTracker(min_hits=2)
        tracker.update([car(100, 300)], 0)
        tracker.update([], 0.2)
        self.assertEqual(len(tracker.tracks), 0)

    def test_selang_waktu_tak_seragam(self):
        tracker = ByteTracker(min_hits=2)
        ids, t = set(), 0.0
        for i, dt in enumerate([0.2, 0.2, 0.4, 0.2, 0.6, 0.2, 0.2]):
            t += dt
            x = 100 + t * 250  # 250 px/detik
            ids.update(tr.id for tr in tracker.update([car(x, 300)], t))
        self.assertEqual(len(ids), 1)

    def test_kelas_ditentukan_suara_terbanyak_skor_tinggi(self):
        tracker = ByteTracker(min_hits=1, high_conf=0.5, low_conf=0.1)
        classes = ["mobil", "mobil", "truk", "mobil"]
        for i, cls in enumerate(classes):
            tracks = tracker.update([car(100 + i * 30, 300, cls=cls)], i / FPS)
        self.assertEqual(tracks[0].cls, "mobil")


class ZoneMeasureTests(unittest.TestCase):
    """Penghitungan per zona: hitungan, kecepatan, dan lawan arah dihitung dari kunjungan zona."""

    def cal(self, direction="a", zones_only=True, **over):
        zone = {"name": "Lajur 1", "color": "#3d8cff", "direction": direction,
                "points": [[0.1, 0.5], [0.4, 0.5], [0.4, 0.9], [0.1, 0.9]]}  # x 128..512
        return calibrated(zones=[zone], zones_only=zones_only, **over)

    def run_vehicle(self, a, clock, x0, v, seconds, cls="mobil", y=450):
        drive(a, clock, [(cls, x0, y, v)], seconds)
        return a.snapshot(clock.t)

    def test_hitungan_dan_kecepatan_dari_zona_tanpa_garis_hitung(self):
        # garis hitung di 90% jalan (x ~ 1050) tak pernah dicapai; kendaraan hanya melewati zona
        a, clock = make(self.cal(line_pos=0.9))
        snap = self.run_vehicle(a, clock, 100, 300, 2.8)
        self.assertEqual(snap["counts"]["a"]["mobil"], 1)
        z = snap["zones"][0]
        self.assertEqual((z["total"], z["by_cls"]["mobil"]), (1, 1))
        expected = 300 * (25.0 / 640) * 3.6  # px/dtk -> km/j (skala referensi)
        self.assertAlmostEqual(z["avg_speed"], expected, delta=6)
        self.assertAlmostEqual(snap["speed"]["avg"], z["avg_speed"], delta=0.5)  # sumber sama
        self.assertEqual(snap["wrong_today"], 0)

    def test_lawan_arah_di_zona(self):
        a, clock = make(self.cal(direction="a"))
        snap = self.run_vehicle(a, clock, 700, -250, 4.8, cls="truk")
        z = snap["zones"][0]
        self.assertEqual(z["wrong"], 1)
        self.assertEqual(snap["wrong_today"], 1)
        wrong = [e for e in snap["events"] if e["type"] == "wrong"]
        self.assertEqual(len(wrong), 1)
        self.assertIn("Lajur 1", wrong[0]["detail"])
        self.assertEqual(snap["counts"]["b"]["truk"], 1)  # dihitung menurut arah gerak sebenarnya

    def test_arah_b_dan_dua_arah(self):
        a, clock = make(self.cal(direction="b"))
        snap = self.run_vehicle(a, clock, 700, -250, 4.8)
        self.assertEqual(snap["zones"][0]["wrong"], 0)
        a, clock = make(self.cal(direction="both"))
        snap = self.run_vehicle(a, clock, 700, -250, 4.8)
        self.assertEqual(snap["zones"][0]["wrong"], 0)
        self.assertEqual(snap["counts"]["b"]["mobil"], 1)

    def test_pelanggaran_kecepatan_per_zona(self):
        a, clock = make(self.cal(), limit=30)
        snap = self.run_vehicle(a, clock, 100, 400, 2.5)  # ~56 km/j
        self.assertEqual(snap["zones"][0]["speeding"], 1)
        self.assertEqual(snap["speeding"] if "speeding" in snap else snap["speed"]["speeding"], 1)

    def test_tanpa_mode_zona_statistik_zona_tetap_ada_tetapi_hitungan_global_dari_garis(self):
        a, clock = make(self.cal(zones_only=False, line_pos=0.9))
        snap = self.run_vehicle(a, clock, 100, 300, 2.8)  # garis tak tercapai
        self.assertEqual(snap["counts"]["a"]["mobil"], 0)
        self.assertEqual(snap["zones"][0]["total"], 1)

    def test_lawan_arah_zona_tanpa_mode_zona_tidak_menambah_hitungan_global(self):
        a, clock = make(self.cal(direction="a", zones_only=False))
        snap = self.run_vehicle(a, clock, 700, -250, 4.8)
        self.assertEqual(snap["zones"][0]["wrong"], 1)
        self.assertEqual(snap["wrong_today"], 0)  # tanpa median/satu arah, logika garis tak bisa menilai

    def test_getar_di_tepi_zona_tidak_menghitung_ganda(self):
        a, clock = make(self.cal())
        # keluar-masuk tepi kanan zona (x=512) beberapa kali lalu pergi: satu kunjungan saja
        for i, x in enumerate([150, 250, 350, 450, 480, 530, 490, 535, 495, 540, 700, 900, 1100]):
            clock.t = 1_800_000_000.0 + i / FPS
            a.process([car(x, 450)], (W, H), clock.t)
        for i in range(13, 32):
            clock.t = 1_800_000_000.0 + i / FPS
            a.process([], (W, H), clock.t)
        snap = a.snapshot(clock.t)
        self.assertEqual(snap["zones"][0]["total"], 1)
        self.assertEqual(sum(snap["counts"]["a"].values()) + sum(snap["counts"]["b"].values()), 1)

    def test_arah_zona_dibaca_dan_divalidasi(self):
        bad = {"name": "Z", "color": "#3d8cff", "direction": "x", "points": [[0.1, 0.5], [0.4, 0.5], [0.4, 0.9]]}
        _, errors = parse_calibration({**calibrated().to_dict(), "zones": [bad]})
        self.assertIn("zones", errors)
        cal, _ = parse_calibration({**calibrated().to_dict(), "zones": [{**bad, "direction": "both"}]})
        self.assertEqual(cal.zones[0].direction, "both")
        default, _ = parse_calibration({**calibrated().to_dict(), "zones": [{k: v for k, v in bad.items() if k != "direction"}]})
        self.assertEqual(default.zones[0].direction, "a")


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


class RoiAndProviderTests(unittest.TestCase):
    def test_roi_diurutkan_dan_divalidasi(self):
        cal = calibrated(roi=[[0.9, 0.9], [0.2, 0.3]])
        self.assertEqual(cal.roi, ((0.2, 0.3), (0.9, 0.9)))
        self.assertIn("roi", parse_calibration({"axis": [[0.1, 0.5], [0.9, 0.5]], "roi": [[0.1, 0.1], [0.15, 0.9]]})[1])
        self.assertIn("roi", parse_calibration({"axis": [[0.1, 0.5], [0.9, 0.5]], "roi": [[0.1, 0.1]]})[1])
        self.assertEqual(cal.to_dict()["roi"], [[0.2, 0.3], [0.9, 0.9]])

    def test_pemilihan_penyedia_eksekusi(self):
        pick = YoloOnnxDetector._choose_providers
        both = ["DmlExecutionProvider", "CPUExecutionProvider"]
        self.assertEqual(pick(both, "auto"), both)
        self.assertEqual(pick(both, "cpu"), ["CPUExecutionProvider"])
        self.assertEqual(pick(["CPUExecutionProvider"], "cuda"), ["CPUExecutionProvider"])
        self.assertEqual(pick(["CUDAExecutionProvider", "CPUExecutionProvider"], "auto")[0], "CUDAExecutionProvider")

    def test_pipeline_memotong_area_dan_mengembalikan_koordinat_penuh(self):
        from apps.dashboard.detection.pipeline import DetectionPipeline

        seen = {}

        class Det:
            def detect(self, frame):
                seen["shape"] = frame.shape[:2]
                return [Detection((10, 20, 60, 70), 0.9, "mobil")]

        analyzer = TrafficAnalyzer(speed_limit=60, calibration=calibrated(roi=[[0.5, 0.5], [1.0, 1.0]]))
        pipe = DetectionPipeline("X", analyzer, lambda c: Det(), DetectionConfig())
        dets, area = pipe._detect_in_roi(Det(), np.zeros((720, 1280, 3), dtype=np.uint8))
        self.assertEqual(seen["shape"], (360, 640))
        self.assertEqual(dets[0].box, (650, 380, 700, 430))
        self.assertEqual(area, 640.0 * 360.0)


class ZoneTests(unittest.TestCase):
    SQUARE = [[0.3, 0.3], [0.7, 0.3], [0.7, 0.9], [0.3, 0.9]]

    def zone_cal(self, **extra):
        from apps.dashboard.detection.calibration import parse_calibration
        data = {**calibrated().to_dict(), "zones": [{"name": "Lajur 1", "color": "#3d8cff", "points": self.SQUARE}], **extra}
        cal, errors = parse_calibration(data)
        self.assertEqual(errors, {})
        return cal

    def test_validasi_zona(self):
        from apps.dashboard.detection.calibration import parse_calibration
        base = calibrated().to_dict()
        bad = [
            [{"name": "a", "color": "biru", "points": self.SQUARE}],
            [{"name": "a", "color": "#3d8cff", "points": self.SQUARE[:2]}],
            [{"name": "a", "color": "#3d8cff", "points": [[0.1, 0.1], [0.2, 0.2], [0.3, 0.3]]}],  # garis lurus
            [{"name": "a", "color": "#3d8cff", "points": [[0.1, 0.1], [1.5, 0.2], [0.3, 0.3]]}],
            [{"name": "a", "color": "#3d8cff", "points": self.SQUARE}, {"name": "A", "color": "#ff0000", "points": self.SQUARE}],
            [{"name": "z", "color": "#3d8cff", "points": self.SQUARE}] * 9,
        ]
        for zones in bad:
            cal, errors = parse_calibration({**base, "zones": zones})
            self.assertIn("zones", errors, zones)

    def test_zona_tersimpan_dan_terbaca(self):
        from apps.dashboard.detection.calibration import from_stored
        cal = self.zone_cal()
        again = from_stored(cal.to_dict())
        self.assertEqual(again.zones, cal.zones)
        self.assertEqual(again.zones[0].bgr, (255, 140, 61))

    def test_zones_only_butuh_zona(self):
        base = calibrated().to_dict()
        _, errors = parse_calibration({**base, "zones": [], "zones_only": True})
        self.assertIn("zones_only", errors)
        cal, errors = parse_calibration({**base, "zones": [{"name": "A", "color": "#3d8cff", "points": self.SQUARE}], "zones_only": True})
        self.assertEqual(errors, {})
        self.assertTrue(cal.detect_in_zones)
        self.assertTrue(parse_calibration(cal.to_dict())[0].zones_only)

    def test_titik_dalam_poligon(self):
        from apps.dashboard.detection.calibration import point_in_polygon
        pts = [(0.3, 0.3), (0.7, 0.3), (0.5, 0.9)]
        self.assertTrue(point_in_polygon(0.5, 0.5, pts))
        self.assertFalse(point_in_polygon(0.1, 0.5, pts))
        self.assertFalse(point_in_polygon(0.65, 0.8, pts))

    def test_waktu_tinggal_dan_statistik(self):
        a, clock = make(self.zone_cal())
        # mobil melaju horizontal di y=450 (0.625 tinggi) dengan 250 px/dtk; zona x 0.3..0.7 = 384..896 px
        seen = []
        for i in range(60):
            t = i / FPS
            clock.t = 1_800_000_000.0 + t
            a.process([car(100 + 250 * t, 450)], (W, H), clock.t)
            ov = a.overlay()[0]
            if ov:
                seen.append(ov[0])
        inside = [o["dwell"] for o in seen if o["zone"] == "Lajur 1"]
        self.assertTrue(inside)
        self.assertAlmostEqual(max(inside), 512 / 250, delta=0.45)
        snap = a.snapshot(clock.t)["zones"][0]
        self.assertEqual(snap["entered"], 1)
        self.assertEqual(snap["now"], 0)  # sudah keluar
        self.assertAlmostEqual(snap["avg_dwell"], 512 / 250, delta=0.45)

    def test_kendaraan_di_luar_zona_tidak_dihitung(self):
        a, clock = make(self.zone_cal())
        for i in range(30):
            clock.t = 1_800_000_000.0 + i / FPS
            a.process([car(100 + 20 * i / FPS, 100)], (W, H), clock.t)  # y=100 di atas zona
        self.assertEqual(a.snapshot(clock.t)["zones"][0]["entered"], 0)

    def test_ganti_zona_mengatur_ulang_statistik(self):
        a, clock = make(self.zone_cal())
        for i in range(10):
            clock.t = 1_800_000_000.0 + i / FPS
            a.process([car(500, 450)], (W, H), clock.t)
        self.assertEqual(a.snapshot(clock.t)["zones"][0]["entered"], 1)
        a.set_calibration(self.zone_cal(zones=[{"name": "Baru", "color": "#ff0000", "points": self.SQUARE}]))
        snap = a.snapshot(clock.t)["zones"]
        self.assertEqual((snap[0]["name"], snap[0]["entered"]), ("Baru", 0))
