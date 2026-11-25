"""Tipe data deteksi."""
from dataclasses import dataclass, field
from typing import Deque, Optional, Tuple
from collections import deque


@dataclass(frozen=True)
class Detection:
    box: Tuple[float, float, float, float]  # x1, y1, x2, y2 (piksel frame)
    score: float
    cls: str  # kunci kelas dashboard: motor | mobil | bus | truk


@dataclass
class Track:
    id: int
    cls: str
    box: Tuple[float, float, float, float]
    t: float  # waktu pembaruan terakhir
    hits: int = 1
    missed: int = 0
    # (waktu, x, y) titik tapak = tengah-bawah kotak; dipakai untuk posisi dan kecepatan.
    points: Deque = field(default_factory=lambda: deque(maxlen=40))
    votes: dict = field(default_factory=dict)
    counted: bool = False
    wrong_flagged: bool = False
    speed_kmh: Optional[float] = None
    s_prev: Optional[float] = None
    direction: Optional[str] = None  # a | b | None (arah gerak terkini)

    @property
    def ground(self):
        x1, _, x2, y2 = self.box
        return ((x1 + x2) / 2.0, y2)

    @property
    def area(self):
        x1, y1, x2, y2 = self.box
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)
