"""Pengaturan streaming. Dapat diubah lewat variabel lingkungan TRAFFICSENSE_*."""
import os
from dataclasses import dataclass


def _env_number(name, default, cast):
    try:
        return cast(os.environ[name])
    except (KeyError, ValueError):
        return default


@dataclass(frozen=True)
class StreamConfig:
    transport: str = "tcp"  # tcp lebih andal daripada udp pada jaringan yang kehilangan paket
    max_width: int = 1280  # frame lebih lebar diperkecil sebelum dikirim ke browser
    jpeg_quality: int = 80
    max_fps: float = 15.0  # batas kirim ke browser (pembacaan tetap penuh)
    open_timeout_ms: int = 8000
    read_timeout_ms: int = 8000
    retry_min: float = 2.0  # jeda awal sebelum mencoba sambung ulang (detik)
    retry_max: float = 30.0
    idle_stop_seconds: float = 20.0  # hentikan pembaca bila tak ada penonton selama ini
    placeholder_interval: float = 2.0  # kirim gambar "menghubungkan" tiap sekian detik


def load_config():
    return StreamConfig(
        transport=os.environ.get("TRAFFICSENSE_RTSP_TRANSPORT", "tcp").lower(),
        max_width=_env_number("TRAFFICSENSE_STREAM_MAX_WIDTH", 1280, int),
        jpeg_quality=_env_number("TRAFFICSENSE_STREAM_JPEG_QUALITY", 80, int),
        max_fps=_env_number("TRAFFICSENSE_STREAM_MAX_FPS", 15.0, float),
    )
