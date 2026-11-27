"""Tes validasi dan penyamaran URL RTSP (Python murni)."""
import unittest

from apps.dashboard.services.rtsp_url import (
    RtspUrlError,
    build_rtsp_url,
    mask_url,
    redact_text,
    split_rtsp_url,
)


class ValidasiTests(unittest.TestCase):
    def test_url_valid(self):
        self.assertTrue(build_rtsp_url("rtsp://192.168.1.20:554/stream1").startswith("rtsp://"))

    def test_skema_selain_rtsp_ditolak(self):
        for bad in ("ftp://x.com/a", "file:///etc/passwd", "ftp://a/b", "javascript:alert(1)"):
            with self.assertRaises(RtspUrlError, msg=bad):
                split_rtsp_url(bad)

    def test_kosong_spasi_dan_terlalu_panjang(self):
        for bad in ("", "   ", "rtsp://a b/c", "rtsp://host/" + "a" * 600):
            with self.assertRaises(RtspUrlError, msg=bad[:30]):
                split_rtsp_url(bad)

    def test_port_di_luar_rentang(self):
        for bad in ("rtsp://h:0/x", "rtsp://h:70000/x", "rtsp://h:abc/x"):
            with self.assertRaises(RtspUrlError, msg=bad):
                split_rtsp_url(bad)

    def test_host_berbahaya_ditolak(self):
        for bad in (
            "rtsp://169.254.169.254/x",
            "rtsp://0.0.0.0/x",
            "rtsp://224.0.0.1/x",
            "rtsp://[::ffff:169.254.169.254]/x",
            "rtsp://2852039166/x",
            "rtsp://metadata.google.internal/x",
        ):
            with self.assertRaises(RtspUrlError, msg=bad):
                split_rtsp_url(bad)

    def test_ip_lan_diizinkan(self):
        # Kamera CCTV memang biasanya ada di jaringan lokal.
        split_rtsp_url("rtsp://10.0.0.5/x")
        split_rtsp_url("rtsp://127.0.0.1:8554/live")


class HlsTests(unittest.TestCase):
    def test_m3u8_diterima(self):
        for ok in ("https://cdn.example.com/live/index.m3u8", "http://10.0.0.5:8080/a/B.M3U8?token=abc"):
            split_rtsp_url(ok)

    def test_http_tanpa_m3u8_ditolak(self):
        for bad in ("http://x.com/a", "https://x.com/video.mp4", "http://x.com/m3u8"):
            with self.assertRaises(RtspUrlError, msg=bad):
                split_rtsp_url(bad)

    def test_host_berbahaya_ditolak_di_hls(self):
        with self.assertRaises(RtspUrlError):
            split_rtsp_url("http://169.254.169.254/latest/x.m3u8")

    def test_penyamaran(self):
        masked = mask_url("https://u:rahasia@h.com/a.m3u8?token=zzz&x=1")
        self.assertNotIn("rahasia", masked)
        self.assertNotIn("zzz", masked)
        self.assertNotIn("rahasia", redact_text("gagal https://u:rahasia@h.com/a.m3u8"))

    def test_kredensial_terpisah(self):
        self.assertIn("admin:", build_rtsp_url("https://h.com/a.m3u8", "admin", "pw"))


class KredensialTests(unittest.TestCase):
    def test_karakter_khusus_di_encode(self):
        url = build_rtsp_url("rtsp://10.0.0.5/x", "admin", "p@ss:w/ord#1")
        self.assertIn("admin:", url)
        self.assertNotIn("p@ss", url)
        self.assertEqual(url.count("@"), 1)

    def test_url_sudah_berkredensial_ditolak_bila_ada_isian_terpisah(self):
        with self.assertRaises(RtspUrlError):
            build_rtsp_url("rtsp://u:p@10.0.0.5/x", "admin", "pw")


class PenyamaranTests(unittest.TestCase):
    def test_sandi_disamarkan(self):
        masked = mask_url("rtsp://admin:rahasia@10.0.0.5:554/live")
        self.assertNotIn("rahasia", masked)
        self.assertIn("admin", masked)
        self.assertIn("10.0.0.5", masked)

    def test_query_rahasia_disamarkan(self):
        masked = mask_url("rtsp://10.0.0.5/x?token=abc123&channel=1")
        self.assertNotIn("abc123", masked)
        self.assertIn("channel=1", masked)

    def test_redact_text(self):
        url = "rtsp://admin:rahasia@10.0.0.5/live"
        out = redact_text(f"gagal membuka {url} dan rahasia", url)
        self.assertNotIn("rahasia", out)


if __name__ == "__main__":
    unittest.main()
