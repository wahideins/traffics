"""Kendaraan simulasi untuk lapisan pratinjau kamera.

Posisi kendaraan digerakkan CSS (animation), bukan JS. Di sini hanya dihitung
lajur, ukuran, durasi, dan label tiap kotak deteksi.
"""
from .constants import VEHICLE_CLASSES
from .formatting import css_number
from .metrics import pseudo_random

# Pusat tiap lajur (% tinggi pratinjau): 2 lajur arah B (atas), 2 lajur arah A (bawah).
LANE_CENTERS = (27.5, 42.5, 57.5, 72.5)
# Ukuran kotak per kelas (% lebar, % tinggi pratinjau).
SIZES = ((4.2, 5.2), (7.8, 8.6), (15, 10), (12, 9.6))
# Pengali durasi: bus/truk lebih lambat, motor lebih cepat.
DURATION_FACTOR = (0.85, 1.0, 1.25, 1.25)
# Urutan kelas yang dipakai berulang (indeks ke VEHICLE_CLASSES).
CLASS_PATTERN = (1, 0, 1, 3, 0, 2, 1, 0, 1, 3, 0, 1, 0, 1)


def build_feed_vehicles(camera, camera_index):
    lane_totals = [0, 0, 0, 0]
    for i in range(camera.vehicle_count):
        lane_totals[i % 4] += 1

    seen = [0, 0, 0, 0]
    vehicles = []
    for i in range(camera.vehicle_count):
        lane = i % 4
        position_in_lane = seen[lane]
        seen[lane] += 1

        is_speeder = i == camera.speeder_index
        is_wrong = i == camera.wrong_index

        class_index = CLASS_PATTERN[(i + camera_index * 3) % len(CLASS_PATTERN)]
        if is_speeder:
            class_index = 1  # mobil
        if is_wrong:
            class_index = 0  # motor

        vc = VEHICLE_CLASSES[class_index]
        width, height = SIZES[class_index]

        direction = "right" if lane >= 2 else "left"
        if is_wrong:
            direction = "left" if direction == "right" else "right"

        duration = (
            camera.base_duration
            * (0.9 + pseudo_random(i + camera_index * 9) * 0.25)
            * DURATION_FACTOR[class_index]
        )
        if is_speeder:
            duration = camera.base_duration * 0.62
        delay = -duration * (
            (position_in_lane + pseudo_random(i * 3 + camera_index) * 0.4) / lane_totals[lane]
        )

        speed = round(camera.base_speed * (camera.base_duration / duration))
        label = f"{vc['short']} {speed}"
        flag = ""
        if is_speeder:
            label += " · Cepat"
            flag = "speeder"
        if is_wrong:
            label = f"{vc['short']} · Lawan arah"
            flag = "wrong"

        vehicles.append(
            {
                "key": vc["key"],
                "direction": direction,
                "flag": flag,
                "label": label,
                "top": css_number(LANE_CENTERS[lane] - height / 2),
                "w": css_number(width),
                "h": css_number(height),
                "duration": css_number(duration),
                "delay": css_number(delay),
                # Posisi diam bila pengguna memilih "kurangi gerakan".
                "rest": css_number((position_in_lane + 0.5) / lane_totals[lane] * 88, 0),
            }
        )
    return vehicles
