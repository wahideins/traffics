"""Routing utama: seluruh halaman didelegasikan ke app dashboard."""
from django.urls import include, path

urlpatterns = [
    path("", include("apps.dashboard.urls")),
]
