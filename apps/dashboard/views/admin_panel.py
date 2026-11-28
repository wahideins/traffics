"""Panel admin: pengaturan model/deteksi/stream dan pengelolaan kamera.

Akses: lihat services/admin_access.py. View hanya lapisan tipis; logika di services/admin_actions.py.
"""
import json
import os
from functools import wraps

from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from ..detection.model_tools import ModelError
from ..recording import get_recording_manager
from ..services import admin_actions, app_settings, camera_admin, recordings_view
from ..services.admin_access import LOGIN, OK, LoginThrottle, decide, password_matches

COOKIE, SALT, SESSION_SECONDS = "ts_admin", "trafficsense-admin", 8 * 3600
_throttle = LoginThrottle()


def _password():
    return os.environ.get("TRAFFICSENSE_ADMIN_PASSWORD", "")


def _client_ip(request):
    return request.META.get("REMOTE_ADDR") or ""


def _decision(request):
    authenticated = request.get_signed_cookie(COOKIE, default=None, salt=SALT, max_age=SESSION_SECONDS) == "1"
    return decide(
        password_set=bool(_password()),
        remote_addr=_client_ip(request),
        forwarded=bool(request.META.get("HTTP_X_FORWARDED_FOR") or request.META.get("HTTP_FORWARDED")),
        authenticated=authenticated,
    )


def admin_only(view):
    """Izinkan hanya yang berhak. Halaman HTML diarahkan ke login/penjelasan; endpoint JSON dijawab 401/403."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        verdict = _decision(request)
        if verdict == OK:
            return view(request, *args, **kwargs)
        wants_json = request.method != "GET" or request.headers.get("Accept", "").startswith("application/json")
        if wants_json and request.path != reverse("dashboard:admin_panel"):
            status = 401 if verdict == LOGIN else 403
            return JsonResponse({"ok": False, "message": "Masuk dulu." if verdict == LOGIN else "Akses ditolak."}, status=status)
        if verdict == LOGIN:
            return render(request, "dashboard/admin_login.html", {"error": ""}, status=401)
        return render(request, "dashboard/admin_forbidden.html", status=403)

    return wrapper


def _json_error(exc, status=400):
    return JsonResponse({"ok": False, "message": str(exc)}, status=status)


@require_GET
@never_cache
@admin_only
def panel(request):
    store = app_settings.get_store()
    return render(request, "dashboard/admin.html", {
        "sections": store.describe(),
        "models": _models_view(store),
        "cameras": admin_actions.camera_overview(),
        "system": admin_actions.system_info(),
        "recordings": recordings_view.overview(),
        "password_set": bool(_password()),
        "has_overrides": bool(store.overrides()),
    })


def _models_view(store):
    from ..detection.model_tools import list_models

    active = store.overrides().get("model", "")
    return [{**m, "active": m["name"] == active} for m in list_models(store.models_dir)]


@require_GET
@never_cache
@admin_only
def cameras_fragment(request):
    return render(request, "dashboard/partials/admin_cameras.html", {"cameras": admin_actions.camera_overview()})


@require_GET
@never_cache
@admin_only
def calibration_page(request, code):
    camera = camera_admin.get_live_camera(code)
    if camera is None:
        raise Http404("Kamera RTSP tidak ditemukan")
    return render(request, "dashboard/admin_calibration.html", {
        "camera": camera,
        "calibration_json": json.dumps(camera.calibration or {}, separators=(",", ":")),
    })


@require_GET
@never_cache
@admin_only
def zone_stats(request, code):
    stats = admin_actions.zone_stats(code)
    return JsonResponse({"ok": stats is not None, "zones": stats or []})


@require_POST
def login(request):
    ip = _client_ip(request)
    expected = _password()
    if not expected:
        return redirect("dashboard:admin_panel")
    if not _throttle.allowed(ip):
        return render(request, "dashboard/admin_login.html", {"error": "Terlalu banyak percobaan. Coba lagi beberapa menit lagi."}, status=429)
    if not password_matches(request.POST.get("password", ""), expected):
        _throttle.fail(ip)
        return render(request, "dashboard/admin_login.html", {"error": "Sandi salah."}, status=401)
    _throttle.reset(ip)
    response = redirect("dashboard:admin_panel")
    response.set_signed_cookie(COOKIE, "1", salt=SALT, max_age=SESSION_SECONDS, httponly=True, samesite="Lax",
                               secure=request.is_secure())
    return response


@require_POST
def logout(request):
    response = redirect("dashboard:admin_panel")
    response.delete_cookie(COOKIE)
    return response


@require_POST
@admin_only
def save(request):
    result, errors = admin_actions.apply_settings(request.POST)
    if errors:
        return JsonResponse({"ok": False, "errors": errors}, status=400)
    return JsonResponse({"ok": True, **result})


@require_POST
@admin_only
def reset(request):
    admin_actions.reset_settings()
    return JsonResponse({"ok": True})


@require_POST
@admin_only
def model_upload(request):
    upload = request.FILES.get("file")
    if upload is None:
        return _json_error("Pilih berkas .onnx dulu.")
    try:
        info = admin_actions.upload_model(upload.name, upload.chunks())
    except ModelError as exc:
        return _json_error(exc)
    return JsonResponse({"ok": True, "name": upload.name, "info": info})


@require_POST
@admin_only
def model_test(request, name):
    try:
        return JsonResponse({"ok": True, "info": admin_actions.test_model(name)})
    except ModelError as exc:
        return _json_error(exc)


@require_POST
@admin_only
def model_use(request, name):
    try:
        admin_actions.set_active_model(name)
    except ModelError as exc:
        return _json_error(exc)
    return JsonResponse({"ok": True})


@require_POST
@admin_only
def model_delete(request, name):
    try:
        admin_actions.remove_model(name)
    except ModelError as exc:
        return _json_error(exc)
    return JsonResponse({"ok": True})


@require_POST
@admin_only
def camera_restart(request, code):
    if not admin_actions.restart_camera(code):
        raise Http404("Kamera RTSP tidak ditemukan")
    return JsonResponse({"ok": True})


@require_POST
@admin_only
def camera_reset_counts(request, code):
    if not admin_actions.reset_camera_counts(code):
        return _json_error("Deteksi belum berjalan untuk kamera ini.", status=409)
    return JsonResponse({"ok": True})


@require_GET
@admin_only
def recording_file(request, rec_id):
    """Putar/unduh satu berkas rekaman; mendukung Range agar bisa digeser di pemutar browser."""
    store = get_recording_manager().store
    rec = store.get(rec_id)
    if rec is None:
        raise Http404("Rekaman tidak ditemukan")
    try:
        path = store.full_path(rec["path"])
        size = path.stat().st_size
    except (OSError, ValueError):
        raise Http404("Berkas rekaman tidak ada") from None
    try:
        span = recordings_view.parse_range(request.META.get("HTTP_RANGE", ""), size)
    except ValueError:
        resp = HttpResponse(status=416)
        resp["Content-Range"] = f"bytes */{size}"
        return resp
    start, end = span if span else (0, size - 1)
    resp = StreamingHttpResponse(recordings_view.iter_file(path, start, end), status=206 if span else 200,
                                 content_type="video/mp4")
    resp["Accept-Ranges"] = "bytes"
    resp["Content-Length"] = str(max(end - start + 1, 0))
    if span:
        resp["Content-Range"] = f"bytes {start}-{end}/{size}"
    if request.GET.get("download"):
        resp["Content-Disposition"] = f'attachment; filename="{path.name}"'
    resp["Cache-Control"] = "private, no-store"
    return resp


@require_POST
@admin_only
def recording_delete(request, rec_id):
    if not get_recording_manager().store.delete(rec_id):
        return _json_error("Rekaman tidak ditemukan atau masih direkam.", status=409)
    return JsonResponse({"ok": True})
