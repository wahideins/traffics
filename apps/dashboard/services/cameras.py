"""Katalog kamera demo (data simulasi, tidak membaca stream sungguhan).

Kamera yang ditambahkan pengguna ada di camera_store.py. URL di sini sengaja
disamarkan kredensialnya.
"""
from dataclasses import dataclass
from typing import NamedTuple


class CameraEvent(NamedTuple):
    time: str
    type: str  # speed | wrong | cong
    detail: str
    lane: str
    severity: str  # high | mid | low


@dataclass(frozen=True)
class Camera:
    id: str
    name: str
    short: str
    rtsp_url: str
    speed_limit: int
    dir_a: str
    dir_b: str
    # Parameter simulasi
    base_speed: float
    base_density: float
    base_flow: int  # kendaraan per menit, kedua arah
    offset_a: float
    offset_b: float
    speed_sd: float
    max_speed: int
    wrong_today: int
    wrong_index: int  # indeks kendaraan lawan arah di pratinjau (-1 = tidak ada)
    wrong_lane: str
    speeder_index: int  # indeks kendaraan ngebut di pratinjau (-1 = tidak ada)
    base_duration: float
    vehicle_count: int
    base_counts_a: tuple
    base_counts_b: tuple
    events: tuple

    # Antarmuka yang sama dengan LiveCamera (camera_store.py), dipakai template.
    source = "demo"
    has_analytics = True
    deletable = False

    @property
    def display_url(self):
        return self.rtsp_url


CAMERAS = (
    Camera(
        id="CAM-01",
        name="Jl. Raya Utama KM 12",
        short="Raya Utama KM 12",
        rtsp_url="rtsp://admin:••••@192.168.10.21:554/stream1",
        speed_limit=60,
        dir_a="Timur",
        dir_b="Barat",
        base_speed=48,
        base_density=34,
        base_flow=62,
        offset_a=4,
        offset_b=-6,
        speed_sd=12,
        max_speed=79,
        wrong_today=2,
        wrong_index=2,
        wrong_lane="Arah B · Lajur 1",
        speeder_index=4,
        base_duration=13,
        vehicle_count=9,
        base_counts_a=(412, 268, 14, 37),
        base_counts_b=(389, 251, 11, 42),
        events=(
            CameraEvent("10:07:42", "speed", "Mobil melaju 78 km/j, batas 60 km/j", "Arah A · Lajur 2", "mid"),
            CameraEvent("10:02:15", "wrong", "Sepeda motor melawan arah selama 6 detik", "Arah B · Lajur 1", "high"),
            CameraEvent("09:51:08", "speed", "Truk melaju 71 km/j, batas 60 km/j", "Arah A · Lajur 1", "low"),
            CameraEvent("09:38:30", "cong", "Kepadatan 58% selama 4 menit, kecepatan rata-rata 33 km/j", "Arah B", "mid"),
            CameraEvent("09:22:51", "speed", "Mobil melaju 76 km/j, batas 60 km/j", "Arah A · Lajur 2", "mid"),
            CameraEvent("08:47:19", "wrong", "Mobil melawan arah selama 3 detik", "Arah B · Lajur 2", "high"),
        ),
    ),
    Camera(
        id="CAM-02",
        name="Simpang Pasar Baru",
        short="Simpang Pasar Baru",
        rtsp_url="rtsp://admin:••••@192.168.10.22:554/stream1",
        speed_limit=60,
        dir_a="Utara",
        dir_b="Selatan",
        base_speed=27,
        base_density=61,
        base_flow=71,
        offset_a=8,
        offset_b=-9,
        speed_sd=10,
        max_speed=63,
        wrong_today=3,
        wrong_index=6,
        wrong_lane="Arah A · Lajur 2",
        speeder_index=-1,
        base_duration=27,
        vehicle_count=11,
        base_counts_a=(531, 342, 19, 28),
        base_counts_b=(498, 320, 17, 31),
        events=(
            CameraEvent("10:08:20", "cong", "Kepadatan 63% selama 6 menit, kecepatan rata-rata 26 km/j", "Arah A", "mid"),
            CameraEvent("10:01:47", "wrong", "Mobil melawan arah selama 11 detik", "Arah A · Lajur 2", "high"),
            CameraEvent("09:49:03", "wrong", "Sepeda motor melawan arah selama 4 detik", "Arah B · Lajur 1", "mid"),
            CameraEvent("09:33:25", "cong", "Kepadatan 78% selama 9 menit, antrean sekitar 120 m", "Arah B", "high"),
            CameraEvent("09:12:40", "speed", "Mobil melaju 63 km/j, batas 60 km/j", "Arah A · Lajur 1", "low"),
        ),
    ),
    Camera(
        id="CAM-03",
        name="Gerbang Tol Barat",
        short="Gerbang Tol Barat",
        rtsp_url="rtsp://admin:••••@192.168.10.23:554/stream1",
        speed_limit=60,
        dir_a="Timur",
        dir_b="Barat",
        base_speed=11,
        base_density=86,
        base_flow=44,
        offset_a=4,
        offset_b=-3,
        speed_sd=7,
        max_speed=24,
        wrong_today=0,
        wrong_index=-1,
        wrong_lane="",
        speeder_index=-1,
        base_duration=62,
        vehicle_count=14,
        base_counts_a=(644, 405, 26, 51),
        base_counts_b=(612, 388, 23, 47),
        events=(
            CameraEvent("10:09:10", "cong", "Antrean sekitar 180 m, kecepatan rata-rata 9 km/j", "Arah B", "high"),
            CameraEvent("09:56:32", "cong", "Kepadatan 88% selama 22 menit", "Arah A", "high"),
            CameraEvent("09:20:05", "cong", "Kepadatan 79% selama 14 menit", "Arah B", "high"),
            CameraEvent("08:44:51", "cong", "Kepadatan 66% selama 8 menit", "Arah A", "mid"),
        ),
    ),
)

# Pencarian kamera (demo + tambahan) ada di registry.py.
