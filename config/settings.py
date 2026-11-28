"""Pengaturan Django untuk TrafficSense (tahap front-end, tanpa database)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Keamanan -------------------------------------------------------------
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-ganti-di-produksi")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "gmsipcamtest.my.id", "animation-lab-test-valuable.trycloudflare.com"]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --- Aplikasi -------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "apps.dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
            ],
        },
    },
]

# Tahap ini belum memakai database. Kamera tambahan disimpan di berkas JSON
# (berisi URL RTSP + kredensial: izin 0600, jangan di-commit).
DATABASES = {}
CAMERA_STORE_PATH = Path(
    os.environ.get("TRAFFICSENSE_CAMERA_STORE", BASE_DIR / "data" / "cameras.json")
)

# --- Lokalisasi -----------------------------------------------------------
LANGUAGE_CODE = "id"
TIME_ZONE = "Asia/Jakarta"
USE_I18N = True
USE_TZ = True

# --- Berkas statis --------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Panel admin: pengaturan tersimpan dan folder model (di dalam data/, tidak masuk git).
SETTINGS_PATH = Path(os.environ.get("TRAFFICSENSE_SETTINGS", BASE_DIR / "data" / "settings.json"))
MODELS_DIR = Path(os.environ.get("TRAFFICSENSE_MODELS_DIR", BASE_DIR / "data" / "models"))

# Rekaman video: berkas di folder, indeks di SQLite (keduanya di dalam data/, tidak masuk git).
RECORDINGS_DIR = Path(os.environ.get("TRAFFICSENSE_RECORDINGS_DIR", BASE_DIR / "data" / "recordings"))
RECORDINGS_DB = Path(os.environ.get("TRAFFICSENSE_RECORDINGS_DB", BASE_DIR / "data" / "recordings.sqlite3"))
