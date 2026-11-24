from django.urls import path

from .views import pages, panels

app_name = "dashboard"

urlpatterns = [
    # Halaman penuh
    path("", pages.index, name="index"),
    # Potongan HTML per panel (dipakai JS untuk pembaruan berkala)
    path("panels/<slug:name>/", panels.panel, name="panel"),
    path('video-feed/<str:camera_id>/', panels.video_feed, name='video_feed'), #path untuk menampilkan video feed RTSP dari kamera
    #Autentikasi
    path('login/', pages.login_view, name='login'),
    path('logout/', pages.logout_view, name='logout'),
]
