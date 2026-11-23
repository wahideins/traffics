"""Tes validasi isian tambah kamera."""
import unittest

from apps.dashboard.services.camera_form import validate_camera_input


def form(**over):
    data = {"name": "Simpang Pasar", "rtsp_url": "rtsp://10.0.0.5/live", "username": "", "password": "",
            "dir_a": "", "dir_b": "", "speed_limit": ""}
    data.update(over)
    return data


class CameraFormTests(unittest.TestCase):
    def test_valid_dengan_default(self):
        cam, errors = validate_camera_input(form())
        self.assertEqual(errors, {})
        self.assertEqual((cam.dir_a, cam.dir_b, cam.speed_limit), ("Kiri ke kanan", "Kanan ke kiri", 60))

    def test_nama_pendek_dan_panjang(self):
        self.assertIn("name", validate_camera_input(form(name="a"))[1])
        self.assertIn("name", validate_camera_input(form(name="x" * 61))[1])

    def test_spasi_dirapikan(self):
        cam, _ = validate_camera_input(form(name="  Simpang   Pasar  "))
        self.assertEqual(cam.name, "Simpang Pasar")

    def test_kecepatan(self):
        self.assertIn("speed_limit", validate_camera_input(form(speed_limit="5"))[1])
        self.assertIn("speed_limit", validate_camera_input(form(speed_limit="999"))[1])
        self.assertIn("speed_limit", validate_camera_input(form(speed_limit="abc"))[1])
        self.assertEqual(validate_camera_input(form(speed_limit="80"))[0].speed_limit, 80)

    def test_url_buruk_memberi_galat_rtsp_url(self):
        self.assertIn("rtsp_url", validate_camera_input(form(rtsp_url="http://x"))[1])

    def test_kredensial_masuk_url_tapi_tidak_ke_galat(self):
        cam, errors = validate_camera_input(form(username="admin", password="rahasia"))
        self.assertEqual(errors, {})
        self.assertIn("rahasia", cam.source_url)
        self.assertNotIn("rahasia", repr(cam))

    def test_nama_tidak_wajib_untuk_probe(self):
        cam, errors = validate_camera_input(form(name=""), require_name=False)
        self.assertEqual(errors, {})


if __name__ == "__main__":
    unittest.main()
