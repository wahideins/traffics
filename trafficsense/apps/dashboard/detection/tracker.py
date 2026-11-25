"""Pelacak objek ringan: pencocokan IoU + jarak titik pusat dengan prediksi kecepatan.

Tanpa dependensi tambahan. Cukup untuk lalu lintas satu kamera dengan deteksi
~5 fps; bila nanti perlu lebih tangguh, ganti dengan ByteTrack tanpa mengubah
antarmuka `update(detections, t) -> list[Track]`.
"""
from collections import Counter
from typing import List

import numpy as np

from .detector import iou_matrix
from .types import Detection, Track


class Tracker:
    def __init__(self, *, max_age=1.5, min_hits=3, iou_threshold=0.2, max_distance=0.8):
        self.max_age = max_age
        self.min_hits = min_hits
        self.iou_threshold = iou_threshold
        self.max_distance = max_distance  # kelipatan ukuran kotak untuk pencocokan jarak
        self._tracks: List[Track] = []
        self._next_id = 1

    @property
    def tracks(self):
        return list(self._tracks)

    def update(self, detections: List[Detection], t: float) -> List[Track]:
        """Perbarui dengan deteksi terbaru. Kembalikan track yang sudah terkonfirmasi dan sedang terlihat."""
        predicted = [self._predict(tr, t) for tr in self._tracks]
        matches, unmatched_tracks, unmatched_dets = self._match(predicted, detections)

        for ti, di in matches:
            self._apply(self._tracks[ti], detections[di], t)
        for ti in unmatched_tracks:
            self._tracks[ti].missed += 1
        for di in unmatched_dets:
            self._spawn(detections[di], t)

        self._tracks = [tr for tr in self._tracks if t - tr.points[-1][0] <= self.max_age]
        return [tr for tr in self._tracks if tr.hits >= self.min_hits and tr.missed == 0]

    # --- internal -----------------------------------------------------
    @staticmethod
    def _predict(track: Track, t: float):
        """Geser kotak mengikuti kecepatan terakhir (maks 1 detik ke depan)."""
        if len(track.points) < 2:
            return track.box
        t0, x0, y0 = track.points[max(0, len(track.points) - 4)]
        t1, x1, y1 = track.points[-1]
        dt = t1 - t0
        if dt <= 1e-6:
            return track.box
        ahead = min(t - t1, 1.0)
        dx, dy = (x1 - x0) / dt * ahead, (y1 - y0) / dt * ahead
        x1b, y1b, x2b, y2b = track.box
        return (x1b + dx, y1b + dy, x2b + dx, y2b + dy)

    def _match(self, predicted, detections):
        if not predicted or not detections:
            return [], list(range(len(predicted))), list(range(len(detections)))

        det_boxes = np.array([d.box for d in detections], dtype=np.float32)
        pred_boxes = np.array(predicted, dtype=np.float32)
        iou = iou_matrix(pred_boxes, det_boxes)

        # Skor gabungan: IoU, dengan cadangan kedekatan pusat untuk objek kecil/cepat (motor).
        pc = np.stack([(pred_boxes[:, 0] + pred_boxes[:, 2]) / 2, (pred_boxes[:, 1] + pred_boxes[:, 3]) / 2], 1)
        dc = np.stack([(det_boxes[:, 0] + det_boxes[:, 2]) / 2, (det_boxes[:, 1] + det_boxes[:, 3]) / 2], 1)
        dist = np.linalg.norm(pc[:, None, :] - dc[None, :, :], axis=2)
        size = np.maximum(
            np.maximum(pred_boxes[:, 2] - pred_boxes[:, 0], pred_boxes[:, 3] - pred_boxes[:, 1])[:, None], 1.0
        )
        closeness = np.clip(1.0 - dist / (size * self.max_distance), 0.0, 1.0) * 0.5
        score = np.maximum(iou, closeness)
        score[(iou < self.iou_threshold) & (closeness <= 0)] = 0.0

        pairs = sorted(
            ((score[i, j], i, j) for i in range(score.shape[0]) for j in range(score.shape[1]) if score[i, j] > 0),
            reverse=True,
        )
        used_t, used_d, matches = set(), set(), []
        for _, i, j in pairs:
            if i in used_t or j in used_d:
                continue
            used_t.add(i)
            used_d.add(j)
            matches.append((i, j))
        return (
            matches,
            [i for i in range(len(predicted)) if i not in used_t],
            [j for j in range(len(detections)) if j not in used_d],
        )

    def _apply(self, track: Track, det: Detection, t: float):
        track.box = det.box
        track.hits += 1
        track.missed = 0
        track.t = t
        track.votes[det.cls] = track.votes.get(det.cls, 0) + 1
        track.cls = Counter(track.votes).most_common(1)[0][0]
        track.points.append((t, *track.ground))

    def _spawn(self, det: Detection, t: float):
        track = Track(id=self._next_id, cls=det.cls, box=det.box, t=t)
        track.votes[det.cls] = 1
        track.points.append((t, *track.ground))
        self._next_id += 1
        self._tracks.append(track)
