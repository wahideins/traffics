from django.urls import path

from .views import cameras, pages, panels

app_name = "dashboard"

urlpatterns = [
    # Halaman penuh
    path("", pages.index, name="index"),
    # Potongan HTML per panel (dipakai JS untuk pembaruan berkala)
    path("panels/<slug:name>/", panels.panel, name="panel"),
    # Kelola kamera
    path("cameras/probe/", cameras.probe, name="camera_probe"),
    path("cameras/add/", cameras.add, name="camera_add"),
    path("cameras/<slug:code>/stream.mjpg", cameras.stream, name="camera_stream"),
    path("cameras/<slug:code>/snapshot.jpg", cameras.snapshot, name="camera_snapshot"),
    path("cameras/<slug:code>/reconnect/", cameras.reconnect, name="camera_reconnect"),
    path("cameras/<slug:code>/delete/", cameras.delete, name="camera_delete"),
]
