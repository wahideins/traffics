"""View kamera: video MJPEG, tes koneksi, tambah, hapus, sambung ulang.

Django hanya lapisan tipis; logikanya ada di services/camera_admin.py dan streaming/.
"""
import json

from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .. import runtime
from ..services import camera_admin
from ..services.registry import get_live_camera
from ..streaming import get_manager
from ..streaming.mjpeg import CONTENT_TYPE, mjpeg_stream


def _live_camera_or_404(code):
    camera = get_live_camera(code)
    if camera is None:
        raise Http404("Kamera RTSP tidak ditemukan")
    return camera


@require_GET
@never_cache
def stream(request, code):
    """Video langsung (MJPEG) untuk <img>. Pembaca RTSP dimulai saat ada yang menonton."""
    camera = _live_camera_or_404(code)
    reader = runtime.ensure_camera(camera)
    response = StreamingHttpResponse(mjpeg_stream(reader), content_type=CONTENT_TYPE)
    response["Cache-Control"] = "no-store"
    response["X-Accel-Buffering"] = "no"  # cegah proxy (nginx) menahan frame
    return response


@require_GET
@never_cache
def snapshot(request, code):
    """Satu frame JPEG terbaru (untuk thumbnail atau pengecekan cepat)."""
    camera = _live_camera_or_404(code)
    reader = get_manager().get(camera.id)
    jpeg = reader.latest_jpeg() if reader else None
    if jpeg is None:
        return HttpResponse("Belum ada frame", status=503, content_type="text/plain")
    return HttpResponse(jpeg, content_type="image/jpeg")


@require_POST
def probe(request):
    """Tes koneksi dari isian form (belum menyimpan apa pun)."""
    return JsonResponse(camera_admin.probe_camera(request.POST))


@require_POST
def add(request):
    camera, errors = camera_admin.create_camera(request.POST)
    if errors:
        return JsonResponse({"ok": False, "errors": errors}, status=400)
    return JsonResponse({"ok": True, "code": camera.id})


@require_POST
def reconnect(request, code):
    if not camera_admin.reconnect_camera(code):
        raise Http404("Kamera RTSP tidak ditemukan")
    return JsonResponse({"ok": True})


@require_POST
def delete(request, code):
    if not camera_admin.delete_camera(code):
        raise Http404("Kamera RTSP tidak ditemukan")
    return JsonResponse({"ok": True})


@require_POST
def calibration(request, code):
    """Simpan kalibrasi (JSON): arah, garis hitung, median, skala."""
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"ok": False, "errors": {"axis": "Data tidak valid."}}, status=400)
    ok, errors = camera_admin.save_calibration(code, data)
    if ok is None:
        raise Http404("Kamera RTSP tidak ditemukan")
    if not ok:
        return JsonResponse({"ok": False, "errors": errors}, status=400)
    return JsonResponse({"ok": True})
