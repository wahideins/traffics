"""Pembacaan stream RTSP (OpenCV/FFmpeg) dan penyajian ke browser sebagai MJPEG.

Browser tidak bisa memutar RTSP langsung, jadi server membaca stream, menyandikan
frame menjadi JPEG, lalu mengirimkannya sebagai multipart/x-mixed-replace yang
bisa ditampilkan lewat <img>.

Modul di sini tidak mengimpor Django. OpenCV dimuat malas (lazy), sehingga
aplikasi tetap berjalan bila OpenCV belum terpasang; kamera RTSP akan menampilkan
pesan galat yang jelas.

  config.py    pengaturan (transport, timeout, kualitas, dll.)
  capture.py   membuka cv2.VideoCapture dengan opsi RTSP
  frames.py    encode JPEG dan gambar placeholder
  reader.py    thread pembaca satu kamera (+ reconnect otomatis)
  manager.py   mengelola banyak reader, menghentikan yang tak ditonton
  mjpeg.py     generator multipart untuk respons HTTP
  probe.py     tes koneksi sekali jalan (dipakai form tambah kamera)
"""
from .manager import get_manager

__all__ = ["get_manager"]
