"""Penganalisis lalu lintas: dari deteksi per frame menjadi hitungan, kecepatan, lawan arah, kepadatan, dan kejadian.

Tidak bergantung Django maupun OpenCV (mudah diuji dengan deteksi skrip).
Seluruh metode publik aman dipanggil dari thread berbeda.
"""
import math
import threading
import time
from collections import deque
from datetime import datetime

from ..services.constants import DENSITY_MACET, DENSITY_PADAT, SPEED_BINS, VEHICLE_CLASSES
from ..services.metrics import classify_flow, density_level
from .calibration import Calibration, RoadModel
from .tracker import Tracker

CLASS_KEYS = tuple(vc["key"] for vc in VEHICLE_CLASSES)
CLASS_NAMES = {vc["key"]: vc["name"] for vc in VEHICLE_CLASSES}

# Luas kendaraan sebagai persentase luas frame yang dianggap "penuh" (antre rapat).
FULL_OCCUPANCY = 0.30
SPEED_WINDOW = 1.5  # detik jendela untuk menghitung kecepatan
MAX_PLAUSIBLE_KMH = 250.0
CONGESTION_HOLD = 20.0  # detik berstatus macet sebelum dicatat sebagai kejadian
WRONG_WAY_ACTIVE = 8.0  # detik peringatan lawan arah tampil di HUD
BUCKET_KEEP_SECONDS = 25 * 3600
MAX_EVENTS = 200
STATE_VERSION = 1


def _empty_counts():
    return {"a": {k: 0 for k in CLASS_KEYS}, "b": {k: 0 for k in CLASS_KEYS}}


class TrafficAnalyzer:
    def __init__(self, *, speed_limit, calibration=None, dir_a="Arah A", dir_b="Arah B",
                 track_max_age=1.5, track_min_hits=3, full_occupancy=FULL_OCCUPANCY, clock=time.time):
        self.speed_limit = speed_limit
        self.calibration = calibration or Calibration()
        self.dir_a, self.dir_b = dir_a, dir_b
        self._clock = clock
        self._full = full_occupancy
        self._lock = threading.RLock()
        self._tracker = Tracker(max_age=track_max_age, min_hits=track_min_hits)

        self._frame_size = None
        self._frames = 0
        self._density = 0.0
        self._dir_density = {"a": 0.0, "b": 0.0}
        self._avg_live_speed = None
        self._overlay = []

        self._date = self._today(clock())
        self._counts = _empty_counts()
        self._hist = [0] * len(SPEED_BINS)
        self._speed_sum = 0.0
        self._speed_n = 0
        self._speed_max = 0.0
        self._speeding = 0
        self._wrong_today = 0
        self._last_wrong_t = None
        self._events = deque(maxlen=MAX_EVENTS)
        self._buckets = {}  # menit -> {"c": {kelas: n}, "d": [jumlah, n]}
        self._crossings = deque()  # (t, arah, kecepatan|None)
        self._macet_since = None
        self._ok_since = None
        self._macet_logged = False

    # --- masukan ---------------------------------------------------------
    def set_calibration(self, calibration, *, dir_a=None, dir_b=None, speed_limit=None):
        with self._lock:
            self.calibration = calibration
            if dir_a:
                self.dir_a = dir_a
            if dir_b:
                self.dir_b = dir_b
            if speed_limit:
                self.speed_limit = speed_limit

    def process(self, detections, frame_size, t=None, area=None):
        """Proses deteksi satu frame. `frame_size`: (lebar, tinggi). Kembalikan track terkonfirmasi."""
        with self._lock:
            t = self._clock() if t is None else t
            self._roll_day(t)
            width, height = frame_size
            self._frame_size = frame_size
            road = RoadModel(self.calibration, width, height)

            tracks = self._tracker.update(detections, t)
            frame_area = float(area) if area else float(width * height)  # luas area deteksi bila ada

            for tr in tracks:
                gx, gy = tr.ground
                s = road.s(gx, gy)
                tr.speed_kmh = self._speed_of(tr, road, t)
                tr.direction = self._direction_of(tr, road)
                if tr.s_prev is not None:
                    self._check_crossing(tr, tr.s_prev, s, road, t)
                self._check_wrong_way(tr, road, t)
                tr.s_prev = s

            self._update_density(tracks, frame_area, t)
            self._update_live_speed(tracks, t)
            self._check_congestion(t, road)
            self._overlay = [
                {
                    "id": tr.id, "cls": tr.cls, "box": tr.box, "speed": tr.speed_kmh,
                    "wrong": tr.wrong_flagged,
                    "speeding": tr.speed_kmh is not None and tr.speed_kmh > self.speed_limit,
                }
                for tr in tracks
            ]
            self._frames += 1
            return tracks

    # --- keluaran --------------------------------------------------------
    def overlay(self):
        """(daftar kotak untuk digambar, garis hitung dalam piksel, ukuran frame)."""
        with self._lock:
            if self._frame_size is None:
                return [], None, None
            road = RoadModel(self.calibration, *self._frame_size)
            return list(self._overlay), road.line_px(), self._frame_size

    def snapshot(self, t=None):
        with self._lock:
            t = self._clock() if t is None else t
            self._roll_day(t)
            road = self._road()
            self._prune_crossings(t)

            flow = len(self._crossings)
            speed_ready = road is not None and road.mpp is not None
            avg = self._avg_live_speed if speed_ready else None
            if avg is not None:
                level = classify_flow(avg, self._density, self.speed_limit)
            else:
                level = density_level(self._density)

            directions = {}
            for key in ("a", "b"):
                samples = [sp for (ts, d, sp) in self._crossings if d == key and sp is not None]
                speed = sum(samples) / len(samples) if samples else None
                dens = self._dir_density[key]
                directions[key] = {
                    "speed": speed,
                    "density": dens,
                    "level": classify_flow(speed, dens, self.speed_limit) if speed is not None else density_level(dens),
                }

            hist_total = sum(self._hist)
            return {
                "ready": self._frames > 0,
                "frames": self._frames,
                "configured": self.calibration.configured,
                "speed_ready": speed_ready,
                "can_wrong_way": bool(road and road.can_detect_wrong_way),
                "density": self._density,
                "level": level,
                "avg_speed": avg,
                "flow": flow,
                "counts": {d: dict(c) for d, c in self._counts.items()},
                "directions": directions,
                "speed": {
                    "bins": list(self._hist),
                    "n": hist_total,
                    "avg": self._speed_sum / self._speed_n if self._speed_n else None,
                    "max": self._speed_max if self._speed_n else None,
                    "speeding": self._speeding,
                },
                "wrong_today": self._wrong_today,
                "wrong_active": self._last_wrong_t is not None and t - self._last_wrong_t <= WRONG_WAY_ACTIVE,
                "events": [dict(e) for e in reversed(self._events)],  # terbaru dulu
                "dir_a": self.dir_a,
                "dir_b": self.dir_b,
                "speed_limit": self.speed_limit,
            }

    def series(self, points, step_minutes, t=None):
        """Data grafik: `points` interval berukuran `step_minutes`, berakhir sekarang (terlama dulu).

        Tiap elemen: {"classes": {kelas: n}, "total": n, "density": rata-rata|None}.
        """
        with self._lock:
            t = self._clock() if t is None else t
            now_minute = int(t // 60)
            result = []
            for i in range(points):
                end = now_minute - (points - 1 - i) * step_minutes
                start = end - step_minutes + 1
                classes = {k: 0 for k in CLASS_KEYS}
                d_sum, d_n = 0.0, 0
                for minute in range(start, end + 1):
                    bucket = self._buckets.get(minute)
                    if not bucket:
                        continue
                    for k, n in bucket["c"].items():
                        classes[k] = classes.get(k, 0) + n
                    d_sum += bucket["d"][0]
                    d_n += bucket["d"][1]
                result.append(
                    {"classes": classes, "total": sum(classes.values()), "density": d_sum / d_n if d_n else None}
                )
            return result

    def reset(self):
        """Hapus hitungan, grafik, dan kejadian (pelacak dibiarkan agar kendaraan di layar tetap terlacak)."""
        with self._lock:
            self._counts = _empty_counts()
            self._hist = [0] * len(SPEED_BINS)
            self._speed_sum, self._speed_n, self._speed_max = 0.0, 0, 0.0
            self._speeding = 0
            self._wrong_today = 0
            self._events.clear()
            self._buckets.clear()
            self._crossings.clear()
            self._macet_since = self._ok_since = None
            self._macet_logged = False

    # --- penyimpanan keadaan --------------------------------------------
    def export_state(self):
        with self._lock:
            return {
                "version": STATE_VERSION,
                "date": self._date,
                "counts": self._counts,
                "hist": self._hist,
                "speed_sum": self._speed_sum,
                "speed_n": self._speed_n,
                "speed_max": self._speed_max,
                "speeding": self._speeding,
                "wrong_today": self._wrong_today,
                "events": list(self._events),
                "buckets": {str(m): b for m, b in self._buckets.items()},
            }

    def load_state(self, state, t=None):
        """Pulihkan keadaan. Hitungan harian hanya dipulihkan bila tanggalnya hari ini."""
        try:
            if state.get("version") != STATE_VERSION:
                return False
            with self._lock:
                t = self._clock() if t is None else t
                cutoff = int((t - BUCKET_KEEP_SECONDS) // 60)
                self._buckets = {
                    int(m): {"c": dict(b["c"]), "d": list(b["d"])}
                    for m, b in state.get("buckets", {}).items()
                    if int(m) >= cutoff
                }
                if state["date"] == self._today(t):
                    self._date = state["date"]
                    self._counts = {d: {k: int(state["counts"][d].get(k, 0)) for k in CLASS_KEYS} for d in ("a", "b")}
                    hist = list(state["hist"])
                    self._hist = (hist + [0] * len(SPEED_BINS))[: len(SPEED_BINS)]
                    self._speed_sum = float(state["speed_sum"])
                    self._speed_n = int(state["speed_n"])
                    self._speed_max = float(state["speed_max"])
                    self._speeding = int(state["speeding"])
                    self._wrong_today = int(state["wrong_today"])
                self._events = deque((dict(e) for e in state.get("events", [])), maxlen=MAX_EVENTS)
            return True
        except (KeyError, TypeError, ValueError, AttributeError):
            return False

    # --- internal --------------------------------------------------------
    @staticmethod
    def _today(t):
        return datetime.fromtimestamp(t).strftime("%Y-%m-%d")

    def _road(self):
        return RoadModel(self.calibration, *self._frame_size) if self._frame_size else None

    def _roll_day(self, t):
        today = self._today(t)
        if today != self._date:
            self._date = today
            self._counts = _empty_counts()
            self._hist = [0] * len(SPEED_BINS)
            self._speed_sum, self._speed_n, self._speed_max = 0.0, 0, 0.0
            self._speeding = 0
            self._wrong_today = 0

    def _bucket(self, t):
        minute = int(t // 60)
        bucket = self._buckets.get(minute)
        if bucket is None:
            bucket = self._buckets[minute] = {"c": {}, "d": [0.0, 0]}
            cutoff = int((t - BUCKET_KEEP_SECONDS) // 60)
            for old in [m for m in self._buckets if m < cutoff]:
                del self._buckets[old]
        return bucket

    def _prune_crossings(self, t):
        while self._crossings and t - self._crossings[0][0] > 60:
            self._crossings.popleft()

    def _speed_of(self, tr, road, t):
        if road.mpp is None:
            return None
        pts = [p for p in tr.points if t - p[0] <= SPEED_WINDOW]
        if len(pts) < 3 or pts[-1][0] - pts[0][0] < 0.6:
            return tr.speed_kmh
        dist = math.hypot(pts[-1][1] - pts[0][1], pts[-1][2] - pts[0][2])
        if dist < 3.0:  # getar kotak, bukan gerak
            dist = 0.0
        value = dist * road.mpp / (pts[-1][0] - pts[0][0]) * 3.6
        if value > MAX_PLAUSIBLE_KMH:
            return tr.speed_kmh
        return value if tr.speed_kmh is None else 0.6 * tr.speed_kmh + 0.4 * value

    @staticmethod
    def _direction_of(tr, road):
        if len(tr.points) < 4:
            return None
        (_, x0, y0), (_, x1, y1) = tr.points[0], tr.points[-1]
        ds = (x1 - x0) * road.ux + (y1 - y0) * road.uy
        if abs(ds) < max(8.0, 0.02 * road.length):
            return None
        return "a" if ds > 0 else "b"

    def _check_crossing(self, tr, s_prev, s, road, t):
        if tr.counted:
            return
        if s_prev < road.s0 <= s:
            direction = "a"
        elif s_prev > road.s0 >= s:
            direction = "b"
        else:
            return
        tr.counted = True
        cls = tr.cls
        self._counts[direction][cls] += 1
        bucket = self._bucket(t)
        bucket["c"][cls] = bucket["c"].get(cls, 0) + 1
        speed = tr.speed_kmh
        self._crossings.append((t, direction, speed))

        if speed is not None:
            self._speed_n += 1
            self._speed_sum += speed
            self._speed_max = max(self._speed_max, speed)
            idx = 0
            for i, (_, lower) in enumerate(SPEED_BINS):
                if speed >= lower:
                    idx = i
            self._hist[idx] += 1
            if speed > self.speed_limit:
                self._speeding += 1
                over = speed - self.speed_limit
                self._add_event(
                    t, "speed",
                    f"{CLASS_NAMES[cls]} {round(speed)} km/j (batas {self.speed_limit})",
                    self._lane(direction),
                    "high" if over >= 20 else "mid" if over >= 10 else "low",
                )

    def _check_wrong_way(self, tr, road, t):
        if tr.wrong_flagged or not road.can_detect_wrong_way or len(tr.points) < 6:
            return
        pts = list(tr.points)
        x0, y0 = pts[0][1], pts[0][2]
        x1, y1 = pts[-1][1], pts[-1][2]
        ds = (x1 - x0) * road.ux + (y1 - y0) * road.uy
        path = sum(math.hypot(b[1] - a[1], b[2] - a[2]) for a, b in zip(pts, pts[1:]))
        if abs(ds) < max(30.0, 0.08 * road.length) or abs(ds) < 0.7 * path:
            return  # belum cukup jauh atau geraknya zig-zag (kemungkinan salah lacak)

        moving = 1 if ds > 0 else -1
        if road.one_way or road.median_t is None:
            expected = 1
        else:
            mean_t = sum(road.t(p[1], p[2]) for p in pts) / len(pts)
            side = 1 if mean_t >= road.median_t else -1
            if abs(mean_t - road.median_t) < 4.0:
                return  # di atas median: sisi tak jelas
            expected = 1 if side == road.a_side else -1
        if moving != expected:
            tr.wrong_flagged = True
            self._wrong_today += 1
            self._last_wrong_t = t
            lane = self._lane("a" if expected == 1 else "b")
            self._add_event(t, "wrong", f"{CLASS_NAMES[tr.cls]} melawan arah", lane, "high")

    def _update_density(self, tracks, frame_area, t):
        total = sum(tr.area for tr in tracks)
        raw = min(100.0, total / (frame_area * self._full) * 100.0)
        self._density = raw if self._frames == 0 else 0.7 * self._density + 0.3 * raw
        for key in ("a", "b"):
            area = sum(tr.area for tr in tracks if getattr(tr, "direction", None) == key)
            raw_dir = min(100.0, area / (frame_area * self._full / 2) * 100.0)
            self._dir_density[key] = 0.7 * self._dir_density[key] + 0.3 * raw_dir
        bucket = self._bucket(t)
        bucket["d"][0] += self._density
        bucket["d"][1] += 1

    def _update_live_speed(self, tracks, t):
        speeds = [tr.speed_kmh for tr in tracks if tr.speed_kmh is not None]
        if len(speeds) >= 2:
            self._avg_live_speed = sum(speeds) / len(speeds)
            return
        recent = [sp for (ts, _, sp) in self._crossings if sp is not None and t - ts <= 120]
        self._avg_live_speed = sum(recent) / len(recent) if len(recent) >= 3 else (speeds[0] if speeds else None)

    def _check_congestion(self, t, road):
        macet = self._density >= DENSITY_MACET or (
            self._avg_live_speed is not None and road.mpp is not None
            and classify_flow(self._avg_live_speed, self._density, self.speed_limit) == "macet"
            and self._density >= DENSITY_PADAT
        )
        if macet:
            self._ok_since = None
            if self._macet_since is None:
                self._macet_since = t
            if not self._macet_logged and t - self._macet_since >= CONGESTION_HOLD:
                self._macet_logged = True
                self._add_event(t, "cong", f"Kepadatan {round(self._density)}% bertahan lebih dari {int(CONGESTION_HOLD)} detik",
                                "Kedua arah", "high")
        else:
            self._macet_since = None
            if self._ok_since is None:
                self._ok_since = t
            if t - self._ok_since >= CONGESTION_HOLD:
                self._macet_logged = False

    def _lane(self, direction):
        return f"Arah A · {self.dir_a}" if direction == "a" else f"Arah B · {self.dir_b}"

    def _add_event(self, t, type_, detail, lane, severity):
        self._events.append({"t": t, "type": type_, "detail": detail, "lane": lane, "severity": severity})
