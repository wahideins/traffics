"""Entry point WSGI."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
application = get_wsgi_application()

# Server produksi (gunicorn/uvicorn): nyalakan kamera berdeteksi saat proses mulai.
from apps.dashboard import runtime  # noqa: E402

runtime.start_all()
