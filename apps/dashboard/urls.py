from django.urls import path

from .views import admin_panel, cameras, pages, panels

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
    path("cameras/<slug:code>/calibration/", cameras.calibration, name="camera_calibration"),
    path("cameras/<slug:code>/delete/", cameras.delete, name="camera_delete"),
    # Panel admin (pengaturan model, deteksi, stream, kamera)
    path("pengaturan/", admin_panel.panel, name="admin_panel"),
    path("pengaturan/masuk/", admin_panel.login, name="admin_login"),
    path("pengaturan/keluar/", admin_panel.logout, name="admin_logout"),
    path("pengaturan/simpan/", admin_panel.save, name="admin_save"),
    path("pengaturan/bawaan/", admin_panel.reset, name="admin_reset"),
    path("pengaturan/kamera/", admin_panel.cameras_fragment, name="admin_cameras"),
    path("pengaturan/kamera/<slug:code>/mulai-ulang/", admin_panel.camera_restart, name="admin_camera_restart"),
    path("pengaturan/kamera/<slug:code>/reset-hitungan/", admin_panel.camera_reset_counts, name="admin_camera_reset"),
    path("pengaturan/model/unggah/", admin_panel.model_upload, name="admin_model_upload"),
    path("pengaturan/model/<str:name>/uji/", admin_panel.model_test, name="admin_model_test"),
    path("pengaturan/model/<str:name>/pakai/", admin_panel.model_use, name="admin_model_use"),
    path("pengaturan/model/<str:name>/hapus/", admin_panel.model_delete, name="admin_model_delete"),
]
