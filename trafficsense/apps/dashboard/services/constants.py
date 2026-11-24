"""Konstanta dashboard: kelas kendaraan, level arus, rentang waktu, filter."""

# Interval pembaruan panel "live" di browser (milidetik) dan skala waktu simulasi.
REFRESH_INTERVAL_MS = 2000
TICK_SECONDS = 1.5

# --- Kelas kendaraan ------------------------------------------------------
# Warna didefinisikan di static/css/components/vehicle-class.css (kelas `c-<key>`).
VEHICLE_CLASSES = (
    {"key": "motor", "name": "Sepeda motor", "short": "Motor"},
    {"key": "mobil", "name": "Mobil", "short": "Mobil"},
    {"key": "bus", "name": "Bus", "short": "Bus"},
    {"key": "truk", "name": "Truk", "short": "Truk"},
)

# --- Level arus lalu lintas ----------------------------------------------
FLOW_LEVELS = {
    "lancar": {
        "label": "Lancar",
        "los": "LOS B",
        "desc": "Arus bebas hambatan. Kecepatan rata-rata mendekati batas kecepatan.",
    },
    "padat": {
        "label": "Padat",
        "los": "LOS D",
        "desc": "Arus mulai tersendat. Jarak antar kendaraan menyempit dan kecepatan menurun.",
    },
    "macet": {
        "label": "Macet",
        "los": "LOS F",
        "desc": "Arus tersendat berat dengan antrean panjang. Kecepatan jauh di bawah batas.",
    },
}

# Ambang kepadatan (%) untuk status Padat dan Macet.
DENSITY_PADAT = 50
DENSITY_MACET = 75

# --- Rentang waktu grafik -------------------------------------------------
DEFAULT_RANGE = "15m"
TIME_RANGES = {
    "15m": {
        "label": "15 menit",
        "points": 15,
        "step": 1,
        "seed": 0,
        "unit": "Kendaraan per menit",
        "x_labels": ("-15 mnt", "-10 mnt", "-5 mnt", "Sekarang"),
    },
    "1h": {
        "label": "1 jam",
        "points": 12,
        "step": 5,
        "seed": 1,
        "unit": "Kendaraan per 5 menit",
        "x_labels": ("-60 mnt", "-45 mnt", "-30 mnt", "-15 mnt", "Sekarang"),
    },
    "24h": {
        "label": "24 jam",
        "points": 24,
        "step": 60,
        "seed": 2,
        "unit": "Kendaraan per jam",
        "x_labels": ("-24 j", "-18 j", "-12 j", "-6 j", "Sekarang"),
    },
}

# --- Kejadian -------------------------------------------------------------
EVENT_TYPES = {
    "speed": "Kecepatan",
    "wrong": "Lawan arah",
    "cong": "Kemacetan",
}
EVENT_FILTERS = (
    ("all", "Semua"),
    ("speed", "Kecepatan"),
    ("wrong", "Lawan arah"),
    ("cong", "Kemacetan"),
)
SEVERITY_LABELS = {"high": "Tinggi", "mid": "Sedang", "low": "Rendah"}

# --- Histogram kecepatan: (label, batas bawah km/j) ----------------------
SPEED_BINS = (
    ("< 20", 0),
    ("20–40", 20),
    ("40–60", 40),
    ("60–80", 60),
    ("> 80", 80),
)
