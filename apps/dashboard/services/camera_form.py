"""Validasi isian tambah kamera. Tidak bergantung pada Django (mudah diuji)."""
import re
from dataclasses import dataclass, field

from .rtsp_url import RtspUrlError, build_rtsp_url

NAME_MIN, NAME_MAX = 2, 60
DIR_MAX = 24
SPEED_MIN, SPEED_MAX, SPEED_DEFAULT = 10, 150, 60
DEFAULT_DIR_A = "Kiri ke kanan"
DEFAULT_DIR_B = "Kanan ke kiri"


@dataclass(frozen=True)
class CameraInput:
    name: str
    source_url: str = field(repr=False)  # RAHASIA: dapat memuat kredensial
    dir_a: str
    dir_b: str
    speed_limit: int


def _clean_text(value):
    return re.sub(r"\s+", " ", (value or "")).strip()


def validate_camera_input(data, *, require_name=True):
    """Kembalikan (CameraInput | None, errors).

    `data`: mapping dengan `.get` (QueryDict atau dict). Kunci: name, rtsp_url,
    username, password, dir_a, dir_b, speed_limit. `errors` memetakan nama
    kolom ke pesan; kosong berarti valid.
    """
    errors = {}

    name = _clean_text(data.get("name"))
    if require_name or name:
        if len(name) < NAME_MIN:
            errors["name"] = f"Nama kamera minimal {NAME_MIN} karakter."
        elif len(name) > NAME_MAX:
            errors["name"] = f"Nama kamera maksimum {NAME_MAX} karakter."

    source_url = ""
    try:
        source_url = build_rtsp_url(data.get("rtsp_url"), data.get("username"), data.get("password"))
    except RtspUrlError as exc:
        field = "username" if "username" in str(exc).lower() or "kredensial" in str(exc).lower() else "rtsp_url"
        errors[field] = str(exc)

    dir_a = _clean_text(data.get("dir_a")) or DEFAULT_DIR_A
    dir_b = _clean_text(data.get("dir_b")) or DEFAULT_DIR_B
    for field, value in (("dir_a", dir_a), ("dir_b", dir_b)):
        if len(value) > DIR_MAX:
            errors[field] = f"Maksimum {DIR_MAX} karakter."

    raw_limit = _clean_text(data.get("speed_limit"))
    speed_limit = SPEED_DEFAULT
    if raw_limit:
        try:
            speed_limit = int(raw_limit)
        except ValueError:
            errors["speed_limit"] = "Batas kecepatan harus berupa angka."
        else:
            if not SPEED_MIN <= speed_limit <= SPEED_MAX:
                errors["speed_limit"] = f"Batas kecepatan antara {SPEED_MIN} dan {SPEED_MAX} km/j."

    if errors:
        return None, errors
    return CameraInput(name, source_url, dir_a, dir_b, speed_limit), {}
