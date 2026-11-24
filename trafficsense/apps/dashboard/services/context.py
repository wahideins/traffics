"""Perakit konteks template: satu fungsi yang dipakai halaman penuh dan semua panel."""
from .cameras import camera_index, get_camera, list_cameras
from .constants import (
    FLOW_LEVELS,
    TICK_SECONDS,
    TIME_RANGES,
    VEHICLE_CLASSES,
)
from .events import build_event_filters, build_events, build_wrong_way
from .formatting import css_number, format_decimal
from .metrics import (
    clamp,
    classify_flow,
    direction_status,
    live_metrics,
    speed_analysis,
    vehicle_counts,
)
from .series import build_series
from .vehicles import build_feed_vehicles


def build_dashboard_context(params, now) -> dict:
    """`params`: DashboardParams. `now`: datetime lokal (aware)."""
    camera = get_camera(params.camera_id)
    cam_index = camera_index(camera)
    cfg = TIME_RANGES[params.range_key]

    tick = int(now.timestamp() // TICK_SECONDS)
    minutes_today = now.hour * 60 + now.minute + now.second / 60

    live = live_metrics(camera, tick)
    counts = vehicle_counts(camera, minutes_today)
    speed = speed_analysis(camera, live, counts["total_raw"])
    directions, insight = direction_status(camera, live)
    congestion, volume = build_series(camera, cam_index, params.range_key, live)
    level = FLOW_LEVELS[live.level]

    show_alert = camera.wrong_index >= 0 and (tick % 8) < 3

    wrong_way = build_wrong_way(camera)

    return {
        "camera": camera,
        "cameras": _camera_tabs(camera, tick),
        "vehicle_classes": VEHICLE_CLASSES,
        # Rentang waktu
        "time_range": {"key": params.range_key, "label": cfg["label"], "unit": cfg["unit"], "x_labels": cfg["x_labels"]},
        "ranges": [
            {"key": key, "label": value["label"], "active": key == params.range_key}
            for key, value in TIME_RANGES.items()
        ],
        # Status arus
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
        # KPI
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
        # Panel analitik
        "counts": counts,
        "speed": speed,
        "volume": volume,
        "congestion": congestion,
        "wrong_way": wrong_way,
        # Kejadian
        "event_type": params.event_type,
        "event_filters": build_event_filters(params.event_type),
        "events": build_events(camera, params.event_type),
        # Pratinjau kamera
        "vehicles": build_feed_vehicles(camera, cam_index),
        "hud": {"a": counts["sum_a"], "b": counts["sum_b"]},
        "alert": f"Lawan arah terdeteksi · {camera.wrong_lane}" if show_alert else "",
    }


def _camera_tabs(active_camera, tick):
    tabs = []
    for cam in list_cameras():
        cam_live = live_metrics(cam, tick)
        level_key = classify_flow(cam_live.avg_speed, cam_live.density, cam.speed_limit)
        tabs.append(
            {
                "id": cam.id,
                "short": cam.short,
                "active": cam is active_camera,
                "level": level_key,
                "level_label": FLOW_LEVELS[level_key]["label"],
            }
        )
    return tabs
