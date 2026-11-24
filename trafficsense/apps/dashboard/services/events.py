"""Log kejadian dan ringkasan deteksi lawan arah."""
from .constants import EVENT_FILTERS, EVENT_TYPES, SEVERITY_LABELS


def build_events(camera, event_type):
    return [
        {
            "time": event.time,
            "type": event.type,
            "type_label": EVENT_TYPES[event.type],
            "detail": event.detail,
            "lane": event.lane,
            "severity": event.severity,
            "severity_label": SEVERITY_LABELS[event.severity],
        }
        for event in camera.events
        if event_type == "all" or event.type == event_type
    ]


def build_event_filters(active_key):
    return [
        {"key": key, "label": label, "active": key == active_key}
        for key, label in EVENT_FILTERS
    ]


def build_wrong_way(camera):
    wrong_events = [event for event in camera.events if event.type == "wrong"]
    last = wrong_events[0] if wrong_events else None
    return {
        "count": camera.wrong_today,
        "has": camera.wrong_today > 0,
        "last_time": f"{last.time} WIB" if last else "Belum ada kejadian",
        "last_detail": (
            f"{last.detail} · {last.lane}"
            if last
            else "Tidak ada kendaraan melawan arah pada kamera ini."
        ),
    }
