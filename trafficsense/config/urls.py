"""Routing utama: seluruh halaman didelegasikan ke app dashboard."""
from django.urls import include, path
from apps.dashboard.views import pages, panels #Modul Panels pada folder apps/dashboard/views/panels.py

urlpatterns = [
    path("", include("apps.dashboard.urls")),
    path('video-feed/<str:camera_id>/', panels.video_feed, name='video_feed'),

    path('login/', pages.login_view, name='login'), # <- Pastikan name='login' ada
    path('logout/', pages.logout_view, name='logout'),
]
