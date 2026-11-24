"""Data grafik berseri: kepadatan (kongesti) dan volume kendaraan per interval."""
import math

from .constants import TIME_RANGES
from .formatting import css_number, format_int
from .metrics import clamp, density_level, pseudo_random


def build_series(camera, camera_index, range_key, live):
    """Kembalikan (congestion, volume) untuk rentang waktu terpilih.

    Bar terakhir selalu memakai nilai langsung; sisanya deterministik per
    kamera dan rentang, sehingga grafik tidak melompat saat dimuat ulang.
    """
    cfg = TIME_RANGES[range_key]
    points, step, seed = cfg["points"], cfg["step"], cfg["seed"]
    amplitude = 26 if range_key == "24h" else 15

    densities = []
    volumes = []
    for i in range(points):
        is_last = i == points - 1

        density = (
            camera.base_density
            + amplitude * math.sin(i * 0.55 + camera_index * 1.7)
            + (pseudo_random(i * 7 + camera_index * 13 + seed * 101) - 0.5) * 10
        )
        if is_last:
            density = live.density
        densities.append(clamp(density, 4, 98))

        factor = 0.65 + 0.7 * pseudo_random(i * 5 + camera_index * 17 + seed * 53)
        if range_key == "24h":
            factor = (
                0.35
                + 0.9 * math.exp(-((i - 8) ** 2) / 10)
                + 0.7 * math.exp(-((i - 17) ** 2) / 8)
                + 0.2 * pseudo_random(i + camera_index)
            )
        volume = camera.base_flow * step * factor
        if is_last:
            volume = live.flow * step
        volumes.append(volume)

    congestion = {
        "bars": [
            {
                "h": css_number(d),
                "level": density_level(d),
                "title": f"Kepadatan {round(d)}%",
            }
            for d in densities
        ],
        "peak": round(max(densities)),
        "share": round(sum(1 for d in densities if d >= 50) / len(densities) * 100),
    }

    max_volume = max(volumes)
    unit = 100 if max_volume > 500 else 10
    y_max = math.ceil(max_volume / unit) * unit

    bars = []
    for i, volume in enumerate(volumes):
        motor = 0.5 + (pseudo_random(i * 3 + 1) - 0.5) * 0.12
        mobil = 0.35 + (pseudo_random(i * 3 + 2) - 0.5) * 0.10
        bus = 0.03 + pseudo_random(i * 3 + 3) * 0.02
        truk = 1 - motor - mobil - bus
        bars.append(
            {
                "h": css_number(volume / y_max * 100),
                "title": f"{format_int(volume)} kendaraan",
                # Urutan dari dasar bar ke atas.
                "segments": [
                    {"key": "motor", "pct": css_number(motor * 100)},
                    {"key": "mobil", "pct": css_number(mobil * 100)},
                    {"key": "bus", "pct": css_number(bus * 100)},
                    {"key": "truk", "pct": css_number(truk * 100)},
                ],
            }
        )

    volume_data = {
        "bars": bars,
        "y_max": format_int(y_max),
        "y_mid": format_int(y_max / 2),
    }
    return congestion, volume_data
