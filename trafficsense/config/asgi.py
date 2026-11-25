"""Entry point ASGI."""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
application = get_asgi_application()

# Server produksi (gunicorn/uvicorn): nyalakan kamera berdeteksi saat proses mulai.
from apps.dashboard import runtime  # noqa: E402

runtime.start_all()
