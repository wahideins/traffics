"""Mengubah snapshot penganalisis (angka mentah) menjadi data siap tampil di template.

Bentuk keluaran sama dengan analitik simulasi (context._simulated_analytics) supaya
template tidak perlu tahu sumber datanya. Tanpa Django; mudah diuji.
"""
from datetime import datetime

from .constants import (
    DENSITY_MACET,
    DENSITY_PADAT,
    EVENT_TYPES,
    FLOW_LEVELS,
    SEVERITY_LABELS,
    SPEED_BINS,
    TIME_RANGES,
    VEHICLE_CLASSES,
)
from .formatting import css_number, format_decimal, format_int
from .metrics import clamp, density_level

NO_DATA = "—"
WAITING_SPEED = "Perlu kalibrasi skala (jarak referensi)"


def _fmt_time(epoch):
    return datetime.fromtimestamp(epoch).strftime("%H:%M:%S")


def build_counts(snapshot):
    rows, sum_a, sum_b = [], 0, 0
    for vc in VEHICLE_CLASSES:
        a, b = snapshot["counts"]["a"][vc["key"]], snapshot["counts"]["b"][vc["key"]]
        sum_a, sum_b = sum_a + a, sum_b + b
        rows.append({"key": vc["key"], "name": vc["name"], "a": a, "b": b, "total": a + b})
    total = sum_a + sum_b
    return {
        "rows": [
            {
                "key": r["key"], "name": r["name"], "a": format_int(r["a"]), "b": format_int(r["b"]),
                "total": format_int(r["total"]), "pct": round(r["total"] / total * 100) if total else 0,
            }
            for r in rows
        ],
        "sum_a": format_int(sum_a),
        "sum_b": format_int(sum_b),
        "sum_all": format_int(total),
        "total_raw": total,
    }


def build_speed(snapshot):
    spd = snapshot["speed"]
    ready = snapshot["speed_ready"]
    limit = snapshot["speed_limit"]
    max_count = max(spd["bins"]) or 1
    bins = [
        {
            "label": label,
            "count": format_int(count),
            "h": css_number(count / max_count * 86),
            "over": lower >= limit,
        }
        for (label, lower), count in zip(SPEED_BINS, spd["bins"])
    ]
    n = spd["n"]
    pct = spd["speeding"] / n * 100 if n else 0.0
    return {
        "bins": bins,
        "avg": round(spd["avg"]) if spd["avg"] is not None else NO_DATA,
        "max": round(spd["max"]) if spd["max"] is not None else NO_DATA,
        "limit": limit,
        "speeding": format_int(spd["speeding"]) if ready else NO_DATA,
        "speeding_pct": format_decimal(pct) if ready and n else (NO_DATA if not ready else "0,0"),
    }


def build_events(snapshot, event_type):
    return [
        {
            "time": _fmt_time(e["t"]),
            "type": e["type"],
            "type_label": EVENT_TYPES[e["type"]],
            "detail": e["detail"],
            "lane": e["lane"],
            "severity": e["severity"],
            "severity_label": SEVERITY_LABELS[e["severity"]],
        }
        for e in snapshot["events"]
        if event_type == "all" or e["type"] == event_type
    ]


def build_wrong_way(snapshot):
    wrong = [e for e in snapshot["events"] if e["type"] == "wrong"]
    last = wrong[0] if wrong else None
    if not snapshot["can_wrong_way"]:
        return {
            "count": NO_DATA, "has": False, "last_time": "Belum aktif",
            "last_detail": "Atur median atau tandai jalan satu arah di Kalibrasi untuk mengaktifkan.",
        }
    return {
        "count": snapshot["wrong_today"],
        "has": snapshot["wrong_today"] > 0,
        "last_time": f"{_fmt_time(last['t'])} WIB" if last else "Belum ada kejadian",
        "last_detail": f"{last['detail']} · {last['lane']}" if last else "Tidak ada kendaraan melawan arah pada kamera ini.",
    }


def build_directions(snapshot):
    entries = []
    for key, label in (("a", f"Arah A · {snapshot['dir_a']}"), ("b", f"Arah B · {snapshot['dir_b']}")):
        d = snapshot["directions"][key]
        entries.append({
            "label": label,
            "speed": round(d["speed"]) if d["speed"] is not None else NO_DATA,
            "density": round(d["density"]),
            "level": d["level"],
            "speed_raw": d["speed"],
        })
    a, b = entries
    if a["speed_raw"] is not None and b["speed_raw"] is not None:
        slower, faster = sorted(entries, key=lambda e: e["speed_raw"])
        if slower["level"] != faster["level"]:
            insight = f"{slower['label']} lebih tersendat dibanding {faster['label']} ({slower['speed']} km/j dibanding {faster['speed']} km/j)."
        else:
            insight = f"Kedua arah berada pada kondisi yang sama. Selisih kecepatan {abs(slower['speed'] - faster['speed'])} km/j."
    else:
        denser = max(entries, key=lambda e: e["density"])
        insight = (
            f"{denser['label']} lebih padat ({denser['density']}%)."
            if abs(a["density"] - b["density"]) >= 10
            else "Kepadatan kedua arah relatif seimbang."
        )
    return entries, insight


def build_series(series, range_key):
    """Grafik volume (bertumpuk per kelas) dan kepadatan dari `analyzer.series`."""
    cfg = TIME_RANGES[range_key]
    totals = [p["total"] for p in series]
    max_volume = max(totals) if totals and max(totals) > 0 else 0
    unit = 100 if max_volume > 500 else 10 if max_volume > 50 else 5
    y_max = max(unit, -(-max_volume // unit) * unit)

    bars = []
    for point in series:
        total = point["total"]
        segments = [
            {"key": vc["key"], "pct": css_number(point["classes"].get(vc["key"], 0) / total * 100 if total else 25.0)}
            for vc in VEHICLE_CLASSES
        ]
        bars.append({"h": css_number(total / y_max * 100), "title": f"{format_int(total)} kendaraan", "segments": segments})

    densities = [p["density"] for p in series if p["density"] is not None]
    congestion_bars = [
        {
            "h": css_number(clamp(p["density"], 0, 100) if p["density"] is not None else 0.0),
            "level": density_level(p["density"] or 0),
            "title": f"Kepadatan {round(p['density'])}%" if p["density"] is not None else "Tidak ada data",
        }
        for p in series
    ]
    return (
        {"bars": congestion_bars,
         "peak": round(max(densities)) if densities else NO_DATA,
         "share": round(sum(1 for d in densities if d >= DENSITY_PADAT) / len(densities) * 100) if densities else NO_DATA},
        {"bars": bars, "y_max": format_int(y_max), "y_mid": format_int(y_max / 2)},
    )


def build_live_analytics(camera, snapshot, series, range_key, event_type):
    level_key = snapshot["level"]
    level = FLOW_LEVELS[level_key]
    avg = snapshot["avg_speed"]
    speed_ready = snapshot["speed_ready"]
    counts = build_counts(snapshot)
    speed = build_speed(snapshot)
    directions, insight = build_directions(snapshot)
    congestion, volume = build_series(series, range_key)
    wrong = build_wrong_way(snapshot)
    density = snapshot["density"]
    recent_wrong = next((e for e in snapshot["events"] if e["type"] == "wrong"), None)

    desc = level["desc"]
    if not speed_ready:
        desc = "Status dari kepadatan saja. Kalibrasi skala diperlukan agar kecepatan ikut dihitung."

    return {
        "flow": {
            "key": level_key,
            "label": level["label"],
            "los": level["los"],
            "desc": desc,
            "marker": css_number(clamp(density, 2, 98)),
            "speed": round(avg) if avg is not None else NO_DATA,
            "density": round(density),
            "rate": snapshot["flow"],
            "travel": format_decimal(60 / avg) if avg and avg >= 3 else NO_DATA,
        },
        "directions": directions,
        "insight": insight,
        "kpi": {
            "total": counts["sum_all"],
            "flow": snapshot["flow"],
            "flow_note": "Dihitung dari 60 detik terakhir",
            "avg": round(avg) if avg is not None else NO_DATA,
            "avg_note": f"Batas kecepatan {snapshot['speed_limit']} km/j" if speed_ready else WAITING_SPEED,
            "speeding": speed["speeding"],
            "speeding_note": f"{speed['speeding_pct']}% dari kendaraan terukur" if speed_ready else WAITING_SPEED,
            "limit": snapshot["speed_limit"],
            "speeding_pct": speed["speeding_pct"],
            "wrong": wrong["count"],
            "wrong_tone": "danger" if snapshot["can_wrong_way"] and snapshot["wrong_today"] > 0 else "",
        },
        "counts": counts,
        "speed": speed,
        "volume": volume,
        "congestion": congestion,
        "wrong_way": wrong,
        "events": build_events(snapshot, event_type),
        "vehicles": [],
        "hud": {"a": counts["sum_a"], "b": counts["sum_b"]},
        "alert": f"Lawan arah terdeteksi · {recent_wrong['lane']}" if snapshot["wrong_active"] and recent_wrong else "",
    }
