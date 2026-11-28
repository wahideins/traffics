"""Pengaturan perekaman. Dapat diubah lewat variabel lingkungan TRAFFICSENSE_* atau panel admin."""
import os
from dataclasses import dataclass


def _env(name, default, cast):
    try:
        return cast(os.environ[name])
    except (KeyError, ValueError):
        return default


@dataclass(frozen=True)
class RecordingConfig:
    record: int = 1  # 1 = rekam selama kamera menyala
    record_fps: float = 10.0  # frame per detik yang disimpan (bukan fps kamera)
    record_segment_minutes: int = 5  # panjang tiap berkas
    record_max_width: int = 960  # frame lebih lebar diperkecil sebelum disimpan
    record_max_gb: float = 20.0  # batas total penyimpanan; berkas tertua dihapus. 0 = tanpa batas
    idle_close_seconds: float = 5.0  # tutup berkas bila tak ada frame selama ini
    queue_size: int = 60

    @property
    def enabled(self):
        return bool(self.record)


def load_config():
    return RecordingConfig(
        record=_env("TRAFFICSENSE_RECORD", 1, int),
        record_fps=_env("TRAFFICSENSE_RECORD_FPS", 10.0, float),
        record_segment_minutes=_env("TRAFFICSENSE_RECORD_SEGMENT_MINUTES", 5, int),
        record_max_width=_env("TRAFFICSENSE_RECORD_MAX_WIDTH", 960, int),
        record_max_gb=_env("TRAFFICSENSE_RECORD_MAX_GB", 20.0, float),
    )
