"""Kalibrasi kamera: arah jalan, garis hitung, median, dan skala jarak.

Semua titik disimpan ternormalisasi (0..1 terhadap lebar/tinggi frame) sehingga
tidak bergantung resolusi stream.

* axis      : panah dari titik awal ke titik akhir = arah A (searah lalu lintas Arah A).
              Garis hitung tegak lurus panah, pada `line_pos` (0..1) sepanjang panah.
* median    : satu titik di pemisah jalur. Sisi tempat panah berada = jalur Arah A;
              sisi seberangnya = jalur Arah B. Dipakai untuk deteksi lawan arah.
* one_way   : jalan satu arah; kendaraan yang bergerak ke Arah B dianggap lawan arah.
* roi       : area deteksi (dua sudut persegi). Hanya bagian ini yang dikirim ke model, jadi
              kendaraan jauh tampil lebih besar dan CPU tidak membuang tenaga pada langit/bangunan.
* ref/ref_m : dua titik di jalan yang jarak aslinya diketahui (meter), untuk skala km/j.
"""
import math
from dataclasses import dataclass
from typing import Optional, Tuple

Point = Tuple[float, float]

DEFAULT_AXIS = ((0.1, 0.5), (0.9, 0.5))  # kiri -> kanan, sama dengan demo
MIN_AXIS_LEN = 0.1
MIN_REF_LEN = 0.03
MIN_ROI_SIDE = 0.15
REF_M_RANGE = (2.0, 500.0)


@dataclass(frozen=True)
class Calibration:
    axis: Tuple[Point, Point] = DEFAULT_AXIS
    line_pos: float = 0.5
    median: Optional[Point] = None
    one_way: bool = False
    ref: Optional[Tuple[Point, Point]] = None
    ref_m: Optional[float] = None
    roi: Optional[Tuple[Point, Point]] = None  # (kiri-atas, kanan-bawah), ternormalisasi
    configured: bool = False  # False = nilai bawaan, pengguna belum mengatur

    def to_dict(self):
        return {
            "axis": [list(p) for p in self.axis],
            "line_pos": self.line_pos,
            "median": list(self.median) if self.median else None,
            "one_way": self.one_way,
            "ref": [list(p) for p in self.ref] if self.ref else None,
            "ref_m": self.ref_m,
            "roi": [list(p) for p in self.roi] if self.roi else None,
        }


def _point(value, name, errors):
    try:
        x, y = float(value[0]), float(value[1])
    except (TypeError, ValueError, IndexError, KeyError):
        errors[name] = "Titik tidak valid."
        return None
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0) or not (math.isfinite(x) and math.isfinite(y)):
        errors[name] = "Titik berada di luar gambar."
        return None
    return (x, y)


def parse_calibration(data):
    """Validasi dict kalibrasi dari klien. Kembalikan (Calibration | None, errors)."""
    errors = {}
    if not isinstance(data, dict):
        return None, {"axis": "Data kalibrasi tidak valid."}

    axis = None
    raw_axis = data.get("axis")
    if isinstance(raw_axis, (list, tuple)) and len(raw_axis) == 2:
        p0, p1 = _point(raw_axis[0], "axis", errors), _point(raw_axis[1], "axis", errors)
        if p0 and p1:
            if math.dist(p0, p1) < MIN_AXIS_LEN:
                errors["axis"] = "Panah arah terlalu pendek. Tarik lebih panjang di sepanjang jalan."
            else:
                axis = (p0, p1)
    else:
        errors["axis"] = "Tandai arah A dengan dua titik."

    try:
        line_pos = float(data.get("line_pos", 0.5))
        if not 0.05 <= line_pos <= 0.95:
            raise ValueError
    except (TypeError, ValueError):
        line_pos = 0.5
        errors["line_pos"] = "Posisi garis hitung harus antara 5% dan 95%."

    median = None
    if data.get("median"):
        median = _point(data["median"], "median", errors)

    ref, ref_m = None, None
    if data.get("ref") or data.get("ref_m") not in (None, ""):
        raw_ref = data.get("ref")
        if isinstance(raw_ref, (list, tuple)) and len(raw_ref) == 2:
            r0, r1 = _point(raw_ref[0], "ref", errors), _point(raw_ref[1], "ref", errors)
            if r0 and r1 and math.dist(r0, r1) < MIN_REF_LEN:
                errors["ref"] = "Dua titik referensi terlalu dekat."
            elif r0 and r1:
                ref = (r0, r1)
        else:
            errors["ref"] = "Tandai dua titik referensi."
        try:
            ref_m = float(str(data.get("ref_m")).replace(",", "."))
            if not REF_M_RANGE[0] <= ref_m <= REF_M_RANGE[1]:
                raise ValueError
        except (TypeError, ValueError):
            errors["ref_m"] = f"Jarak asli {REF_M_RANGE[0]:.0f}–{REF_M_RANGE[1]:.0f} meter."

    roi = None
    raw_roi = data.get("roi")
    if raw_roi:
        if isinstance(raw_roi, (list, tuple)) and len(raw_roi) == 2:
            r0, r1 = _point(raw_roi[0], "roi", errors), _point(raw_roi[1], "roi", errors)
            if r0 and r1:
                left, right = sorted((r0[0], r1[0]))
                top, bottom = sorted((r0[1], r1[1]))
                if right - left < MIN_ROI_SIDE or bottom - top < MIN_ROI_SIDE:
                    errors["roi"] = "Area deteksi terlalu kecil. Tarik dari sudut ke sudut yang berlawanan."
                else:
                    roi = ((left, top), (right, bottom))
        else:
            errors["roi"] = "Tandai dua sudut area deteksi."

    if errors:
        return None, errors
    return (
        Calibration(
            axis=axis, line_pos=line_pos, median=median, one_way=bool(data.get("one_way")),
            ref=ref, ref_m=ref_m, roi=roi, configured=True,
        ),
        {},
    )


def from_stored(data):
    """Baca kalibrasi dari penyimpanan; nilai rusak/kosong jatuh ke bawaan."""
    if not data:
        return Calibration()
    cal, _ = parse_calibration(data)
    return cal or Calibration()


class RoadModel:
    """Geometri jalan dalam piksel untuk ukuran frame tertentu."""

    def __init__(self, cal: Calibration, width: int, height: int):
        self.width, self.height = width, height
        (x0, y0), (x1, y1) = cal.axis
        self.origin = (x0 * width, y0 * height)
        vx, vy = (x1 - x0) * width, (y1 - y0) * height
        self.length = math.hypot(vx, vy)
        self.ux, self.uy = vx / self.length, vy / self.length
        self.nx, self.ny = -self.uy, self.ux
        self.s0 = cal.line_pos * self.length
        self.one_way = cal.one_way
        self.configured = cal.configured

        self.median_t = None
        self.a_side = 1
        if cal.median:
            mx, my = cal.median[0] * width, cal.median[1] * height
            self.median_t = self.t(mx, my)
            mid = ((x0 + x1) / 2 * width, (y0 + y1) / 2 * height)
            self.a_side = 1 if self.t(*mid) >= self.median_t else -1

        self.mpp = None  # meter per piksel
        if cal.ref and cal.ref_m:
            (r0x, r0y), (r1x, r1y) = cal.ref
            px = math.hypot((r1x - r0x) * width, (r1y - r0y) * height)
            if px > 1:
                self.mpp = cal.ref_m / px

    @property
    def can_detect_wrong_way(self):
        return self.configured and (self.one_way or self.median_t is not None)

    def s(self, x, y):
        return (x - self.origin[0]) * self.ux + (y - self.origin[1]) * self.uy

    def t(self, x, y):
        return (x - self.origin[0]) * self.nx + (y - self.origin[1]) * self.ny

    def line_px(self):
        """Dua ujung garis hitung (piksel) untuk digambar; tegak lurus panah, panjang 60% tinggi/lebar."""
        cx = self.origin[0] + self.ux * self.s0
        cy = self.origin[1] + self.uy * self.s0
        half = 0.3 * max(self.width, self.height)
        return (cx - self.nx * half, cy - self.ny * half), (cx + self.nx * half, cy + self.ny * half)
