"""Pengelolaan berkas model ONNX: daftar, unggah, hapus, dan uji (bentuk keluaran + waktu inferensi)."""
import os
import re
import tempfile
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from .detector import DetectorUnavailable, YoloOnnxDetector

MAX_MODEL_BYTES = 400 * 1024 * 1024
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.onnx$", re.IGNORECASE)
COCO_CLASSES = 80


class ModelError(ValueError):
    """Pesan aman ditampilkan ke pengguna."""


def check_name(name):
    if not isinstance(name, str) or not NAME_RE.match(name) or ".." in name:
        raise ModelError("Nama berkas hanya boleh huruf, angka, titik, minus, garis bawah, dan berakhiran .onnx.")
    return name


def list_models(models_dir):
    models_dir = Path(models_dir)
    items = []
    try:
        for path in sorted(models_dir.iterdir()):
            if path.is_file() and path.suffix.lower() == ".onnx":
                stat = path.stat()
                items.append({"name": path.name, "size_mb": round(stat.st_size / 1024 / 1024, 1), "mtime": stat.st_mtime})
    except OSError:
        pass
    return items


def classify_output(shape):
    """Kenali tata letak keluaran dari bentuknya. Kembalikan (nama_tata_letak, jumlah_kelas|None)."""
    dims = [d if isinstance(d, int) else None for d in shape]
    if len(dims) == 3 and dims[2] == 6:
        return "end-to-end (x1,y1,x2,y2,skor,kelas)", None
    if len(dims) == 3:
        _, a, b = dims
        if a is not None and (b is None or a < b) and 5 <= a <= 1100:
            return "YOLOv8/v11 (4+kelas, N)", a - 4
        if b is not None and (a is None or b < a) and 5 <= b <= 1100:
            return "YOLO transposisi (N, 4+kelas)", b - 4
    return "tidak dikenali", None


def inspect_model(path, config, *, runs=3):
    """Muat model sungguhan dan ukur kecepatannya pada frame kosong 1280x720. Lempar ModelError bila gagal."""
    try:
        detector = YoloOnnxDetector(replace(config, model_path=str(path)))
    except DetectorUnavailable as exc:
        raise ModelError(str(exc)) from exc
    session = detector._session
    out_shape = list(session.get_outputs()[0].shape)
    layout, nc = classify_output(out_shape)
    if layout == "tidak dikenali":
        raise ModelError(f"Format keluaran model {out_shape} tidak dikenali. Gunakan ekspor YOLOv8/v11/v26 (format=onnx).")

    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    try:
        detector.detect(frame)  # pemanasan
        started = time.perf_counter()
        for _ in range(runs):
            detector.detect(frame)
        ms = (time.perf_counter() - started) / runs * 1000
    except Exception as exc:  # noqa: BLE001
        raise ModelError("Model dimuat tetapi gagal dijalankan. Pastikan ekspornya float32 dengan masukan gambar.") from exc

    warnings = []
    if nc is not None and nc != COCO_CLASSES:
        warnings.append(f"Model punya {nc} kelas; hanya model COCO ({COCO_CLASSES} kelas) yang dipetakan ke mobil/motor/bus/truk.")
    return {
        "layout": layout,
        "input": list(session.get_inputs()[0].shape),
        "output": out_shape,
        "provider": detector.provider.upper(),
        "ms": round(ms, 1),
        "max_fps": round(1000 / ms, 1) if ms > 0 else None,
        "warnings": warnings,
    }


def save_model(models_dir, name, chunks, *, max_bytes=MAX_MODEL_BYTES):
    """Simpan unggahan secara atomik. `chunks`: iterator bytes. Lempar ModelError bila ditolak."""
    check_name(name)
    models_dir = Path(models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)
    target = models_dir / name
    if target.exists():
        raise ModelError(f"Model {name} sudah ada. Hapus dulu atau ganti nama berkas.")
    fd, tmp = tempfile.mkstemp(dir=models_dir, suffix=".part")
    size = 0
    try:
        with os.fdopen(fd, "wb") as fh:
            for chunk in chunks:
                size += len(chunk)
                if size > max_bytes:
                    raise ModelError(f"Berkas terlalu besar (maksimum {max_bytes // 1024 // 1024} MB).")
                fh.write(chunk)
        if size == 0:
            raise ModelError("Berkas kosong.")
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return target


def delete_model(models_dir, name, *, active_name=""):
    check_name(name)
    if name == active_name:
        raise ModelError("Model ini sedang dipakai. Pilih model lain dulu.")
    path = Path(models_dir) / name
    try:
        path.unlink()
    except FileNotFoundError as exc:
        raise ModelError("Model tidak ditemukan.") from exc
