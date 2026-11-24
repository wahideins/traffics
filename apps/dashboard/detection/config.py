"""Pengaturan deteksi. Dapat diubah lewat variabel lingkungan TRAFFICSENSE_*."""
import os
from dataclasses import dataclass
from pathlib import Path


def _env(name, default, cast):
    try:
        return cast(os.environ[name])
    except (KeyError, ValueError):
        return default


@dataclass(frozen=True)
class DetectionConfig:
    model_path: str = ""  # berkas ONNX YOLO (v8/v11/v10); kosong = deteksi nonaktif
    conf: float = 0.35  # skor minimum
    nms_iou: float = 0.5
    imgsz: int = 640  # dipakai bila model berukuran masukan dinamis
    detect_fps: float = 5.0  # batas frekuensi inferensi per kamera
    track_max_age: float = 1.5  # detik; objek hilang selama ini dibuang
    track_min_hits: int = 3  # jumlah deteksi sebelum objek dihitung
    state_dir: str = ""  # folder simpan hitungan harian; kosong = tidak disimpan
    autostart: bool = True  # jalankan kamera berdeteksi sejak server hidup


def load_config(base_dir=None) -> DetectionConfig:
    base = Path(base_dir) if base_dir else Path.cwd()
    return DetectionConfig(
        model_path=os.environ.get("TRAFFICSENSE_MODEL", ""),
        conf=_env("TRAFFICSENSE_DETECT_CONF", 0.35, float),
        nms_iou=_env("TRAFFICSENSE_DETECT_NMS_IOU", 0.5, float),
        imgsz=_env("TRAFFICSENSE_DETECT_IMGSZ", 640, int),
        detect_fps=_env("TRAFFICSENSE_DETECT_FPS", 5.0, float),
        state_dir=os.environ.get("TRAFFICSENSE_STATE_DIR", str(base / "data" / "analytics")),
        autostart=os.environ.get("TRAFFICSENSE_AUTOSTART", "1") != "0",
    )
