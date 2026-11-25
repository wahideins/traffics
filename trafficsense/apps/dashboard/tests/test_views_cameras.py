"""Tes view kamera (butuh Django). Memakai folder sementara untuk penyimpanan kamera."""
import tempfile
from pathlib import Path

from django.test import Client, SimpleTestCase
from django.urls import reverse

from apps.dashboard.services import registry

RTSP = "rtsp://10.0.0.5:554/live"


class CameraViewTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        registry.configure(Path(self.tmp.name) / "cameras.json")
        self.client = Client(enforce_csrf_checks=True)
        self.token = self._token()

    def tearDown(self):
        self.tmp.cleanup()

    def _token(self):
        response = self.client.get(reverse("dashboard:index"))
        return response.cookies["csrftoken"].value

    def _post(self, name, data=None, **kwargs):
        return self.client.post(reverse(name, **kwargs), data or {}, HTTP_X_CSRFTOKEN=self.token)

    def _add(self, **over):
        data = {"name": "Simpang Uji", "rtsp_url": RTSP, "username": "admin", "password": "rahasia-123"}
        data.update(over)
        return self._post("dashboard:camera_add", data)

    def test_post_tanpa_csrf_ditolak(self):
        response = self.client.post(reverse("dashboard:camera_add"), {"name": "x"})
        self.assertEqual(response.status_code, 403)

    def test_tambah_valid(self):
        response = self._add()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "code": "CAM-04"})

    def test_tambah_tidak_valid_mengembalikan_galat_per_kolom(self):
        response = self._add(name="", rtsp_url="http://x")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.json()["errors"]), {"name", "rtsp_url"})

    def test_sandi_tidak_pernah_muncul_di_html(self):
        self._add()
        for url in (
            reverse("dashboard:index") + "?camera=CAM-04",
            reverse("dashboard:panel", kwargs={"name": "camera_feed"}) + "?camera=CAM-04",
            reverse("dashboard:panel", kwargs={"name": "feed_hud"}) + "?camera=CAM-04",
        ):
            html = self.client.get(url).content.decode()
            self.assertNotIn("rahasia-123", html, msg=url)
            self.assertIn("CAM-04", html)

    def test_tab_kamera_memuat_kamera_baru(self):
        self._add()
        html = self.client.get(reverse("dashboard:panel", kwargs={"name": "camera_tabs"})).content.decode()
        self.assertIn('data-camera="CAM-04"', html)

    def test_hapus(self):
        self._add()
        self.assertEqual(self._post("dashboard:camera_delete", kwargs={"code": "CAM-04"}).status_code, 200)
        self.assertEqual(self._post("dashboard:camera_delete", kwargs={"code": "CAM-04"}).status_code, 404)

    def test_kamera_demo_tidak_bisa_dihapus_atau_distream(self):
        self.assertEqual(self._post("dashboard:camera_delete", kwargs={"code": "CAM-01"}).status_code, 404)
        self.assertEqual(self.client.get(reverse("dashboard:camera_stream", kwargs={"code": "CAM-01"})).status_code, 404)

    def test_stream_kamera_tak_dikenal_404(self):
        self.assertEqual(self.client.get(reverse("dashboard:camera_stream", kwargs={"code": "CAM-99"})).status_code, 404)

    def test_snapshot_tanpa_frame_503(self):
        self._add()
        self.assertEqual(self.client.get(reverse("dashboard:camera_snapshot", kwargs={"code": "CAM-04"})).status_code, 503)

    def test_probe_menolak_host_berbahaya_tanpa_koneksi(self):
        response = self._post("dashboard:camera_probe", {"rtsp_url": "rtsp://169.254.169.254/x"})
        self.assertIn("rtsp_url", response.json()["errors"])


class CalibrationViewTests(CameraViewTests):
    """Mewarisi setUp/_add; (kelas induk ikut dijalankan ulang, murah)."""

    CAL = {"axis": [[0.1, 0.7], [0.9, 0.7]], "median": [0.5, 0.5], "line_pos": 0.5,
           "ref": [[0.2, 0.9], [0.7, 0.9]], "ref_m": "25"}

    def _cal(self, data, code="CAM-04"):
        import json

        return self.client.post(
            reverse("dashboard:camera_calibration", kwargs={"code": code}),
            json.dumps(data), content_type="application/json", HTTP_X_CSRFTOKEN=self.token,
        )

    def test_simpan_kalibrasi_valid(self):
        self._add()
        self.assertEqual(self._cal(self.CAL).json(), {"ok": True})
        self.assertEqual(registry.get_live_camera("CAM-04").calibration["ref_m"], 25.0)

    def test_kalibrasi_tidak_valid_400_dengan_galat(self):
        self._add()
        response = self._cal({"axis": [[0.1, 0.5], [0.11, 0.5]]})
        self.assertEqual(response.status_code, 400)
        self.assertIn("axis", response.json()["errors"])

    def test_kalibrasi_kamera_demo_404(self):
        self.assertEqual(self._cal(self.CAL, code="CAM-01").status_code, 404)

    def test_panel_detection_notice_ada_untuk_kamera_rtsp(self):
        self._add()
        response = self.client.get(reverse("dashboard:panel", kwargs={"name": "detection_notice"}) + "?camera=CAM-04")
        self.assertContains(response, 'data-panel="detection_notice"')
        self.assertContains(response, "Deteksi belum aktif")  # tanpa TRAFFICSENSE_MODEL pada tes
