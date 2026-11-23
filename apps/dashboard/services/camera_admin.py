"""Operasi kelola kamera: tes koneksi, tambah, hapus, sambung ulang.

View hanya meneruskan data ke sini, jadi logikanya bisa diuji tanpa Django.
"""
from ..streaming import get_manager
from ..streaming.probe import probe_stream
from .camera_form import validate_camera_input
from .registry import demo_codes, get_live_camera, get_store


def probe_camera(data):
    """Tes koneksi dari isian form. Kembalikan dict JSON-siap (tanpa kredensial)."""
    cleaned, errors = validate_camera_input(data, require_name=False)
    if errors:
        return {"ok": False, "message": "Isian belum valid.", "errors": errors}
    result = probe_stream(cleaned.source_url)
    return {"ok": result.ok, "message": result.message, "width": result.width, "height": result.height}


def create_camera(data):
    """Simpan kamera baru. Kembalikan (LiveCamera | None, errors)."""
    cleaned, errors = validate_camera_input(data, require_name=True)
    if errors:
        return None, errors
    camera = get_store().add(
        name=cleaned.name,
        source_url=cleaned.source_url,
        dir_a=cleaned.dir_a,
        dir_b=cleaned.dir_b,
        speed_limit=cleaned.speed_limit,
        reserved_codes=demo_codes(),
    )
    return camera, {}


def delete_camera(code):
    """Hapus kamera tambahan dan hentikan pembacanya. Kamera demo tidak bisa dihapus."""
    if get_live_camera(code) is None:
        return False
    get_manager().stop(code)
    return get_store().delete(code)


def reconnect_camera(code):
    """Sambung ulang kamera RTSP. True bila kamera dikenal."""
    camera = get_live_camera(code)
    if camera is None:
        return False
    manager = get_manager()
    if not manager.reconnect(code):
        manager.ensure(code, camera.source_url)
    return True
