"""Tes koneksi sekali jalan: buka stream, ambil satu frame, tutup."""
import threading
from dataclasses import dataclass, replace

from ..services.rtsp_url import redact_text
from .capture import CaptureUnavailable, open_capture
from .config import load_config


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    message: str
    width: int = 0
    height: int = 0


def probe_stream(url, config=None, *, timeout=10.0, capture_factory=open_capture):
    """Coba baca satu frame dari `url`. Tidak pernah melempar; hasil selalu ProbeResult."""
    config = replace(
        config or load_config(),
        open_timeout_ms=int(timeout * 1000),
        read_timeout_ms=int(timeout * 1000),
    )
    outcome = {}

    def work():
        capture = None
        try:
            capture = capture_factory(url, config)
            if not capture.isOpened():
                outcome["result"] = ProbeResult(
                    False, "Tidak dapat membuka stream. Periksa URL, kredensial, dan jaringan."
                )
                return
            frame = None
            for _ in range(20):  # beberapa frame awal bisa kosong
                ok, candidate = capture.read()
                if ok and candidate is not None:
                    frame = candidate
                    break
            if frame is None:
                outcome["result"] = ProbeResult(False, "Terhubung, tetapi tidak ada gambar yang diterima.")
                return
            height, width = frame.shape[:2]
            outcome["result"] = ProbeResult(True, f"Terhubung: {width}×{height}", width, height)
        except CaptureUnavailable as exc:
            outcome["result"] = ProbeResult(False, str(exc))
        except Exception as exc:  # noqa: BLE001
            outcome["result"] = ProbeResult(False, "Gagal menguji koneksi: " + redact_text(str(exc), url)[:160])
        finally:
            if capture is not None:
                try:
                    capture.release()
                except Exception:  # noqa: BLE001
                    pass

    thread = threading.Thread(target=work, name="rtsp-probe", daemon=True)
    thread.start()
    thread.join(timeout + 2.0)
    if thread.is_alive():
        return ProbeResult(False, "Waktu habis saat menghubungi kamera.")
    return outcome.get("result") or ProbeResult(False, "Gagal menguji koneksi.")
