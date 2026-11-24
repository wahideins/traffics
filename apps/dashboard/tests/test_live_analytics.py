"""Tes pengubah snapshot -> data template, dan bentuknya sama dengan analitik kosong/simulasi."""
import time
import unittest

from apps.dashboard.detection.analyzer import TrafficAnalyzer
from apps.dashboard.services.context import _empty_analytics
from apps.dashboard.services.camera_store import LiveCamera
from apps.dashboard.services.live_analytics import build_live_analytics
from apps.dashboard.tests.test_detection import Clock, calibrated, car, drive, make

CAM = LiveCamera(id="CAM-04", name="Uji", short="Uji", source_url="rtsp://h/x", speed_limit=40,
                 dir_a="Timur", dir_b="Barat", created_at="2026-01-01T00:00:00+00:00")


class P:  # parameter minimum untuk _empty_analytics
    range_key, event_type, camera_id = "15m", "all", "CAM-04"


def keys(d, prefix=""):
    out = set()
    for k, v in d.items():
        out.add(prefix + k)
        if isinstance(v, dict):
            out |= keys(v, prefix + k + ".")
    return out


class LiveAnalyticsTests(unittest.TestCase):
    def _build(self, **kw):
        a, clock = make(limit=48, **kw)
        drive(a, clock, [("mobil", 100, 600, 384), ("motor", 1180, 300, -300)], 3.5)
        snap = a.snapshot(clock.t)
        return build_live_analytics(CAM, snap, a.series(15, 1, clock.t), "15m", "all"), a, clock

    def test_bentuk_sama_dengan_analitik_kosong(self):
        live, _, _ = self._build()
        empty = _empty_analytics(CAM, P)
        self.assertEqual(keys(live), keys(empty))

    def test_isi_nyata(self):
        live, _, _ = self._build()
        self.assertEqual(live["counts"]["sum_all"], "2")
        self.assertEqual(live["hud"], {"a": "1", "b": "1"})
        self.assertEqual(live["kpi"]["speeding"], "1")  # mobil ~54 km/j > 48; motor ~42 km/j tidak
        self.assertEqual(live["flow"]["key"], "lancar")
        self.assertEqual(len(live["volume"]["bars"]), 15)
        self.assertEqual(len(live["congestion"]["bars"]), 15)
        self.assertTrue(any(e["type"] == "speed" for e in live["events"]))

    def test_filter_kejadian(self):
        _, a, clock = self._build()
        snap = a.snapshot(clock.t)
        only_wrong = build_live_analytics(CAM, snap, a.series(15, 1, clock.t), "15m", "wrong")
        self.assertEqual(only_wrong["events"], [])

    def test_tanpa_skala_tampil_strip_bukan_angka_palsu(self):
        a, clock = make(cal=calibrated(ref=None, ref_m=None))
        drive(a, clock, [("mobil", 100, 600, 384)], 3.0)
        live = build_live_analytics(CAM, a.snapshot(clock.t), a.series(15, 1, clock.t), "15m", "all")
        self.assertEqual(live["kpi"]["avg"], "—")
        self.assertEqual(live["kpi"]["speeding"], "—")
        self.assertEqual(live["flow"]["speed"], "—")
        self.assertEqual(live["speed"]["avg"], "—")
        self.assertEqual(live["wrong_way"]["count"], "—")

    def test_angka_css_memakai_titik_bukan_koma(self):
        live, _, _ = self._build()
        for bar in live["volume"]["bars"] + live["congestion"]["bars"]:
            self.assertNotIn(",", bar["h"])
        self.assertNotIn(",", live["flow"]["marker"])

    def test_peringatan_lawan_arah_tampil_di_hud(self):
        a, clock = make(cal=calibrated(axis=[[0.1, 0.7], [0.9, 0.7]], median=[0.5, 0.5]))
        drive(a, clock, [("mobil", 1100, 560, -300)], 3.5)
        live = build_live_analytics(CAM, a.snapshot(clock.t), a.series(15, 1, clock.t), "15m", "all")
        self.assertIn("Lawan arah", live["alert"])
        self.assertEqual(live["kpi"]["wrong_tone"], "danger")

    def test_rentang_24_jam(self):
        a, clock = make()
        drive(a, clock, [("mobil", 100, 600, 300)], 3.0)
        live = build_live_analytics(CAM, a.snapshot(clock.t), a.series(24, 60, clock.t), "24h", "all")
        self.assertEqual(len(live["volume"]["bars"]), 24)


if __name__ == "__main__":
    unittest.main()
