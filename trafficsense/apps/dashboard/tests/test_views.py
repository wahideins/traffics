"""Tes view (butuh Django): halaman penuh dan semua panel."""
import re

from django.test import SimpleTestCase
from django.urls import reverse

from apps.dashboard.views.panels import PANEL_TEMPLATES


class IndexViewTests(SimpleTestCase):
    def test_halaman_utama_ok(self):
        response = self.client.get(reverse("dashboard:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "TrafficSense")
        self.assertContains(response, 'data-panel="flow_status"')

    def test_parameter_kamera_dan_rentang_dipakai(self):
        response = self.client.get(reverse("dashboard:index"), {"camera": "CAM-03", "range": "24h"})
        self.assertContains(response, 'data-initial-camera="CAM-03"')
        self.assertContains(response, 'data-initial-range="24h"')

    def test_parameter_tidak_valid_jatuh_ke_default(self):
        response = self.client.get(reverse("dashboard:index"), {"camera": "x", "range": "y"})
        self.assertContains(response, 'data-initial-camera="CAM-01"')
        self.assertContains(response, 'data-initial-range="15m"')

    def test_tidak_ada_desimal_berkoma_di_style(self):
        html = self.client.get(reverse("dashboard:index")).content.decode()
        for style in re.findall(r'style="([^"]*)"', html):
            self.assertNotRegex(style, r"\d,\d", msg=f"Desimal berkoma di style: {style}")


class PanelViewTests(SimpleTestCase):
    def test_semua_panel_mengembalikan_html_dengan_atribut_data_panel(self):
        for name in PANEL_TEMPLATES:
            with self.subTest(panel=name):
                response = self.client.get(reverse("dashboard:panel", args=[name]))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f'data-panel="{name}"')

    def test_panel_tidak_dikenal_404(self):
        response = self.client.get(reverse("dashboard:panel", args=["tidak_ada"]))
        self.assertEqual(response.status_code, 404)

    def test_panel_mengikuti_parameter(self):
        response = self.client.get(
            reverse("dashboard:panel", args=["events_log"]),
            {"camera": "CAM-02", "event_type": "wrong"},
        )
        self.assertContains(response, "Simpang Pasar Baru")
        self.assertContains(response, "Mobil melawan arah selama 11 detik")
        self.assertNotContains(response, "Kepadatan 78%")

    def test_panel_tidak_di_cache(self):
        response = self.client.get(reverse("dashboard:panel", args=["flow_status"]))
        self.assertIn("no-store", response["Cache-Control"])

    def test_metode_selain_get_ditolak(self):
        response = self.client.post(reverse("dashboard:panel", args=["flow_status"]))
        self.assertEqual(response.status_code, 405)
