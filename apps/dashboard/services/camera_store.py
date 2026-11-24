"""Penyimpanan kamera tambahan (berkas JSON).

Cukup untuk tahap ini (satu proses, sedikit kamera). Antarmukanya (list/get/
add/delete) sengaja kecil agar nanti mudah diganti model Django + database.

Catatan keamanan: berkas ini menyimpan URL RTSP lengkap beserta kredensial
dalam teks biasa. Izin berkas diset 0600 dan foldernya masuk .gitignore,
tetapi untuk produksi simpan kredensial terenkripsi atau di secret manager.
"""
import json
import logging
import os
import re
import tempfile
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from .rtsp_url import mask_url

LOG = logging.getLogger(__name__)

_CODE_RE = re.compile(r"^CAM-(\d+)$")
_SHORT_MAX = 22


@dataclass(frozen=True)
class LiveCamera:
    """Kamera RTSP tambahan. Analitik hanya ada bila modul deteksi berjalan untuk kamera ini."""

    id: str
    name: str
    short: str
    source_url: str = field(repr=False)  # RAHASIA: jangan diteruskan ke template
    speed_limit: int
    dir_a: str
    dir_b: str
    created_at: str
    # Kalibrasi arah/garis hitung/skala (lihat detection/calibration.py); kosong = belum diatur.
    calibration: dict = field(default_factory=dict, compare=False, hash=False)

    source = "rtsp"
    has_analytics = False
    deletable = True

    @property
    def display_url(self):
        return mask_url(self.source_url)


class CameraStore:
    def __init__(self, path):
        self._path = Path(path)
        self._lock = threading.RLock()
        self._cache = None
        self._cache_mtime = None

    # --- baca ---------------------------------------------------------
    def list(self):
        with self._lock:
            return list(self._load())

    def get(self, code):
        for camera in self.list():
            if camera.id == code:
                return camera
        return None

    # --- tulis --------------------------------------------------------
    def add(self, *, name, source_url, dir_a, dir_b, speed_limit, reserved_codes=()):
        with self._lock:
            cameras = list(self._load())
            code = _next_code([c.id for c in cameras] + list(reserved_codes))
            camera = LiveCamera(
                id=code,
                name=name,
                short=name if len(name) <= _SHORT_MAX else name[: _SHORT_MAX - 1] + "…",
                source_url=source_url,
                speed_limit=speed_limit,
                dir_a=dir_a,
                dir_b=dir_b,
                created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            self._write(cameras + [camera])
            return camera

    def update_calibration(self, code, calibration):
        """Simpan kalibrasi (dict yang sudah divalidasi). Kembalikan kamera baru, atau None bila tak ada."""
        with self._lock:
            cameras = list(self._load())
            for i, camera in enumerate(cameras):
                if camera.id == code:
                    cameras[i] = replace(camera, calibration=dict(calibration))
                    self._write(cameras)
                    return cameras[i]
            return None

    def delete(self, code):
        with self._lock:
            cameras = list(self._load())
            remaining = [c for c in cameras if c.id != code]
            if len(remaining) == len(cameras):
                return False
            self._write(remaining)
            return True

    # --- internal -----------------------------------------------------
    def _load(self):
        try:
            mtime = self._path.stat().st_mtime_ns
        except FileNotFoundError:
            self._cache, self._cache_mtime = [], None
            return self._cache
        if self._cache is not None and mtime == self._cache_mtime:
            return self._cache

        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            cameras = [LiveCamera(**item) for item in payload["cameras"]]
        except (ValueError, KeyError, TypeError, OSError):
            # Jangan menghilangkan data diam-diam: simpan berkas rusak untuk dipulihkan manual.
            backup = self._path.with_suffix(".json.corrupt")
            LOG.error("Berkas kamera rusak, dipindahkan ke %s", backup)
            try:
                os.replace(self._path, backup)
            except OSError:
                pass
            cameras, mtime = [], None
        self._cache, self._cache_mtime = cameras, mtime
        return cameras

    def _write(self, cameras):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "cameras": [
                {
                    "id": c.id,
                    "name": c.name,
                    "short": c.short,
                    "source_url": c.source_url,
                    "speed_limit": c.speed_limit,
                    "dir_a": c.dir_a,
                    "dir_b": c.dir_b,
                    "created_at": c.created_at,
                    "calibration": c.calibration,
                }
                for c in cameras
            ],
        }
        # Tulis atomik: berkas sementara di folder yang sama lalu os.replace.
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".cameras-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self._path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        self._cache = None  # paksa baca ulang (mtime berubah)


def _next_code(existing_codes):
    numbers = [int(m.group(1)) for code in existing_codes if (m := _CODE_RE.match(code))]
    return f"CAM-{(max(numbers) + 1) if numbers else 1:02d}"
