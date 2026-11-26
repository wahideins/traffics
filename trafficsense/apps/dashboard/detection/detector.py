"""Detektor kendaraan: YOLO berformat ONNX lewat onnxruntime.

Ekspor model (di komputer dengan internet), mis. YOLOv8 nano:
    pip install ultralytics
    yolo export model=yolov8n.pt format=onnx imgsz=640
lalu set TRAFFICSENSE_MODEL=/jalur/yolov8n.onnx. Kelas COCO yang dipakai:
car, motorcycle, bus, truck.
"""
import logging
from typing import List

import numpy as np

from .config import DetectionConfig
from .types import Detection

LOG = logging.getLogger(__name__)

# Indeks kelas COCO -> kelas dashboard.
COCO_TO_CLASS = {2: "mobil", 3: "motor", 5: "bus", 7: "truk"}


class DetectorUnavailable(RuntimeError):
    """Model/pustaka belum siap. Pesannya aman ditampilkan ke pengguna."""


def iou_matrix(a, b):
    """IoU antara array (N,4) dan (M,4) berformat x1,y1,x2,y2."""
    a = np.asarray(a, dtype=np.float32).reshape(-1, 4)
    b = np.asarray(b, dtype=np.float32).reshape(-1, 4)
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)), dtype=np.float32)
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    union = area_a[:, None] + area_b[None, :] - inter
    return inter / np.maximum(union, 1e-6)


def nms(boxes, scores, iou_threshold):
    """NMS sederhana; kembalikan indeks yang dipertahankan."""
    order = np.argsort(-scores)
    keep = []
    while len(order):
        i = order[0]
        keep.append(int(i))
        if len(order) == 1:
            break
        ious = iou_matrix(boxes[i : i + 1], boxes[order[1:]])[0]
        order = order[1:][ious <= iou_threshold]
    return keep


def letterbox(frame, size):
    """Ubah ukuran dengan menjaga rasio, isi sisanya abu-abu. Kembalikan (gambar, skala, pad_x, pad_y)."""
    import cv2

    h, w = frame.shape[:2]
    scale = min(size[0] / w, size[1] / h)
    new_w, new_h = int(round(w * scale)), int(round(h * scale))
    resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size[1], size[0], 3), 114, dtype=np.uint8)
    pad_x, pad_y = (size[0] - new_w) // 2, (size[1] - new_h) // 2
    canvas[pad_y : pad_y + new_h, pad_x : pad_x + new_w] = resized
    return canvas, scale, pad_x, pad_y


def decode_output(output, *, conf, nms_iou, scale, pad_x, pad_y, frame_w, frame_h) -> List[Detection]:
    """Terjemahkan keluaran mentah YOLO menjadi Detection pada koordinat frame asli.

    Mendukung dua tata letak:
      * (1, 4+nc, N) atau (1, N, 4+nc)  — YOLOv8/v11 (cx, cy, w, h, skor per kelas)
      * (1, N, 6)                        — end-to-end/NMS-bawaan (x1, y1, x2, y2, skor, kelas)
    """
    out = np.asarray(output)
    if out.ndim == 3:
        out = out[0]
    if out.ndim != 2:
        raise ValueError(f"Bentuk keluaran model tidak dikenal: {np.asarray(output).shape}")

    if out.shape[1] == 6 and out.shape[0] != 6:  # end-to-end
        boxes = out[:, :4].astype(np.float32)
        scores = out[:, 4].astype(np.float32)
        class_ids = out[:, 5].astype(int)
        keep_idx = scores >= conf
        boxes, scores, class_ids = boxes[keep_idx], scores[keep_idx], class_ids[keep_idx]
        xyxy = boxes
        already_nms = True
    else:
        if out.shape[0] < out.shape[1]:  # (4+nc, N) -> (N, 4+nc); N model nyata >= ratusan
            out = out.T
        if out.shape[1] < 5:
            raise ValueError("Keluaran model tidak memuat skor kelas.")
        cls_scores = out[:, 4:]
        class_ids = cls_scores.argmax(axis=1)
        scores = cls_scores[np.arange(len(out)), class_ids]
        keep_idx = scores >= conf
        out, scores, class_ids = out[keep_idx], scores[keep_idx], class_ids[keep_idx]
        cx, cy, w, h = out[:, 0], out[:, 1], out[:, 2], out[:, 3]
        xyxy = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1)
        already_nms = False

    wanted = np.isin(class_ids, list(COCO_TO_CLASS))
    xyxy, scores, class_ids = xyxy[wanted], scores[wanted], class_ids[wanted]
    if len(xyxy) == 0:
        return []

    if not already_nms:
        keep = []
        for cid in np.unique(class_ids):  # NMS per kelas
            idx = np.where(class_ids == cid)[0]
            keep.extend(idx[nms(xyxy[idx], scores[idx], nms_iou)])
        keep = sorted(keep, key=lambda i: -scores[i])
        xyxy, scores, class_ids = xyxy[keep], scores[keep], class_ids[keep]

    # Kembalikan dari koordinat letterbox ke koordinat frame asli.
    xyxy = xyxy.copy()
    xyxy[:, [0, 2]] = (xyxy[:, [0, 2]] - pad_x) / scale
    xyxy[:, [1, 3]] = (xyxy[:, [1, 3]] - pad_y) / scale
    xyxy[:, [0, 2]] = np.clip(xyxy[:, [0, 2]], 0, frame_w)
    xyxy[:, [1, 3]] = np.clip(xyxy[:, [1, 3]], 0, frame_h)

    return [
        Detection(tuple(float(v) for v in box), float(score), COCO_TO_CLASS[int(cid)])
        for box, score, cid in zip(xyxy, scores, class_ids)
        if box[2] - box[0] > 1 and box[3] - box[1] > 1
    ]


class YoloOnnxDetector:
    def __init__(self, config: DetectionConfig, session=None):
        self._config = config
        self._session = session if session is not None else self._open_session(config.model_path)
        try:
            self.provider = self._session.get_providers()[0].replace("ExecutionProvider", "").lower() or "cpu"
        except (AttributeError, IndexError):
            self.provider = "cpu"
        inp = self._session.get_inputs()[0]
        self._input_name = inp.name
        shape = inp.shape  # [1, 3, H, W]; bisa dinamis (string/None)
        h = shape[2] if isinstance(shape[2], int) else config.imgsz
        w = shape[3] if isinstance(shape[3], int) else config.imgsz
        self._size = (int(w), int(h))

    provider = "cpu"

    @staticmethod
    def _choose_providers(available, preference):
        """Urutan penyedia eksekusi ONNX: GPU bila ada (auto), selalu CPU sebagai cadangan."""
        table = {"cuda": "CUDAExecutionProvider", "dml": "DmlExecutionProvider", "cpu": "CPUExecutionProvider"}
        order = ["cuda", "dml", "cpu"] if preference == "auto" else [preference, "cpu"]
        chosen = list(dict.fromkeys(table[k] for k in order if k in table and table[k] in available))
        return chosen or ["CPUExecutionProvider"]

    def _open_session(self, path):
        if not path:
            raise DetectorUnavailable("Model deteksi belum diatur (variabel TRAFFICSENSE_MODEL).")
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise DetectorUnavailable("Pustaka onnxruntime belum terpasang.") from exc
        try:
            providers = self._choose_providers(ort.get_available_providers(), self._config.provider)
            options = ort.SessionOptions()
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            return ort.InferenceSession(path, sess_options=options, providers=providers)
        except Exception as exc:  # noqa: BLE001 - berkas hilang/rusak
            LOG.error("Gagal memuat model %s: %s", path, exc)
            raise DetectorUnavailable("Model deteksi tidak dapat dimuat. Periksa jalur dan formatnya.") from exc

    def detect(self, frame) -> List[Detection]:
        h, w = frame.shape[:2]
        image, scale, pad_x, pad_y = letterbox(frame, self._size)
        blob = image[:, :, ::-1].transpose(2, 0, 1).astype(np.float32) / 255.0  # BGR->RGB, NCHW
        output = self._session.run(None, {self._input_name: blob[None]})[0]
        return decode_output(
            output,
            conf=min(self._config.conf, self._config.low_conf),  # deteksi skor rendah dipakai ByteTrack
            nms_iou=self._config.nms_iou,
            scale=scale,
            pad_x=pad_x,
            pad_y=pad_y,
            frame_w=w,
            frame_h=h,
        )


def load_detector(config: DetectionConfig):
    """Buat detektor, atau lempar DetectorUnavailable dengan pesan yang jelas."""
    return YoloOnnxDetector(config)
