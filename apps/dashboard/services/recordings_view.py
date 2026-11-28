"""Data rekaman untuk panel admin dan pelayanan berkas dengan Range (tanpa Django; mudah diuji)."""
import shutil
from datetime import datetime

from ..recording import get_recording_manager
from .registry import list_cameras

PAGE = 40


def human_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024


def human_duration(seconds):
    s = int(seconds or 0)
    h, rest = divmod(s, 3600)
    m, sec = divmod(rest, 60)
    return f"{h}j {m:02d}m" if h else f"{m}m {sec:02d}d"


STATUS_LABEL = {"recording": "Merekam", "done": "Selesai", "interrupted": "Terputus", "error": "Galat"}


def overview(camera=None, limit=PAGE):
    manager = get_recording_manager()
    names = {c.id: c.name for c in list_cameras()}
    info = {
        "enabled": manager.enabled,
        "has_ffmpeg": shutil.which("ffmpeg") is not None,
        "rows": [], "count": 0, "total_size": "0 B", "error": "",
    }
    try:
        store = manager.store
        rows = store.list(camera=camera, limit=limit)
        info["count"] = store.count(camera)
        info["total_size"] = human_size(store.total_bytes())
    except Exception as exc:  # noqa: BLE001  (basis data rusak/tak bisa dibuka)
        info["error"] = "Basis data rekaman tidak bisa dibuka."
        return info
    for r in rows:
        started = datetime.fromtimestamp(r["started_at"])
        info["rows"].append({
            "id": r["id"], "camera": names.get(r["camera"], r["camera"]),
            "started": started.strftime("%d/%m/%Y %H:%M:%S"),
            "duration": human_duration(r["duration"]) if r["status"] != "recording" else "…",
            "size": human_size(r["size_bytes"]),
            "status": STATUS_LABEL.get(r["status"], r["status"]),
            "live": r["status"] == "recording",
            "playable": r["codec"] == "h264",
            "resolution": f"{r['width']}×{r['height']}" if r["width"] else "",
        })
    return info


def parse_range(header, size):
    """Header Range 'bytes=a-b' -> (start, end) inklusif; None bila tak ada; ValueError bila tak sah."""
    if not header:
        return None
    if not header.startswith("bytes=") or "," in header:
        raise ValueError("Range tidak didukung")
    first, _, last = header[6:].strip().partition("-")
    try:
        if first == "":
            n = int(last)
            if n <= 0:
                raise ValueError
            start, end = max(size - n, 0), size - 1
        else:
            start = int(first)
            end = int(last) if last else size - 1
    except ValueError:
        raise ValueError("Range tidak sah") from None
    end = min(end, size - 1)
    if start > end or start >= size:
        raise ValueError("Range di luar berkas")
    return start, end


def iter_file(path, start, end, chunk=64 * 1024):
    with open(path, "rb") as fh:
        fh.seek(start)
        left = end - start + 1
        while left > 0:
            data = fh.read(min(chunk, left))
            if not data:
                break
            left -= len(data)
            yield data
