"""Generator multipart/x-mixed-replace (MJPEG) untuk <img src=...>."""
from .frames import placeholder_jpeg
from .reader import LIVE

BOUNDARY = "frame"
CONTENT_TYPE = f"multipart/x-mixed-replace; boundary={BOUNDARY}"

_PLACEHOLDER_TEXT = {
    "connecting": "Menghubungkan ke kamera...",
    "error": "Tidak dapat terhubung. Mencoba lagi...",
}


def _part(jpeg):
    header = (
        f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(jpeg)}\r\n\r\n"
    ).encode("ascii")
    return header + jpeg + b"\r\n"


def mjpeg_stream(reader, *, wait=2.0):
    """Hasilkan bagian multipart selama reader hidup dan klien masih terhubung.

    Saat belum ada frame, kirim gambar placeholder berkala. Ini juga yang
    membuat putusnya koneksi klien terdeteksi (penulisan gagal), sehingga
    thread server tidak tertahan selamanya.
    """
    last_id = 0
    with reader.viewer():
        while True:
            item = reader.wait_for_frame(last_id, timeout=wait)
            if item is not None:
                last_id, jpeg = item
                yield _part(jpeg)
                continue

            status = reader.status()
            if reader.stopped or status.fatal:
                return
            if status.state != LIVE:
                text = _PLACEHOLDER_TEXT.get(status.state, _PLACEHOLDER_TEXT["connecting"])
                yield _part(placeholder_jpeg(text))
