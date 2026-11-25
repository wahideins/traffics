"""View potongan HTML (panel) untuk pembaruan tanpa reload halaman.

Setiap panel punya satu template partial. JS meminta
`/panels/<nama>/?camera=...&range=...&event_type=...` lalu mengganti elemen
panel lama dengan HTML yang dikembalikan di sini.
"""
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from ..services.context import build_dashboard_context
from ..services.params import parse_params

_P = "dashboard/partials/"

# nama panel -> template. Tambah panel baru cukup dengan satu baris di sini.
PANEL_TEMPLATES = {
    "camera_tabs": _P + "camera_tabs.html",
    "camera_feed": _P + "camera_feed.html",
    "feed_hud": _P + "feed_hud.html",
    "detection_notice": _P + "detection_notice.html",
    "flow_status": _P + "flow_status.html",
    "kpi_cards": _P + "kpi_cards.html",
    "range_toggle": _P + "range_toggle.html",
    "vehicle_counts": _P + "vehicle_counts.html",
    "volume_chart": _P + "volume_chart.html",
    "congestion_chart": _P + "congestion_chart.html",
    "speed_chart": _P + "speed_chart.html",
    "wrong_way": _P + "wrong_way.html",
    "events_log": _P + "events_log.html",
}


@require_GET
@never_cache
def panel(request, name):
    template = PANEL_TEMPLATES.get(name)
    if template is None:
        raise Http404("Panel tidak dikenal")
    params = parse_params(request.GET)
    context = build_dashboard_context(params, now=timezone.localtime())
    return render(request, template, context)
