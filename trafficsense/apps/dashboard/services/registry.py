"""Registry kamera: gabungan kamera demo dan kamera RTSP tambahan pengguna."""
import os
import threading
from pathlib import Path

from .camera_store import CameraStore
from .cameras import CAMERAS

_store = None
_lock = threading.Lock()


def configure(store_path):
    """Dipanggil sekali saat aplikasi siap (apps.py) dengan lokasi berkas penyimpanan."""
    global _store
    with _lock:
        _store = CameraStore(store_path)


def get_store():
    global _store
    with _lock:
        if _store is None:
            default = os.environ.get("TRAFFICSENSE_CAMERA_STORE") or Path.cwd() / "data" / "cameras.json"
            _store = CameraStore(default)
        return _store


def demo_codes():
    return [camera.id for camera in CAMERAS]


def list_cameras():
    return list(CAMERAS) + get_store().list()


def find_camera(code):
    """Kamera dengan kode tersebut, atau None."""
    for camera in list_cameras():
        if camera.id == code:
            return camera
    return None


def get_camera(code):
    """Kamera sesuai kode; kode tak dikenal jatuh ke kamera demo pertama."""
    return find_camera(code) or CAMERAS[0]


def get_live_camera(code):
    """Kamera RTSP tambahan (punya sumber nyata), atau None."""
    return get_store().get(code)


def camera_index(camera):
    """Indeks untuk seed simulasi (hanya bermakna bagi kamera demo)."""
    try:
        return CAMERAS.index(camera)
    except ValueError:
        return 0
