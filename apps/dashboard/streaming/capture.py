"""Membuka stream dengan OpenCV (backend FFmpeg)."""
import os

# Opsi FFmpeg dibaca OpenCV saat stream pertama dibuka, jadi harus diset sebelum itu.
# Pengguna boleh menimpanya dengan mengisi OPENCV_FFMPEG_CAPTURE_OPTIONS sendiri.
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    f"rtsp_transport;{os.environ.get('TRAFFICSENSE_RTSP_TRANSPORT', 'tcp').lower()}",
)


class CaptureUnavailable(RuntimeError):
    """OpenCV tidak ada: mencoba ulang tidak akan membantu."""


def import_cv2():
    try:
        import cv2
    except ImportError:
        raise CaptureUnavailable(
            "OpenCV belum terpasang di server. Jalankan: pip install opencv-python-headless"
        ) from None
    return cv2


def open_capture(url, config):
    """Buka stream. Kembalikan cv2.VideoCapture (periksa .isOpened())."""
    cv2 = import_cv2()
    params = [
        cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, int(config.open_timeout_ms),
        cv2.CAP_PROP_READ_TIMEOUT_MSEC, int(config.read_timeout_ms),
    ]
    return cv2.VideoCapture(url, cv2.CAP_FFMPEG, params)
