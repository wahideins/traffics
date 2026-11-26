"""Pembuat berkas ONNX mungil tanpa paket `onnx`: menulis protobuf langsung.

Model hasilnya mengabaikan gambar dan selalu mengeluarkan tensor tetap bergaya YOLOv8
(1, 4+nc, N) berisi satu kendaraan. Cukup untuk menguji jalur onnxruntime sungguhan:
pemuatan sesi, praproses letterbox, dekode, dan pemetaan koordinat balik.
"""
import struct

import numpy as np


def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _field(num, wire, payload):
    return _varint((num << 3) | wire) + payload


def _bytes(num, data):
    return _field(num, 2, _varint(len(data)) + data)


def _str(num, text):
    return _bytes(num, text.encode())


def _int(num, value):
    return _field(num, 0, _varint(value))


def _tensor(name, dims, data_type, raw):
    body = b"".join(_int(1, d) for d in dims) + _int(2, data_type) + _str(8, name) + _bytes(9, raw)
    return body


def _value_info(name, dims):
    shape = b"".join(_bytes(1, _int(1, d)) for d in dims)  # Dimension.dim_value
    tensor_type = _int(1, 1) + _bytes(2, shape)  # elem_type=FLOAT, shape
    return _str(1, name) + _bytes(2, _bytes(1, tensor_type))


def build_constant_yolo_model(*, boxes=((320.0, 320.0, 100.0, 60.0, 2, 0.9),), nc=80, n=8400, size=640,
                              layout="v8"):
    """boxes: (cx, cy, w, h, kelas_coco, skor) pada koordinat masukan model (letterbox)."""
    if layout == "v8":
        out = np.zeros((1, 4 + nc, n), dtype=np.float32)
        for i, (cx, cy, w, h, cls, score) in enumerate(boxes):
            out[0, :4, i] = (cx, cy, w, h)
            out[0, 4 + cls, i] = score
    else:  # end-to-end (1, N, 6): x1,y1,x2,y2,skor,kelas
        out = np.zeros((1, 300, 6), dtype=np.float32)
        for i, (cx, cy, w, h, cls, score) in enumerate(boxes):
            out[0, i] = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, score, cls)

    node = _str(1, "const_out") + _str(2, "output0") + _str(3, "id0") + _str(4, "Identity")
    graph = (
        _bytes(1, node)
        + _str(2, "tiny_yolo")
        + _bytes(5, _tensor("const_out", out.shape, 1, out.tobytes()))
        + _bytes(11, _value_info("images", (1, 3, size, size)))
        + _bytes(12, _value_info("output0", out.shape))
    )
    opset = _str(1, "") + _int(2, 13)
    return _int(1, 8) + _str(2, "tests") + _bytes(7, graph) + _bytes(8, opset)
