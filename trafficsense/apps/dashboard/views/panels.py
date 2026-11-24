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
from django.contrib.auth.decorators import login_required

from ..services.context import build_dashboard_context
from ..services.params import parse_params

from django.http import StreamingHttpResponse
from apps.dashboard.services.cameras import get_camera, generate_rtsp_stream

_P = "dashboard/partials/"

# nama panel -> template. Tambah panel baru cukup dengan satu baris di sini.
PANEL_TEMPLATES = {
    "camera_tabs": _P + "camera_tabs.html",
    "camera_feed": _P + "camera_feed.html",
    "feed_hud": _P + "feed_hud.html",
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

@login_required(login_url='login')
def video_feed(request, camera_id):
    """Endpoint HTTP Streaming untuk menampilkan video RTSP kamera."""
    camera = get_camera(camera_id)
    # Ambil RTSP dari query params jika ada reconnect, jika tidak pakai default kamera
    rtsp_url = request.GET.get('rtsp', camera.rtsp_url)
    
    return StreamingHttpResponse(
        generate_rtsp_stream(rtsp_url),
        content_type='multipart/x-mixed-replace; boundary=frame'
    )
