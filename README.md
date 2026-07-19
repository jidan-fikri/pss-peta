# Panduan Pengguna: P.E.T.A (Pengolah Ekstraksi Titik Area)

**P.E.T.A** adalah aplikasi mandiri berbasis antarmuka grafis (GUI) yang dirancang untuk mempercepat ekstraksi data spasial dari peta penampang raster statis (geolistrik) menjadi data numerik siap-model (X, Y, Z). 

---

## 1. Persiapan Sistem dan Berkas
Sebelum memulai, pastikan Anda telah menyiapkan:
1. **Berkas Peta Raster:** Peta penampang geofisika dalam format `.JPG`, `.PNG`, atau `.TIFF`. Pastikan gambar memiliki resolusi yang cukup agar legenda warna terlihat jelas.
2. **Informasi Georeferensi:** Koordinat batas aktual (X minimum/maksimum, Y minimum/maksimum) dari penampang lintasan jika diperlukan untuk kalibrasi spasial.

---

## 2. Pengenalan Antarmuka (User Interface)
Saat membuka aplikasi, Anda akan melihat tiga area utama:
* **Panel Kontrol (Kiri/Atas):** Berisi tombol untuk memuat gambar, mengatur batas koordinat, mengekstrak warna, dan mengekspor data.
* **Kanvas Spasial (Tengah):** Area penampil (*viewer*) interaktif tempat Anda melakukan digitasi poligon dan melakukan QC visual.
* **Log Status (Bawah):** Menampilkan notifikasi sistem, progres perhitungan, dan status keberhasilan ekstraksi.

---

## 3. Standar Operasional Prosedur (SOP) Ekstraksi

### Langkah 1: Memuat Peta Raster
1. Klik tombol **[Load Image / Buka Gambar]** pada panel kontrol.
2. Cari dan pilih berkas peta penampang geolistrik dari direktori Anda.
3. Gambar akan langsung dirender dan ditampilkan di dalam Kanvas Spasial.

### Langkah 2: Digitasi Area Batasan (Region of Interest)
Langkah ini menggantikan proses ekstraksi titik manual pada perangkat lunak GIS.
1. Aktifkan mode digitasi dengan mengklik **[Draw Area / Gambar Poligon]**.
2. Klik titik-titik batas terluar area peta yang ingin diekstrak datanya di atas kanvas (abaikan area putih atau teks yang tidak relevan).
3. Tutup poligon dengan mengklik kembali titik pertama, atau klik dua kali (*double-click*). Area yang akan diekstrak kini telah terdefinisi oleh sistem (OpenCV).

### Langkah 3: Kalibrasi Skala Warna (Color Scale Bar)
Langkah ini adalah kunci dari algoritma P.E.T.A untuk menggantikan rumus VLOOKUP Excel secara otomatis.
1. Klik tombol **[Define Legend / Set Skala Warna]**.
2. Arahkan kursor pada gambar legenda warna (Color Scale) di peta Anda.
3. Klik nilai ekstremum atas (warna maksimal) dan masukkan nilai aktualnya (misal: resistivitas tertinggi).
4. Klik nilai ekstremum bawah (warna minimal) dan masukkan nilai aktualnya.
5. Sistem akan menyimpan gradasi nilai tersebut sebagai referensi interpolasi.

### Langkah 4: Ekstraksi dan Interpolasi (KD-Tree Processing)
1. Atur kerapatan titik (*Grid Spacing*) yang Anda inginkan (misalnya interval 5 meter atau 10 meter).
2. Klik tombol **[Extract Data / Ekstrak Nilai Z]**.
3. *Mesin komputasi NumPy dan algoritma SciPy (KD-Tree) akan bekerja di latar belakang, mencocokkan puluhan ribu nilai warna RGB pada peta dengan legenda warna untuk menghasilkan nilai Z (kedalaman/amplitudo).*

### Langkah 5: Siklus Koreksi Visual (Visual QA/QC)
1. Setelah ekstraksi selesai, P.E.T.A akan menampilkan titik-titik hasil (*scatter plot overlay*) di atas peta asli menggunakan Matplotlib.
2. Lakukan inspeksi visual: periksa apakah ada titik yang melenceng atau warna anomali yang tidak terbaca dengan benar.
3. Jika terdapat *noise* (seperti garis tepi peta atau teks yang ikut terekstrak), gunakan fitur **[Erase / Hapus Titik]** untuk membersihkannya secara interaktif.

### Langkah 6: Ekspor Data
1. Setelah data dirasa akurat dan bersih, klik tombol **[Export to CSV]**.
2. Pilih folder tujuan dan ketik nama *file* (misal: `Lintasan_A_Extracted.csv`).
3. Berkas data tabular (*X, Y, Z*) kini siap diimpor langsung ke dalam perangkat lunak pemodelan 3D Anda (seperti Micromine, Leapfrog, atau Datamine).

---

## 4. Troubleshooting (Penyelesaian Masalah)

* **Gambar Terlihat Pecah di Kanvas:** Pastikan resolusi asli gambar raster di atas 1080p. Jika gambar terlalu kecil, algoritma pendeteksi warna akan kesulitan membedakan gradasi yang kabur (blur).
* **Nilai Z Menjadi "NaN" atau Nol Semua:** Ini terjadi jika Kalibrasi Skala Warna pada Langkah 3 tidak menutupi rentang warna yang ada di dalam peta. Ulangi pendefinisian legenda dan pastikan Anda mengambil titik warna paling ekstrem.
* **Aplikasi Terhenti (Not Responding) Saat Ekstraksi:** Hal ini normal jika kerapatan *grid* yang Anda atur terlalu padat pada komputer dengan spesifikasi terbatas. Biarkan aplikasi memproses data selama beberapa detik hingga indikator progres selesai.
