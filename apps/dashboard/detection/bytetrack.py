"""Pelacak ByteTrack (Zhang dkk., 2022) tanpa dependensi tambahan selain numpy.

Gagasan ByteTrack: deteksi berskor rendah (kendaraan terhalang, jauh, atau kabur) tidak dibuang,
melainkan dipakai untuk mempertahankan track yang sudah ada. Alurnya per pembaruan:

1. Deteksi dibagi: skor >= high_conf (tinggi) dan low_conf <= skor < high_conf (rendah).
2. Semua track terkonfirmasi (terlihat maupun sedang hilang) diprediksi dengan filter Kalman,
   lalu dicocokkan dengan deteksi tinggi (IoU, penugasan optimal Hungarian).
3. Track yang masih terlihat pada pembaruan sebelumnya tetapi belum cocok dicocokkan dengan
   deteksi rendah (IoU lebih ketat).
4. Track baru (belum terkonfirmasi) dicocokkan dengan deteksi tinggi yang tersisa.
5. Deteksi tinggi yang tersisa membuka track baru. Track baru yang tak cocok langsung dibuang;
   track terkonfirmasi yang hilang ditahan hingga `max_age` detik.

Berbeda dari versi aslinya: kemiripan pencocokan adalah IoU dengan cadangan kedekatan titik pusat
(seperti pelacak lama), karena deteksi ~5 fps membuat kendaraan cepat/kecil bergeser lebih jauh dari
lebarnya antar-frame sehingga IoU-nya nol. Waktu antar-pembaruan tidak tetap (frame bisa terlewat saat inferensi
sibuk), jadi filter Kalman memakai selang waktu nyata, dan keadaan memakai (cx, cy, lebar, tinggi).
Antarmuka sama dengan pelacak lama: `update(detections, t) -> list[Track]`.
"""
from collections import Counter
from typing import List

import numpy as np

from .detector import iou_matrix
from .types import Detection, Track

NOMINAL_DT = 0.2  # detik; satuan kecepatan filter = piksel per selang nominal (5 fps)
STD_POS = 1.0 / 20  # simpangan baku posisi, relatif terhadap tinggi kotak (nilai ByteTrack)
STD_VEL = 1.0 / 160


def linear_assignment(cost):
    """Penugasan optimal (algoritma Hungarian) untuk matriks biaya n x m. Kembalikan [(baris, kolom)]."""
    cost = np.asarray(cost, dtype=np.float64)
    if cost.size == 0:
        return []
    n, m = cost.shape
    transposed = n > m
    if transposed:
        cost, n, m = cost.T, m, n
    inf = float("inf")
    u = np.zeros(n + 1)
    v = np.zeros(m + 1)
    p = np.zeros(m + 1, dtype=int)
    way = np.zeros(m + 1, dtype=int)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = np.full(m + 1, inf)
        used = np.zeros(m + 1, dtype=bool)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta, j1 = inf, 0
            for j in range(1, m + 1):
                if used[j]:
                    continue
                cur = cost[i0 - 1, j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j], way[j] = cur, j0
                if minv[j] < delta:
                    delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    pairs = [(int(p[j]) - 1, j - 1) for j in range(1, m + 1) if p[j] != 0]
    if transposed:
        pairs = [(c, r) for r, c in pairs]
    return sorted(pairs)


def _to_state(box):
    x1, y1, x2, y2 = box
    return np.array([(x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1], dtype=np.float64)


def _to_box(mean):
    cx, cy, w, h = mean[:4]
    w, h = max(w, 1.0), max(h, 1.0)
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


class _Kalman:
    """Kecepatan konstan atas (cx, cy, w, h); keadaan 8 dimensi."""

    @staticmethod
    def initiate(box):
        z = _to_state(box)
        h = max(z[3], 1.0)
        mean = np.concatenate([z, np.zeros(4)])
        std = np.array([2 * STD_POS * h] * 4 + [10 * STD_VEL * h] * 4)
        return mean, np.diag(std ** 2)

    @staticmethod
    def predict(mean, cov, dt):
        k = float(np.clip(dt / NOMINAL_DT, 0.0, 10.0))
        F = np.eye(8)
        F[:4, 4:] = np.eye(4) * k
        h = max(mean[3], 1.0)
        std = np.array([STD_POS * h] * 4 + [STD_VEL * h] * 4) * max(k, 0.5)
        return F @ mean, F @ cov @ F.T + np.diag(std ** 2)

    @staticmethod
    def update(mean, cov, box):
        z = _to_state(box)
        h = max(mean[3], 1.0)
        R = np.diag(np.array([STD_POS * h] * 4) ** 2)
        S = cov[:4, :4] + R
        K = np.linalg.solve(S, cov[:4, :]).T  # (8,4)
        mean = mean + K @ (z - mean[:4])
        cov = cov - K @ S @ K.T
        return mean, cov


class ByteTracker:
    def __init__(self, *, max_age=1.5, min_hits=2, high_conf=0.35, low_conf=0.1,
                 match_sim=0.08, low_match_sim=0.3, new_match_sim=0.08, max_distance=1.0):
        self.max_age = max_age
        self.min_hits = min_hits
        self.high_conf = high_conf
        self.low_conf = min(low_conf, high_conf)
        self.match_sim = match_sim
        self.low_match_sim = low_match_sim
        self.new_match_sim = new_match_sim
        self.max_distance = max_distance  # kelipatan ukuran kotak untuk kedekatan pusat
        self._tracks: List[Track] = []
        self._kf = {}  # id track -> (mean, cov, waktu)
        self._next_id = 1

    @property
    def tracks(self):
        return list(self._tracks)

    def update(self, detections: List[Detection], t: float) -> List[Track]:
        """Perbarui dengan deteksi terbaru. Kembalikan track terkonfirmasi yang terlihat pada `t`."""
        high = [d for d in detections if d.score >= self.high_conf]
        low = [d for d in detections if self.low_conf <= d.score < self.high_conf]

        for tr in self._tracks:
            self._predict(tr, t)

        confirmed = [tr for tr in self._tracks if self._is_confirmed(tr)]
        tentative = [tr for tr in self._tracks if not self._is_confirmed(tr)]

        # 1) track terkonfirmasi (terlihat + hilang) <-> deteksi tinggi
        m1, left_tracks, left_high = self._associate(confirmed, high, self.match_sim)
        for tr, det in m1:
            self._apply(tr, det, t, vote=True)

        # 2) track yang tadi masih terlihat <-> deteksi rendah
        visible = [tr for tr in left_tracks if tr.missed == 0]
        lost_left = [tr for tr in left_tracks if tr.missed > 0]
        m2, still_visible, _ = self._associate(visible, low, self.low_match_sim)
        for tr, det in m2:
            self._apply(tr, det, t, vote=False)

        # 3) track baru <-> deteksi tinggi yang tersisa
        m3, left_tentative, left_high = self._associate(tentative, left_high, self.new_match_sim)
        for tr, det in m3:
            self._apply(tr, det, t, vote=True)

        for tr in still_visible + lost_left:
            tr.missed += 1
        dead = {id(tr) for tr in left_tentative}
        for det in left_high:
            self._spawn(det, t)

        self._tracks = [
            tr for tr in self._tracks
            if id(tr) not in dead and t - tr.t <= self.max_age
        ]
        alive = {tr.id for tr in self._tracks}
        self._kf = {k: v for k, v in self._kf.items() if k in alive}
        return [tr for tr in self._tracks if self._is_confirmed(tr) and tr.missed == 0]

    # --- internal -----------------------------------------------------
    def _is_confirmed(self, track: Track):
        return track.hits >= self.min_hits

    def _predict(self, track: Track, t: float):
        mean, cov, t0 = self._kf[track.id]
        if t > t0:
            mean, cov = _Kalman.predict(mean, cov, t - t0)
            self._kf[track.id] = (mean, cov, t)

    def _predicted_box(self, track: Track):
        return _to_box(self._kf[track.id][0])

    def _similarity(self, pred, dets):
        """max(IoU, 0,5 x kedekatan pusat). Kedekatan: 1 di titik yang sama, 0 pada jarak max_distance x ukuran."""
        iou = iou_matrix(pred, dets)
        pc = np.stack([(pred[:, 0] + pred[:, 2]) / 2, (pred[:, 1] + pred[:, 3]) / 2], 1)
        dc = np.stack([(dets[:, 0] + dets[:, 2]) / 2, (dets[:, 1] + dets[:, 3]) / 2], 1)
        dist = np.linalg.norm(pc[:, None, :] - dc[None, :, :], axis=2)
        size = np.maximum(np.maximum(pred[:, 2] - pred[:, 0], pred[:, 3] - pred[:, 1])[:, None], 1.0)
        closeness = np.clip(1.0 - dist / (size * self.max_distance), 0.0, 1.0) * 0.5
        return np.maximum(iou, closeness)

    def _associate(self, tracks, detections, min_sim):
        """Cocokkan dengan Hungarian pada biaya 1 - kemiripan; pasangan di bawah `min_sim` ditolak."""
        if not tracks or not detections:
            return [], list(tracks), list(detections)
        pred = np.array([self._predicted_box(tr) for tr in tracks], dtype=np.float32)
        dets = np.array([d.box for d in detections], dtype=np.float32)
        sim = self._similarity(pred, dets)
        pairs = [(i, j) for i, j in linear_assignment(1.0 - sim) if sim[i, j] >= min_sim]
        used_t = {i for i, _ in pairs}
        used_d = {j for _, j in pairs}
        return (
            [(tracks[i], detections[j]) for i, j in pairs],
            [tr for i, tr in enumerate(tracks) if i not in used_t],
            [d for j, d in enumerate(detections) if j not in used_d],
        )

    def _apply(self, track: Track, det: Detection, t: float, vote: bool):
        mean, cov, _ = self._kf[track.id]
        self._kf[track.id] = (*_Kalman.update(mean, cov, det.box), t)
        track.box = det.box
        track.hits += 1
        track.missed = 0
        track.t = t
        if vote:  # skor rendah tidak ikut menentukan kelas
            track.votes[det.cls] = track.votes.get(det.cls, 0) + 1
            track.cls = Counter(track.votes).most_common(1)[0][0]
        track.points.append((t, *track.ground))

    def _spawn(self, det: Detection, t: float):
        track = Track(id=self._next_id, cls=det.cls, box=det.box, t=t)
        track.votes[det.cls] = 1
        track.points.append((t, *track.ground))
        mean, cov = _Kalman.initiate(det.box)
        self._kf[track.id] = (mean, cov, t)
        self._next_id += 1
        self._tracks.append(track)
