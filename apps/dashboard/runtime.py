"""Menyambungkan stream video dengan deteksi untuk kamera RTSP.

Satu tempat yang tahu cara menyalakan sebuah kamera: dipakai view, tambah/hapus
kamera, dan autostart saat server hidup.
"""
import logging

from .detection.manager import get_detection_manager
from .services.registry import list_cameras
from .streaming import get_manager

LOG = logging.getLogger(__name__)


def ensure_camera(camera):
    """Pastikan pembaca stream (dan deteksi bila aktif) berjalan. Kembalikan RtspReader."""
    pipeline = get_detection_manager().ensure(camera)
    keep_alive = pipeline is not None and pipeline.active
    return get_manager().ensure(
        camera.id,
        camera.source_url,
        on_frame=pipeline.submit if pipeline else None,
        annotate=pipeline.annotate if pipeline else None,
        keep_alive=keep_alive,
    )


def stop_camera(code, *, delete_state=False):
    get_manager().stop(code)
    get_detection_manager().remove(code, delete_state=delete_state)


def start_all():
    """Nyalakan semua kamera RTSP yang tersimpan bila deteksi aktif (agar penghitungan 24 jam tak bergantung penonton)."""
    detection = get_detection_manager()
    if not (detection.enabled and detection.config.autostart):
        return []
    started = []
    for camera in list_cameras():
        if camera.source == "rtsp":
            try:
                ensure_camera(camera)
                started.append(camera.id)
            except Exception:  # noqa: BLE001
                LOG.exception("Gagal menyalakan kamera %s", camera.id)
    return started
