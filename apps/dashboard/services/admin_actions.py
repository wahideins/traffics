"""Tindakan panel admin: simpan pengaturan, ganti model, uji model, kelola kamera, info sistem."""
import logging
import json
import os
import platform
from dataclasses import replace

from .. import runtime
from ..detection import model_tools
from ..detection.manager import get_detection_manager
from ..streaming import get_manager
from . import app_settings
from .registry import get_live_camera, list_cameras

LOG = logging.getLogger(__name__)


def apply_settings(raw):
    """Simpan isian formulir (kolom kosong = pakai bawaan) dan terapkan. Kembalikan (hasil, galat)."""
    store = app_settings.get_store()
    values, errors = store.validate(raw)
    if errors:
        return None, errors
    before = store.overrides()
    if values == before:
        return {"changed": False, "restarted": False}, {}
    if values:
        store.save(values)
    else:
        store.reset()
    runtime.restart_all()
    return {"changed": True, "restarted": True}, {}


def reset_settings():
    app_settings.get_store().reset()
    runtime.restart_all()


def set_active_model(name):
    """Pakai model dari folder model, lalu mulai ulang deteksi. Lempar ModelError bila tak sah."""
    store = app_settings.get_store()
    model_tools.check_name(name)
    if name not in store.model_names():
        raise model_tools.ModelError("Model tidak ditemukan.")
    store.save({**store.overrides(), "model": name})
    runtime.restart_all()


def test_model(name):
    store = app_settings.get_store()
    model_tools.check_name(name)
    if name not in store.model_names():
        raise model_tools.ModelError("Model tidak ditemukan.")
    return model_tools.inspect_model(store.models_dir / name, store.detection_config())


def upload_model(name, chunks):
    """Simpan unggahan lalu uji; bila gagal diuji, berkasnya dihapus. Kembalikan hasil uji."""
    store = app_settings.get_store()
    path = model_tools.save_model(store.models_dir, name, chunks)
    try:
        return model_tools.inspect_model(path, store.detection_config(), runs=2)
    except model_tools.ModelError:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def remove_model(name):
    store = app_settings.get_store()
    active = store.overrides().get("model", "")
    model_tools.delete_model(store.models_dir, name, active_name=active)


def restart_camera(code):
    camera = get_live_camera(code)
    if camera is None:
        return False
    runtime.stop_camera(code)
    runtime.ensure_camera(camera)
    return True


def reset_camera_counts(code):
    pipeline = get_detection_manager().get(code)
    if pipeline is None:
        return False
    pipeline.analyzer.reset()
    pipeline.save_now()
    return True


def zone_stats(code):
    """Statistik zona kamera yang sedang berdeteksi, atau None bila deteksi belum berjalan."""
    pipeline = get_detection_manager().get(code)
    if pipeline is None:
        return None
    return pipeline.analyzer.snapshot()["zones"]


def camera_overview():
    detection = get_detection_manager()
    rows = []
    for cam in list_cameras():
        if cam.source != "rtsp":
            continue
        d = detection.status(cam.id)
        reader = get_manager().get(cam.id)
        r = reader.status() if reader else None
        snap = detection.snapshot(cam.id)
        total = sum(sum(c.values()) for c in snap["counts"].values()) if snap else None
        rows.append({
            "id": cam.id, "name": cam.name, "url": cam.display_url,
            "stream": r.state if r else "idle",
            "detect_state": d.state, "detect_message": d.message,
            "fps": f"{d.fps:.1f}".replace(".", ",") if d.fps else "",
            "ms": round(d.infer_ms) if d.infer_ms else "",
            "provider": (d.provider or "").upper(),
            "total": total,
            "calibrated": bool(cam.calibration),
            "calibration_json": json.dumps(cam.calibration, separators=(",", ":")) if cam.calibration else "",
            "dir_a": cam.dir_a, "dir_b": cam.dir_b,
            "deletable": getattr(cam, "deletable", False),
        })
    return rows


def system_info():
    info = {
        "Python": platform.python_version(),
        "Sistem": f"{platform.system()} {platform.release()}",
        "CPU": f"{os.cpu_count()} inti",
    }
    try:
        import onnxruntime as ort

        info["onnxruntime"] = ort.__version__
        info["Perangkat tersedia"] = ", ".join(p.replace("ExecutionProvider", "") for p in ort.get_available_providers())
    except ImportError:
        info["onnxruntime"] = "belum terpasang"
    try:
        import cv2

        info["OpenCV"] = cv2.__version__
    except ImportError:
        info["OpenCV"] = "belum terpasang"
    store = app_settings.get_store()
    info["Folder model"] = str(store.models_dir)
    info["Berkas pengaturan"] = str(store.path)
    return info
