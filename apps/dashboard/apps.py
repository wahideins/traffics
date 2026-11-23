from django.apps import AppConfig


class DashboardConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.dashboard"
    verbose_name = "Dashboard lalu lintas"

    def ready(self):
        from django.conf import settings

        from .services import registry

        registry.configure(settings.CAMERA_STORE_PATH)
