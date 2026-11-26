# TrafficSense — Dashboard analitik lalu lintas CCTV (front-end)

Dashboard memakai Django. Status tahap ini:

- **Nyata:** menambah/menghapus kamera RTSP, tes koneksi, dan video langsung (RTSP → MJPEG di browser).
- **Simulasi:** CAM-01 sampai CAM-03 (kamera demo) beserta seluruh analitiknya.
- **Deteksi nyata (butuh model):** untuk kamera RTSP, hitungan per arah dan kelas, kecepatan,
  lawan arah, kepadatan, status arus, dan kejadian dihitung dari video. Tanpa model, panel
  analitik kamera RTSP kosong ("—") dengan penjelasan, bukan angka palsu.

## Menjalankan

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py runserver
```

Buka http://127.0.0.1:8000/ . Pilihan kamera, rentang waktu, dan filter kejadian
ikut tersimpan di URL (`?camera=CAM-02&range=1h&event_type=wrong`).

Tes:

```bash
python manage.py test apps.dashboard
```

## Kamera RTSP

Klik **Tambah kamera**, isi nama dan tautan RTSP (`rtsp://host:554/path`), nama pengguna/sandi
(opsional), lalu **Tes koneksi** dan **Simpan**. Kamera tersimpan di `data/cameras.json`
(bisa diganti lewat `TRAFFICSENSE_CAMERA_STORE`). Video baru dibuka saat ada yang menonton dan
dihentikan 20 detik setelah penonton terakhir pergi.

Uji tanpa kamera asli (butuh `ffmpeg`):

```bash
python tools/fake_rtsp_server.py --user cctv --password rahasia   # rtsp://127.0.0.1:8554/live
```

Variabel lingkungan opsional: `TRAFFICSENSE_RTSP_TRANSPORT` (tcp/udp), `TRAFFICSENSE_STREAM_MAX_WIDTH`,
`TRAFFICSENSE_STREAM_JPEG_QUALITY`, `TRAFFICSENSE_STREAM_MAX_FPS`.

Struktur tambahan deteksi: `detection/` (detector, tracker, calibration, analyzer, pipeline, manager), `runtime.py` (menyalakan stream + deteksi), `services/live_analytics.py` (angka → template).

**Keamanan (penting sebelum dipakai di luar jaringan tepercaya):**

- Dashboard belum punya login. Siapa pun yang bisa membukanya bisa menambah kamera, yang membuat
  *server* menyambung ke alamat tersebut. Pasang autentikasi atau batasi akses jaringan.
- Sandi disimpan sebagai teks biasa di `data/cameras.json` (izin 0600, masuk `.gitignore`).
  Produksi: gunakan secret manager atau enkripsi.
- Sandi dikirim dari browser ke server saat menyimpan; gunakan HTTPS.
- Sandi tidak pernah dirender ke HTML maupun log (ditampilkan `••••`).
- Alamat link-local/metadata cloud, multicast, dan alamat tak valid ditolak; alamat LAN (10.x, 192.168.x) diizinkan karena CCTV memang di sana.
- Satu penonton memakai satu thread server; dengan beberapa worker gunicorn, tiap worker membuka pembacanya sendiri.

## Deteksi kendaraan

1. Di komputer berinternet, ekspor model YOLO ke ONNX (sekali saja):
   ```bash
   pip install ultralytics
   yolo export model=yolov8n.pt format=onnx imgsz=640
   ```
2. Jalankan server dengan `TRAFFICSENSE_MODEL=/jalur/yolov8n.onnx python manage.py runserver`.
   Kamera RTSP yang tersimpan langsung dinyalakan dan dihitung terus, ada atau tidak ada yang membuka dashboard.
3. Buka kamera → **Kalibrasi**, lalu klik di atas gambar kamera:
   - **Arah A**: dua titik searah lalu lintas Arah A. Garis hitung otomatis tegak lurus panah (geser posisinya dengan slider).
   - **Median** (opsional): satu titik di pemisah jalur. Sisi tempat panah berada = jalur Arah A. Tanpa median (atau centang "jalan satu arah") deteksi lawan arah mati.
   - **Jarak referensi**: dua titik di jalan beserta jarak aslinya (meter). Tanpa ini kecepatan dan pelanggaran batas tidak dihitung.
   - **Area deteksi** (opsional, sangat disarankan di CPU): dua sudut yang membingkai jalan. Hanya bagian ini yang dikirim ke model, sehingga kendaraan jauh tampil lebih besar dan langit/bangunan tidak ikut diproses.

Yang dilakukan: YOLO (mobil, motor, bus, truk) → pelacak IoU → hitung saat melintas garis → kecepatan dari
perpindahan titik tapak × skala → lawan arah dari gerak berlawanan arah jalur → kepadatan dari luas kotak
terhadap frame. Hitungan harian dan grafik disimpan di `data/analytics/` tiap 30 detik (reset tiap pergantian hari).

Perangkat keras: `TRAFFICSENSE_PROVIDER` = `auto` (bawaan: CUDA, lalu DirectML, lalu CPU) / `cpu` / `cuda` / `dml`.
Untuk GPU di Windows, ganti paket: `pip uninstall onnxruntime` lalu `pip install onnxruntime-directml` (GPU apa pun yang mendukung DirectX 12)
atau `onnxruntime-gpu` (NVIDIA + CUDA). Status dan waktu inferensi tampil di bawah video ("Deteksi: x fps · y ms · CPU/DML/CUDA").

Variabel opsional: `TRAFFICSENSE_DETECT_FPS` (5), `TRAFFICSENSE_DETECT_CONF` (0,35),
`TRAFFICSENSE_AUTOSTART=0` (jangan menyalakan kamera saat server hidup), `TRAFFICSENSE_STATE_DIR`.

**Batas akurasi (baca sebelum memakai angkanya):**

- Skala kecepatan memakai satu nilai meter-per-piksel; perspektif (jauh/dekat) membuat galat. Pilih jarak referensi di dekat garis hitung, sejajar jalan.
- Kepadatan adalah perkiraan dari luas kotak (penuh = 30% frame), bukan okupansi jalan sebenarnya; sesuaikan `FULL_OCCUPANCY` di `detection/analyzer.py` per lokasi.
- Pelacak sederhana: kendaraan yang saling menutup bisa tertukar atau terlewat. Untuk lalu lintas padat, ganti dengan ByteTrack (antarmuka `Tracker.update` sama).
- Satu pipeline per kamera memakai CPU; naikkan `TRAFFICSENSE_DETECT_FPS` hanya bila perlu.
- Inferensi model YOLO asli belum diuji di lingkungan pengembangan ini (tanpa berkas model dan jaringan); yang diuji adalah dekode keluaran, pelacak, dan penganalisis dengan deteksi skrip.

## Struktur folder

```
trafficsense/
├── manage.py
├── requirements.txt
├── config/                       # Konfigurasi proyek Django
│   ├── settings.py
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
├── apps/
│   └── dashboard/                # Satu-satunya app saat ini
│       ├── urls.py               # Rute: halaman + endpoint panel
│       ├── views/
│       │   ├── pages.py          # Halaman penuh (index)
│       │   └── panels.py         # Potongan HTML per panel (+ daftar panel)
│       ├── services/             # Lapisan data (tanpa impor Django)
│       │   ├── constants.py      # Kelas kendaraan, level arus, rentang, filter
│       │   ├── cameras.py        # Katalog kamera
│       │   ├── params.py         # Validasi ?camera=&range=&event_type=
│       │   ├── metrics.py        # Arus, hitungan, kecepatan, per arah
│       │   ├── series.py         # Data grafik kongesti dan volume
│       │   ├── vehicles.py       # Kotak deteksi di pratinjau kamera
│       │   ├── events.py         # Log kejadian + ringkasan lawan arah
│       │   ├── formatting.py     # Format angka (ID) dan angka aman-CSS
│       │   └── context.py        # Merakit konteks template
│       └── tests/
│           ├── test_services.py
│           └── test_views.py
├── templates/
│   ├── base.html
│   ├── includes/                 # Dipakai lintas halaman
│   │   ├── styles.html           # Daftar stylesheet (satu tempat)
│   │   └── icon.html             # Ikon SVG
│   └── dashboard/
│       ├── index.html            # Susunan halaman (hanya include)
│       ├── components/           # Potongan kecil yang dipakai ulang
│       │   ├── kpi_card.html
│       │   ├── legend.html
│       │   └── axis_x.html
│       └── partials/             # Satu berkas = satu panel
│           ├── header.html
│           ├── camera_tabs.html
│           ├── camera_feed.html
│           ├── feed_hud.html
│           ├── flow_status.html
│           ├── kpi_cards.html
│           ├── range_toggle.html
│           ├── vehicle_counts.html
│           ├── volume_chart.html
│           ├── congestion_chart.html
│           ├── speed_chart.html
│           ├── wrong_way.html
│           └── events_log.html
└── static/
    ├── css/
    │   ├── tokens.css            # Warna (aksen biru), font, radius
    │   ├── base.css
    │   ├── layout.css
    │   └── components/           # Satu berkas CSS per komponen
    └── js/
        ├── main.js               # Titik masuk
        ├── config.js             # Konfigurasi dari <body data-*>
        ├── state.js              # State + sinkron ke URL
        ├── api.js                # fetch panel
        ├── utils/dom.js
        └── modules/
            ├── panels.js         # Muat ulang panel (berkala dan saat state berubah)
            ├── controls.js       # Klik kamera / rentang / filter
            ├── connection.js     # Simulasi status koneksi RTSP
            └── clock.js
```

Aturan penamaan: nama berkas partial = nama panel = nilai `data-panel`
(mis. `flow_status.html` → `data-panel="flow_status"`). CSS dipisah per komponen
visual di `static/css/components/` (mis. `flow-status.css`, `camera-feed.css`).

## Cara kerja

Halaman dirender penuh oleh Django, lalu JS memperbarui **panel per panel**: browser
meminta `/panels/<nama>/?camera=…&range=…&event_type=…`, Django merender partial yang
sama dengan yang dipakai halaman utama, dan JS menggantikan elemen lamanya. Tidak ada
markup yang ditulis dua kali.

Atribut pada elemen panel mengatur perilakunya:

| Atribut | Arti |
|---|---|
| `data-panel="nama"` | Nama panel (harus terdaftar di `views/panels.py`) |
| `data-refresh="live"` | Ikut diperbarui tiap `REFRESH_INTERVAL_MS` (default 2 detik) |
| `data-depends="camera range eventType"` | Dimuat ulang paksa saat state tersebut berubah |

Pembaruan otomatis ditunda selagi pengguna menunjuk atau memfokuskan panel itu, agar klik
tidak hilang.

## Menambah panel baru

1. Buat `templates/dashboard/partials/<nama>.html` dengan elemen akar ber-`data-panel`.
2. Daftarkan di `PANEL_TEMPLATES` pada `views/panels.py`.
3. `{% include %}` di `templates/dashboard/index.html`.
4. Tambah data yang dibutuhkan di `services/context.py`.
5. Buat `static/css/components/<nama>.css` dan daftarkan di `templates/includes/styles.html`.

## Menyambungkan backend nanti

Ganti isi `services/` (metrics, series, vehicles, events, cameras) dengan sumber data
nyata yang mengembalikan bentuk dict yang sama; view dan template tidak perlu diubah.
Tombol "Lihat klip" belum terhubung. Struktur tambahan: `services/{rtsp_url,camera_form,camera_store,registry,camera_admin}.py`
(logika kamera, tanpa Django), `streaming/` (pembaca RTSP, MJPEG, tes koneksi), `views/cameras.py`, `tools/` (RTSP palsu untuk uji).

## Catatan

- Locale `id` membuat Django menampilkan desimal berkoma (12,5). Angka yang masuk ke
  atribut `style` diformat sebagai string bertitik lewat `css_number()`; jangan kirim
  float mentah ke style.
- Produksi: set `DJANGO_DEBUG=0`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, jalankan
  `collectstatic`, dan sajikan berkas statis lewat web server atau WhiteNoise.
- Font memakai Google Fonts (Inter, Space Grotesk); tanpa internet dipakai font sistem.

## Panel admin (`/pengaturan/`)

Atur model deteksi dan parameter tanpa menyunting environment:

- **Model**: unggah `.onnx` (maks 400 MB), uji kecepatan di komputer ini, pakai, atau hapus. Berkas ada di `data/models/` (ubah dengan `TRAFFICSENSE_MODELS_DIR`).
- **Parameter**: perangkat (CPU/CUDA/DirectML), ukuran masukan, ambang skor, NMS, fps deteksi, pelacakan, kepadatan, serta transport/lebar/kualitas/fps tayangan. Tersimpan di `data/settings.json`; "Kembalikan ke bawaan" menghapusnya. Menyimpan memulai ulang semua kamera.
- **Kamera**: mulai ulang, reset hitungan, lihat kinerja (fps, ms, perangkat).

Akses: bila `TRAFFICSENSE_ADMIN_PASSWORD` diatur, halaman meminta sandi (PowerShell: `$env:TRAFFICSENSE_ADMIN_PASSWORD = "..."`). Tanpa sandi, hanya bisa dibuka dari komputer server itu sendiri. Bila memakai reverse proxy di mesin yang sama, selalu atur sandi.

Catatan: tambah, hapus, sambung ulang, dan kalibrasi kamera ada di halaman Pengaturan (dengan aturan akses yang sama); dashboard hanya menampilkan video dan analitik.
