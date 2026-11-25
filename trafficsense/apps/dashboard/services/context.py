"""Perakit konteks template: satu fungsi yang dipakai halaman penuh dan semua panel.

Kamera demo memakai data simulasi. Kamera RTSP tambahan memakai analitik nyata
dari modul deteksi; sebelum ada data (model belum diatur/belum ada frame)
analitiknya kosong ("—"), bukan angka palsu.
"""
import json

from ..detection.manager import get_detection_manager
from ..streaming import get_manager
from .constants import (
    FLOW_LEVELS,
    SPEED_BINS,
    TICK_SECONDS,
    TIME_RANGES,
    VEHICLE_CLASSES,
)
from .events import build_event_filters, build_events, build_wrong_way
from .formatting import css_number, format_decimal
from .live_analytics import build_live_analytics
from .metrics import (
    clamp,
    classify_flow,
    direction_status,
    live_metrics,
    speed_analysis,
    vehicle_counts,
)
from .registry import camera_index, get_camera, list_cameras
from .series import build_series
from .vehicles import build_feed_vehicles

NO_DATA = "—"

_STREAM_LABELS = {
    "idle": "MENYIAPKAN",
    "connecting": "MENGHUBUNGKAN",
    "live": "LIVE",
    "error": "TERPUTUS",
    "stopped": "BERHENTI",
}


def build_dashboard_context(params, now) -> dict:
    """`params`: DashboardParams. `now`: datetime lokal (aware)."""
    camera = get_camera(params.camera_id)
    cfg = TIME_RANGES[params.range_key]
    tick = int(now.timestamp() // TICK_SECONDS)

    context = {
        "camera": camera,
        "cameras": _camera_tabs(camera, tick),
        "stream": _stream_view(camera),
        "vehicle_classes": VEHICLE_CLASSES,
        "time_range": {
            "key": params.range_key,
            "label": cfg["label"],
            "unit": cfg["unit"],
            "x_labels": cfg["x_labels"],
        },
        "ranges": [
            {"key": key, "label": value["label"], "active": key == params.range_key}
            for key, value in TIME_RANGES.items()
        ],
        "event_type": params.event_type,
        "event_filters": build_event_filters(params.event_type),
    }

    if camera.has_analytics:
        context["analytics"] = True
        context["detection"] = None
        context.update(_simulated_analytics(camera, params, now, tick))
        return context

    # Kamera RTSP: analitik nyata bila deteksi sudah menghasilkan data, selain itu kosong + alasan.
    detection = get_detection_manager()
    snapshot = detection.snapshot(camera.id)
    context["detection"] = _detection_view(camera, detection.status(camera.id), snapshot)
    if snapshot is not None and snapshot["ready"]:
        context["analytics"] = True
        series = detection.series(camera.id, cfg["points"], cfg["step"])
        context.update(build_live_analytics(camera, snapshot, series, params.range_key, params.event_type))
    else:
        context["analytics"] = False
        context.update(_empty_analytics(camera, params))
    return context


# --- kamera demo (simulasi) ---------------------------------------------------
def _simulated_analytics(camera, params, now, tick):
    cam_index = camera_index(camera)
    minutes_today = now.hour * 60 + now.minute + now.second / 60

    live = live_metrics(camera, tick)
    counts = vehicle_counts(camera, minutes_today)
    speed = speed_analysis(camera, live, counts["total_raw"])
    directions, insight = direction_status(camera, live)
    congestion, volume = build_series(camera, cam_index, params.range_key, live)
    level = FLOW_LEVELS[live.level]
    show_alert = camera.wrong_index >= 0 and (tick % 8) < 3

    return {
        "flow": {
            "key": live.level,
            "label": level["label"],
            "los": level["los"],
            "desc": level["desc"],
            "marker": css_number(clamp(live.density, 2, 98)),
            "speed": round(live.avg_speed),
            "density": round(live.density),
            "rate": live.flow,
            "travel": format_decimal(60 / live.avg_speed),
        },
        "directions": directions,
        "insight": insight,
        "kpi": {
            "total": counts["sum_all"],
            "flow": live.flow,
            "flow_note": f"Puncak hari ini {round(camera.base_flow * 1.4)} kend/mnt",
            "avg": round(live.avg_speed),
            "avg_note": f"Batas kecepatan {camera.speed_limit} km/j",
            "speeding": speed["speeding"],
            "speeding_note": f"{speed['speeding_pct']}% dari total kendaraan",
            "limit": camera.speed_limit,
            "speeding_pct": speed["speeding_pct"],
            "wrong": camera.wrong_today,
            "wrong_tone": "danger" if camera.wrong_today > 0 else "",
        },
        "counts": counts,
        "speed": speed,
        "volume": volume,
        "congestion": congestion,
        "wrong_way": build_wrong_way(camera),
        "events": build_events(camera, params.event_type),
        "vehicles": build_feed_vehicles(camera, cam_index),
        "hud": {"a": counts["sum_a"], "b": counts["sum_b"]},
        "alert": f"Lawan arah terdeteksi · {camera.wrong_lane}" if show_alert else "",
    }


# --- kamera RTSP tambahan (belum ada deteksi) ------------------------------------
def _empty_analytics(camera, params):
    waiting = "Menunggu data deteksi"
    return {
        "flow": {
            "key": "unknown",
            "label": "Belum ada data",
            "los": NO_DATA,
            "desc": "Analitik muncul setelah deteksi berjalan untuk kamera ini.",
            "marker": "0",
            "speed": NO_DATA,
            "density": NO_DATA,
            "rate": NO_DATA,
            "travel": NO_DATA,
        },
        "directions": [],
        "insight": "Belum ada data deteksi untuk kamera ini.",
        "kpi": {
            "total": NO_DATA,
            "flow": NO_DATA,
            "flow_note": waiting,
            "avg": NO_DATA,
            "avg_note": f"Batas kecepatan {camera.speed_limit} km/j",
            "speeding": NO_DATA,
            "speeding_note": waiting,
            "limit": camera.speed_limit,
            "speeding_pct": NO_DATA,
            "wrong": NO_DATA,
            "wrong_tone": "",
        },
        "counts": {
            "rows": [
                {"key": vc["key"], "name": vc["name"], "a": "0", "b": "0", "total": "0", "pct": 0}
                for vc in VEHICLE_CLASSES
            ],
            "sum_a": "0",
            "sum_b": "0",
            "sum_all": "0",
            "total_raw": 0,
        },
        "speed": {
            "bins": [
                {"label": label, "count": "0", "h": "0.0", "over": lower >= camera.speed_limit}
                for label, lower in SPEED_BINS
            ],
            "avg": NO_DATA,
            "max": NO_DATA,
            "limit": camera.speed_limit,
            "speeding": NO_DATA,
            "speeding_pct": NO_DATA,
        },
        "volume": {"bars": [], "y_max": "0", "y_mid": "0"},
        "congestion": {"bars": [], "peak": NO_DATA, "share": NO_DATA},
        "wrong_way": {
            "count": NO_DATA,
            "has": False,
            "last_time": "Belum ada kejadian",
            "last_detail": waiting + ".",
        },
        "events": [],
        "vehicles": [],
        "hud": {"a": NO_DATA, "b": NO_DATA},
        "alert": "",
    }


# --- umum --------------------------------------------------------------------
def _live_level(cam):
    """Level arus kamera RTSP dari deteksi, atau None bila belum ada data."""
    snapshot = get_detection_manager().snapshot(cam.id)
    if snapshot is not None and snapshot["ready"]:
        return snapshot["level"]
    return None


def _camera_tabs(active_camera, tick):
    tabs = []
    for cam in list_cameras():
        live_level = None if cam.has_analytics else _live_level(cam)
        if live_level:
            level_key, level_label = live_level, FLOW_LEVELS[live_level]["label"]
        elif cam.has_analytics:
            cam_live = live_metrics(cam, tick)
            level_key = classify_flow(cam_live.avg_speed, cam_live.density, cam.speed_limit)
            level_label = FLOW_LEVELS[level_key]["label"]
        else:
            level_key, level_label = "unknown", "RTSP"
        tabs.append(
            {
                "id": cam.id,
                "short": cam.short,
                "active": cam.id == active_camera.id,
                "level": level_key,
                "level_label": level_label,
            }
        )
    return tabs


def _stream_view(camera):
    """Status koneksi nyata untuk kamera RTSP; None untuk kamera demo."""
    if camera.source != "rtsp":
        return None
    status = get_manager().status(camera.id)
    state = status.state if status else "idle"
    return {
        "state": state,
        "label": _STREAM_LABELS.get(state, state.upper()),
        "message": status.message if status and state != "live" else "",
        "resolution": f"{status.width}×{status.height}" if status and status.width else "",
        "fps": f"{status.fps:.0f}" if status and status.fps else "",
    }


def _detection_view(camera, status, snapshot):
    """Ringkasan status deteksi untuk kamera RTSP (pesan di bawah video)."""
    state = status.state
    calibrated = bool(snapshot and snapshot["configured"])
    ready = bool(snapshot and snapshot["ready"])
    speed_ready = bool(snapshot and snapshot["speed_ready"])
    wrong_ready = bool(snapshot and snapshot["can_wrong_way"])

    if state == "unavailable":
        notice = f"Deteksi belum aktif. {status.message}"
    elif state == "error":
        notice = status.message or "Deteksi bermasalah."
    elif state == "loading" or not ready:
        notice = "Memuat model deteksi dan menunggu frame pertama…"
    elif not calibrated:
        notice = "Kalibrasi belum diatur: Arah A dianggap kiri ke kanan; kecepatan dan lawan arah nonaktif."
    elif not speed_ready or not wrong_ready:
        missing = []
        if not speed_ready:
            missing.append("kecepatan (jarak referensi)")
        if not wrong_ready:
            missing.append("lawan arah (median atau jalan satu arah)")
        notice = "Belum aktif: " + " dan ".join(missing) + "."
    else:
        notice = ""
    return {
        "state": state,
        "notice": notice,
        "calibration_json": json.dumps(camera.calibration, separators=(",", ":")) if camera.calibration else "",
        "calibrated": calibrated,
        "infer_ms": round(status.infer_ms),
        "fps": f"{status.fps:.1f}".replace(".", ",") if status.fps else "",
        "provider": (status.provider or "").upper(),
    }
