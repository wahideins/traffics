"""Pengaturan yang bisa diubah dari panel admin, disimpan di data/settings.json.

Urutan prioritas nilai: pengaturan tersimpan  >  variabel lingkungan  >  bawaan kode.
Skema di bawah satu-satunya sumber untuk validasi dan untuk membentuk formulir admin.
Tanpa Django; mudah diuji.
"""
import json
import os
import tempfile
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Optional

from ..detection.config import DetectionConfig, load_config as load_detection_env
from ..streaming.config import StreamConfig, load_config as load_stream_env

SETTINGS_VERSION = 1


@dataclass(frozen=True)
class Field:
    key: str
    target: str  # "detection" | "stream"
    group: str
    label: str
    kind: str  # "float" | "int" | "choice"
    help: str = ""
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    choices: tuple = ()  # untuk kind == "choice": ((nilai, label), ...)
    unit: str = ""
    scale: float = 1.0  # tampilan = nilai * scale (mis. 0,30 -> 30 %)
    env: str = ""


GROUPS = {
    "detection": ("Deteksi", "Model dan ambang yang menentukan apa yang dianggap kendaraan."),
    "tracking": ("Pelacakan dan kepadatan", "Seberapa cepat kendaraan dikenali dan bagaimana kepadatan dihitung."),
    "stream": ("Aliran video", "Pembacaan RTSP dan tayangan ke browser. Perubahan memulai ulang semua kamera."),
}

FIELDS = (
    Field("model", "detection", "detection", "Model aktif", "choice",
          "Berkas .onnx di folder model. Kosong memakai TRAFFICSENSE_MODEL.", env="TRAFFICSENSE_MODEL"),
    Field("provider", "detection", "detection", "Perangkat inferensi", "choice",
          "Auto memilih GPU bila ada (CUDA/DirectML), selain itu CPU.",
          choices=(("auto", "Otomatis"), ("cpu", "CPU"), ("cuda", "GPU NVIDIA (CUDA)"), ("dml", "GPU DirectML (Windows)")),
          env="TRAFFICSENSE_PROVIDER"),
    Field("imgsz", "detection", "detection", "Ukuran masukan model", "choice",
          "Dipakai bila model berukuran dinamis. Lebih besar = kendaraan kecil lebih terdeteksi, tetapi lebih lambat.",
          choices=tuple((n, f"{n} px") for n in (320, 416, 480, 640, 800, 960, 1280)), env="TRAFFICSENSE_DETECT_IMGSZ"),
    Field("conf", "detection", "detection", "Ambang skor", "float",
          "Naikkan untuk mengurangi deteksi palsu; turunkan bila kendaraan banyak terlewat.",
          minimum=0.05, maximum=0.95, env="TRAFFICSENSE_DETECT_CONF"),
    Field("nms_iou", "detection", "detection", "Ambang tumpang tindih (NMS)", "float",
          "Kotak yang tumpang tindih melebihi nilai ini dianggap objek yang sama.",
          minimum=0.1, maximum=0.9, env="TRAFFICSENSE_DETECT_NMS_IOU"),
    Field("detect_fps", "detection", "detection", "Frekuensi deteksi", "float",
          "Maksimum inferensi per detik tiap kamera. Turunkan bila CPU/GPU kewalahan.",
          minimum=0.5, maximum=30.0, unit="fps", env="TRAFFICSENSE_DETECT_FPS"),
    Field("track_min_hits", "detection", "tracking", "Deteksi minimum sebelum dihitung", "int",
          "Lebih kecil = kendaraan cepat tercatat tetapi lebih rentan deteksi palsu.",
          minimum=1, maximum=10, unit="kali"),
    Field("track_max_age", "detection", "tracking", "Lama objek ditahan saat hilang", "float",
          "Kendaraan yang tak terdeteksi selama ini dibuang dari pelacakan.",
          minimum=0.3, maximum=10.0, unit="detik"),
    Field("full_occupancy", "detection", "tracking", "Luas kendaraan saat dianggap penuh", "float",
          "Luas semua kotak kendaraan terhadap luas area deteksi pada kepadatan 100%. Kecilkan bila jalan sering tampak lancar padahal ramai.",
          minimum=0.05, maximum=1.0, unit="%", scale=100.0, env="TRAFFICSENSE_FULL_OCCUPANCY"),
    Field("transport", "stream", "stream", "Transport RTSP", "choice",
          "TCP lebih andal; UDP lebih ringan tetapi bisa merusak gambar bila jaringan buruk.",
          choices=(("tcp", "TCP"), ("udp", "UDP")), env="TRAFFICSENSE_RTSP_TRANSPORT"),
    Field("max_width", "stream", "stream", "Lebar maksimum tayangan", "int",
          "Frame yang lebih lebar diperkecil sebelum dikirim ke browser. Tidak memengaruhi deteksi.",
          minimum=320, maximum=3840, unit="px", env="TRAFFICSENSE_STREAM_MAX_WIDTH"),
    Field("jpeg_quality", "stream", "stream", "Kualitas JPEG", "int",
          "Lebih tinggi = lebih tajam, tetapi memakai lebih banyak bandwidth.",
          minimum=30, maximum=95, env="TRAFFICSENSE_STREAM_JPEG_QUALITY"),
    Field("max_fps", "stream", "stream", "Batas fps tayangan", "float",
          "Batas kirim ke browser. Pembacaan dari kamera tetap penuh.",
          minimum=1.0, maximum=30.0, unit="fps", env="TRAFFICSENSE_STREAM_MAX_FPS"),
)
BY_KEY = {f.key: f for f in FIELDS}


def _atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class SettingsStore:
    def __init__(self, path, models_dir):
        self.path = Path(path)
        self.models_dir = Path(models_dir)
        self._lock = threading.RLock()

    def overrides(self):
        with self._lock:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                values = data["values"]
                if data.get("version") != SETTINGS_VERSION or not isinstance(values, dict):
                    return {}
            except (OSError, ValueError, KeyError, TypeError):
                return {}
            return self._clean_stored(values)

    @staticmethod
    def _clean_stored(values):
        """Buang nilai tersimpan yang tak lagi sah (berkas diedit tangan/skema berubah). Satuan internal."""
        clean = {}
        for key, value in values.items():
            field = BY_KEY.get(key)
            if field is None:
                continue
            if field.kind == "choice":
                if key == "model" and isinstance(value, str) and value:
                    clean[key] = value
                elif key != "model" and value in [v for v, _ in field.choices]:
                    clean[key] = value
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                if field.minimum - 1e-9 <= value <= field.maximum + 1e-9:
                    clean[key] = int(value) if field.kind == "int" else float(value)
        return clean

    def save(self, values):
        """Simpan nilai yang sudah divalidasi (menggantikan seluruh set override)."""
        with self._lock:
            payload = {"version": SETTINGS_VERSION, "values": values}
            _atomic_write(self.path, json.dumps(payload, indent=2, ensure_ascii=False))

    def reset(self):
        with self._lock:
            try:
                self.path.unlink()
            except OSError:
                pass

    def model_names(self):
        try:
            return sorted(p.name for p in self.models_dir.iterdir() if p.is_file() and p.suffix.lower() == ".onnx")
        except OSError:
            return []

    # --- validasi ---------------------------------------------------------
    def validate(self, raw, *, partial=False, check_model=True):
        """Ubah isian formulir (string) menjadi nilai bertipe. Kembalikan (nilai, galat).

        Kolom kosong berarti "pakai nilai bawaan" dan tidak disimpan.
        Nilai tampilan (mis. persen) dikembalikan ke satuan internal.
        """
        values, errors = {}, {}
        for key, field in BY_KEY.items():
            if key not in raw:
                continue
            text = str(raw[key]).strip().replace(",", ".") if field.kind != "choice" else str(raw[key]).strip()
            if text == "":
                continue
            try:
                if field.kind == "choice":
                    if key == "model":
                        if check_model and text not in self.model_names():
                            raise ValueError("Model tidak ditemukan di folder model.")
                        values[key] = text
                        continue
                    allowed = {str(v): v for v, _ in field.choices}
                    if text not in allowed:
                        raise ValueError("Pilihan tidak valid.")
                    values[key] = allowed[text]
                    continue
                number = float(text) / field.scale
                if field.kind == "int" and abs(number - round(number)) > 1e-9:
                    raise ValueError("Isi dengan bilangan bulat.")
                if field.minimum is not None and not (field.minimum - 1e-9 <= number <= field.maximum + 1e-9):
                    lo, hi = field.minimum * field.scale, field.maximum * field.scale
                    raise ValueError(f"Harus antara {lo:g} dan {hi:g}{(' ' + field.unit) if field.unit else ''}.")
                values[key] = int(round(number)) if field.kind == "int" else round(number, 6)
            except ValueError as exc:
                errors[key] = str(exc) if any(w in str(exc) for w in ("antara", "Pilihan", "Model", "bulat")) else "Isi dengan angka."
        return values, errors

    # --- konfigurasi efektif ---------------------------------------------
    def detection_config(self) -> DetectionConfig:
        config = load_detection_env()
        over = self.overrides()
        changes = {k: v for k, v in over.items() if k in DetectionConfig.__dataclass_fields__ and k != "model"}
        if over.get("model") and over["model"] in self.model_names():
            changes["model_path"] = str(self.models_dir / over["model"])
        return replace(config, **changes)

    def stream_config(self) -> StreamConfig:
        config = load_stream_env()
        over = self.overrides()
        return replace(config, **{k: v for k, v in over.items() if BY_KEY[k].target == "stream"})

    # --- tampilan formulir -----------------------------------------------
    def describe(self):
        """Daftar bidang untuk formulir: nilai efektif, sumber nilai, dan pilihan."""
        over = self.overrides()
        det, stream = self.detection_config(), self.stream_config()
        sections = []
        for gid, (title, intro) in GROUPS.items():
            items = []
            for f in (f for f in FIELDS if f.group == gid):
                if f.key == "model":
                    current = over.get("model", "")
                    choices = [("", "(ikuti TRAFFICSENSE_MODEL)")] + [(n, n) for n in self.model_names()]
                    effective = Path(det.model_path).name if det.model_path else ""
                else:
                    cfg = det if f.target == "detection" else stream
                    effective = getattr(cfg, f.key)
                    current = over.get(f.key, "")
                    choices = f.choices
                shown = effective * f.scale if f.kind in ("float", "int") and effective != "" else effective
                if f.key in over:
                    source = "disimpan"
                elif f.env and os.environ.get(f.env):
                    source = "lingkungan"
                else:
                    source = "bawaan"
                items.append({
                    "key": f.key, "label": f.label, "kind": f.kind, "help": f.help, "unit": f.unit,
                    "choices": [{"value": v, "label": l, "selected": str(v) == str(effective if f.key != "model" else current)} for v, l in choices],
                    "value": f"{shown:g}".replace(".", ",") if isinstance(shown, (int, float)) else shown,
                    "source": source,
                    "min": f.minimum * f.scale if f.minimum is not None else "",
                    "max": f.maximum * f.scale if f.maximum is not None else "",
                })
            sections.append({"id": gid, "title": title, "intro": intro, "fields": items})
        return sections


_store: Optional[SettingsStore] = None


def configure(path, models_dir):
    global _store
    _store = SettingsStore(path, models_dir)
    return _store


def get_store() -> SettingsStore:
    if _store is None:
        base = Path.cwd() / "data"
        configure(base / "settings.json", base / "models")
    return _store


def effective_detection_config():
    return get_store().detection_config()


def effective_stream_config():
    return get_store().stream_config()
