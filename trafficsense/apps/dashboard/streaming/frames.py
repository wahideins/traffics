"""Encode frame ke JPEG dan gambar placeholder status."""
from functools import lru_cache

from .capture import import_cv2


def encode_jpeg(frame, quality=80, max_width=1280):
    """Frame BGR (numpy) -> bytes JPEG, diperkecil bila lebih lebar dari max_width."""
    cv2 = import_cv2()
    height, width = frame.shape[:2]
    if max_width and width > max_width:
        new_height = max(1, int(height * max_width / width))
        frame = cv2.resize(frame, (max_width, new_height), interpolation=cv2.INTER_AREA)
    ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    if not ok:
        raise RuntimeError("Gagal menyandikan frame ke JPEG")
    return buffer.tobytes()


@lru_cache(maxsize=16)
def placeholder_jpeg(text, width=640, height=360):
    """Gambar gelap berisi teks (ASCII saja, font bawaan OpenCV tidak mendukung aksen)."""
    import numpy as np

    cv2 = import_cv2()
    image = np.full((height, width, 3), (38, 20, 10), dtype=np.uint8)  # biru gelap (BGR)
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale, thickness = 0.7, 2
    (text_w, text_h), _ = cv2.getTextSize(text, font, scale, thickness)
    origin = (max(8, (width - text_w) // 2), (height + text_h) // 2)
    cv2.putText(image, text, origin, font, scale, (255, 219, 201), thickness, cv2.LINE_AA)
    ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        raise RuntimeError("Gagal membuat placeholder")
    return buffer.tobytes()
