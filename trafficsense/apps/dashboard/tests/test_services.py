"""Tes lapisan data (Python murni, tidak butuh Django)."""
import datetime
import re
import unittest

from apps.dashboard.services.cameras import CAMERAS, get_camera
from apps.dashboard.services.constants import EVENT_FILTERS, TIME_RANGES
from apps.dashboard.services.context import build_dashboard_context
from apps.dashboard.services.metrics import classify_flow, vehicle_counts
from apps.dashboard.services.params import parse_params

NOW = datetime.datetime(2026, 11, 20, 10, 10, 5, tzinfo=datetime.timezone(datetime.timedelta(hours=7)))


class ClassifyFlowTests(unittest.TestCase):
    def test_lancar(self):
        self.assertEqual(classify_flow(50, 30, 60), "lancar")

    def test_padat_karena_kepadatan(self):
        self.assertEqual(classify_flow(50, 60, 60), "padat")

    def test_macet_karena_kecepatan_rendah(self):
        self.assertEqual(classify_flow(10, 30, 60), "macet")


class ParamsTests(unittest.TestCase):
    def test_nilai_tidak_valid_jatuh_ke_default(self):
        params = parse_params({"camera": "X", "range": "zz", "event_type": "qq"})
        self.assertEqual(params.camera_id, CAMERAS[0].id)
        self.assertEqual(params.range_key, "15m")
        self.assertEqual(params.event_type, "all")

    def test_nilai_valid_dipertahankan(self):
        params = parse_params({"camera": "CAM-02", "range": "1h", "event_type": "wrong"})
        self.assertEqual((params.camera_id, params.range_key, params.event_type), ("CAM-02", "1h", "wrong"))


class CountsTests(unittest.TestCase):
    def test_hitungan_tumbuh_seiring_waktu(self):
        camera = get_camera("CAM-01")
        pagi = vehicle_counts(camera, 60)["total_raw"]
        siang = vehicle_counts(camera, 600)["total_raw"]
        self.assertGreater(siang, pagi)

    def test_tengah_malam_tidak_error(self):
        self.assertEqual(vehicle_counts(get_camera("CAM-01"), 0)["total_raw"], 0)


class ContextTests(unittest.TestCase):
    def test_semua_kombinasi_membangun_konteks(self):
        for camera in CAMERAS:
            for range_key in TIME_RANGES:
                for event_key, _ in EVENT_FILTERS:
                    params = parse_params({"camera": camera.id, "range": range_key, "event_type": event_key})
                    context = build_dashboard_context(params, NOW)
                    self.assertEqual(context["camera"].id, camera.id)

    def test_filter_kejadian(self):
        params = parse_params({"camera": "CAM-01", "event_type": "wrong"})
        events = build_dashboard_context(params, NOW)["events"]
        self.assertTrue(events)
        self.assertTrue(all(e["type"] == "wrong" for e in events))

    def test_angka_css_memakai_titik(self):
        """Nilai untuk atribut style tidak boleh berkoma (locale Indonesia)."""
        context = build_dashboard_context(parse_params({}), NOW)
        numeric = re.compile(r"-?\d+(\.\d+)?")
        for vehicle in context["vehicles"]:
            for key in ("top", "w", "h", "duration", "delay", "rest"):
                self.assertRegex(vehicle[key], numeric)
        for bar in context["volume"]["bars"] + context["congestion"]["bars"]:
            self.assertRegex(bar["h"], numeric)
        for bin_ in context["speed"]["bins"]:
            self.assertRegex(bin_["h"], numeric)


if __name__ == "__main__":
    unittest.main()
