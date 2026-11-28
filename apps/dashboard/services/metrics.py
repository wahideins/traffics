"""Metrik langsung: arus, hitungan kendaraan, kecepatan, kondisi per arah."""
import math
from dataclasses import dataclass

from .constants import (
    DENSITY_MACET,
    DENSITY_PADAT,
    SPEED_BINS,
    VEHICLE_CLASSES,
)
from .formatting import css_number, format_decimal, format_int


def clamp(value, low, high):
    return max(low, min(high, value))


def pseudo_random(seed) -> float:
    """Angka acak deterministik 0..1 (hasil sama untuk seed sama)."""
    x = math.sin(seed * 127.1 + 311.7) * 43758.5453
    return x - math.floor(x)


@dataclass(frozen=True)
class LiveMetrics:
    avg_speed: float
    density: float
    flow: int  # kendaraan per menit
    level: str  # lancar | padat | macet


def classify_flow(speed, density, limit) -> str:
    """Estimasi status arus dari rasio kecepatan terhadap batas dan kepadatan."""
    ratio = speed / limit
    if ratio >= 0.65 and density < DENSITY_PADAT:
        return "lancar"
    if ratio >= 0.35 and density < DENSITY_MACET:
        return "padat"
    return "macet"


def classify_traffic(speed, density, limit, jam_ratio):
    """Status arus untuk kamera nyata. Gerak kendaraan yang menentukan; kepadatan
    saja (jalan ramai tapi lancar) tidak pernah cukup untuk Macet.

    speed: km/j rata-rata atau None (belum dikalibrasi); jam_ratio: porsi kendaraan
    yang nyaris diam (0..1) atau None bila belum cukup data.
    """
    if speed is not None:
        ratio = speed / limit if limit else 1.0
        if ratio >= 0.55:
            return "lancar"
        if ratio >= 0.25:
            return "padat"
        stuck = jam_ratio is not None and jam_ratio >= 0.5
        return "macet" if (density >= 25 or stuck) else "padat"
    if jam_ratio is None:
        return "padat" if density >= DENSITY_MACET else "lancar"
    if jam_ratio >= 0.6 and density >= 25:
        return "macet"
    if jam_ratio >= 0.3 or density >= DENSITY_MACET:
        return "padat"
    return "lancar"


def density_level(density) -> str:
    if density < DENSITY_PADAT:
        return "lancar"
    if density < DENSITY_MACET:
        return "padat"
    return "macet"


def live_metrics(camera, tick) -> LiveMetrics:
    avg_speed = camera.base_speed + math.sin(tick * 0.7) * 2.2
    density = clamp(camera.base_density + math.cos(tick * 0.5) * 3, 0, 100)
    flow = camera.base_flow + round(math.sin(tick * 0.4) * 4)
    level = classify_flow(avg_speed, density, camera.speed_limit)
    return LiveMetrics(avg_speed, density, flow, level)


def vehicle_counts(camera, minutes_today) -> dict:
    """Jumlah kendaraan sejak 00:00, per kelas dan arah (tumbuh sesuai jam)."""
    base_total = sum(camera.base_counts_a) + sum(camera.base_counts_b)
    rows = []
    sum_a = sum_b = 0
    for index, vc in enumerate(VEHICLE_CLASSES):
        a = int(minutes_today * camera.base_flow * camera.base_counts_a[index] / base_total)
        b = int(minutes_today * camera.base_flow * camera.base_counts_b[index] / base_total)
        sum_a += a
        sum_b += b
        rows.append({"key": vc["key"], "name": vc["name"], "a": a, "b": b, "total": a + b})

    total = sum_a + sum_b
    formatted = [
        {
            "key": row["key"],
            "name": row["name"],
            "a": format_int(row["a"]),
            "b": format_int(row["b"]),
            "total": format_int(row["total"]),
            "pct": round(row["total"] / total * 100) if total else 0,
        }
        for row in rows
    ]
    return {
        "rows": formatted,
        "sum_a": format_int(sum_a),
        "sum_b": format_int(sum_b),
        "sum_all": format_int(total),
        "total_raw": total,
    }


def speed_analysis(camera, live, total) -> dict:
    """Distribusi kecepatan (aproksimasi normal) dan jumlah yang melebihi batas."""
    mu, sd = live.avg_speed, camera.speed_sd

    def cdf(x):
        return 0.5 * (1 + math.erf((x - mu) / (sd * math.sqrt(2))))

    lowers = [lower for _, lower in SPEED_BINS]
    uppers = lowers[1:] + [None]
    probs = []
    for lower, upper in zip(lowers, uppers):
        low_p = 0.0 if lower == 0 else cdf(lower)
        high_p = 1.0 if upper is None else cdf(upper)
        probs.append(high_p - low_p)

    counts = [round(total * p) for p in probs]
    max_count = max(counts) or 1
    over_flags = [lower >= camera.speed_limit for lower in lowers]

    bins = [
        {
            "label": label,
            "count": format_int(count),
            "h": css_number(count / max_count * 86),
            "over": over,
        }
        for (label, _), count, over in zip(SPEED_BINS, counts, over_flags)
    ]

    p_over = sum(p for p, over in zip(probs, over_flags) if over)
    return {
        "bins": bins,
        "avg": round(live.avg_speed),
        "max": camera.max_speed,
        "limit": camera.speed_limit,
        "speeding": format_int(total * p_over),
        "speeding_pct": format_decimal(p_over * 100),
    }


def direction_status(camera, live):
    """Kondisi tiap arah dan satu kalimat ringkasan perbandingan."""
    entries = []
    for label, offset in (
        (f"Arah A · {camera.dir_a}", camera.offset_a),
        (f"Arah B · {camera.dir_b}", camera.offset_b),
    ):
        speed = live.avg_speed + offset
        density = clamp(live.density - offset * 0.8, 0, 100)
        level = classify_flow(speed, density, camera.speed_limit)
        entries.append(
            {
                "label": label,
                "speed_raw": speed,
                "speed": round(speed),
                "density": round(density),
                "level": level,
            }
        )

    slower, faster = sorted(entries, key=lambda e: e["speed_raw"])
    if slower["level"] != faster["level"]:
        insight = (
            f"{slower['label']} lebih tersendat dibanding {faster['label']} "
            f"({slower['speed']} km/j dibanding {faster['speed']} km/j)."
        )
    else:
        insight = (
            f"Kedua arah berada pada kondisi yang sama. Selisih kecepatan "
            f"{abs(slower['speed'] - faster['speed'])} km/j, paling lambat di {slower['label']}."
        )
    return entries, insight
