"""Parsing dan validasi parameter query (?camera=&range=&event_type=)."""
from dataclasses import dataclass

from .constants import DEFAULT_RANGE, EVENT_FILTERS, TIME_RANGES
from .registry import get_camera

_EVENT_KEYS = {key for key, _ in EVENT_FILTERS}


@dataclass(frozen=True)
class DashboardParams:
    camera_id: str
    range_key: str
    event_type: str


def parse_params(query) -> DashboardParams:
    """`query` boleh QueryDict atau dict biasa. Nilai tak valid jatuh ke default."""
    camera = get_camera(query.get("camera"))

    range_key = query.get("range", DEFAULT_RANGE)
    if range_key not in TIME_RANGES:
        range_key = DEFAULT_RANGE

    event_type = query.get("event_type", "all")
    if event_type not in _EVENT_KEYS:
        event_type = "all"

    return DashboardParams(camera.id, range_key, event_type)
