from django.apps import AppConfig


class DashboardConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.dashboard"
    verbose_name = "Dashboard lalu lintas"

    def ready(self):
        from django.conf import settings

        from .services import app_settings, registry

        registry.configure(settings.CAMERA_STORE_PATH)
        app_settings.configure(settings.SETTINGS_PATH, settings.MODELS_DIR)
        from .recording import manager as recording_manager

        recording_manager.configure(settings.RECORDINGS_DB, settings.RECORDINGS_DIR)

        # Kamera berdeteksi dihidupkan sejak server berjalan agar penghitungan tak bergantung penonton.
        # `runserver` memakai proses induk + proses anak (reloader): hanya anak (RUN_MAIN) yang menyalakan.
        import os
        import sys

        if len(sys.argv) > 1 and sys.argv[1] == "runserver":
            if os.environ.get("RUN_MAIN") == "true" or "--noreload" in sys.argv:
                from . import runtime

                runtime.start_all()
