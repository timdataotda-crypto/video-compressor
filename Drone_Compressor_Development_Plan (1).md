# Drone Compressor — Rencana Pengembangan

## 1. Ringkasan

**Drone Compressor** adalah aplikasi desktop lokal untuk melakukan kompresi video secara batch dari banyak file MP4/MOV dengan target ukuran maksimum tertentu, terutama **19 MB per video**.

Aplikasi dirancang untuk:
- memilih satu folder sumber;
- membaca seluruh subfolder secara recursive;
- menemukan video secara otomatis;
- mempertahankan struktur folder;
- menghitung bitrate berdasarkan durasi;
- melakukan encoding H.264/AAC;
- melakukan validasi ukuran hasil;
- melakukan retry otomatis jika hasil masih melebihi target;
- menampilkan progress secara real-time;
- dapat melanjutkan pekerjaan setelah aplikasi ditutup;
- bekerja secara lokal tanpa mengunggah video ke server.

---

# 2. Tujuan Produk

## Tujuan Utama

Menyediakan aplikasi sederhana yang memungkinkan pengguna mengompres ratusan video drone sekaligus menjadi file dengan ukuran **<= 19 MB**, dengan kualitas sebaik mungkin.

## Prinsip Utama

1. Local-first: video tidak keluar dari komputer.
2. Batch-first: pengguna tidak perlu memilih video satu per satu.
3. Size-first: target ukuran lebih penting daripada preset kualitas tetap.
4. Safe output: file asli tidak diubah.
5. Resume-able: pekerjaan dapat dilanjutkan.
6. Adaptive: bitrate dan resolusi disesuaikan dengan karakteristik video.

---

# 3. Target Platform

## Prioritas

### macOS
- Apple Silicon
- Intel Mac

### Windows
- Windows 10
- Windows 11

## Future

- Linux desktop

---

# 4. Teknologi

| Komponen | Teknologi |
|---|---|
| Bahasa | Python 3.12+ |
| GUI | PySide6 |
| Video engine | FFmpeg |
| Metadata | FFprobe |
| Database | SQLite |
| Concurrency | QThread / ThreadPoolExecutor |
| Packaging | PyInstaller |
| Testing | pytest |
| Logging | Python logging |

---

# 5. Arsitektur

```text
                  DRONE COMPRESSOR
                         |
                  PySide6 GUI
                         |
                  Job Manager
                         |
          +--------------+--------------+
          |                             |
     File Scanner                   SQLite
          |
      FFprobe
          |
   Video Analyzer
          |
   Bitrate Calculator
          |
 Adaptive Resolution
          |
    FFmpeg Engine
          |
    Size Validator
          |
      +---+---+
      |       |
    <=19MB   >19MB
      |       |
   SUCCESS   RETRY
```

---

# 6. Struktur Project

```text
drone-compressor/
│
├── app/
│   ├── __init__.py
│   ├── main.py
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── scanner.py
│   │   ├── analyzer.py
│   │   ├── bitrate.py
│   │   ├── resolution.py
│   │   ├── compressor.py
│   │   ├── validator.py
│   │   └── job_manager.py
│   │
│   ├── ffmpeg/
│   │   ├── __init__.py
│   │   ├── ffmpeg.py
│   │   ├── ffprobe.py
│   │   └── hardware.py
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── video.py
│   │   └── job.py
│   │
│   ├── database/
│   │   ├── __init__.py
│   │   └── database.py
│   │
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── main_window.py
│   │   ├── settings_dialog.py
│   │   ├── job_table.py
│   │   └── styles.qss
│   │
│   └── utils/
│       ├── __init__.py
│       ├── logger.py
│       ├── paths.py
│       └── system.py
│
├── bin/
│   ├── macos/
│   │   ├── ffmpeg
│   │   └── ffprobe
│   └── windows/
│       ├── ffmpeg.exe
│       └── ffprobe.exe
│
├── assets/
│   ├── icons/
│   └── logo/
│
├── tests/
│   ├── test_scanner.py
│   ├── test_bitrate.py
│   ├── test_resolution.py
│   ├── test_validator.py
│   └── test_paths.py
│
├── logs/
├── output/
│
├── config.json
├── requirements.txt
├── README.md
├── build_macos.spec
├── build_windows.spec
└── .gitignore
```

---

# 7. Modul Utama

## 7.1 Scanner

Tugas:
- membaca source folder;
- recursive scan;
- mendeteksi extension video;
- mengabaikan file temporary;
- mengembalikan daftar video.

Extension awal:

```text
.mp4
.mov
.m4v
.mkv
.avi
```

---

## 7.2 Analyzer

FFprobe digunakan untuk membaca:

- duration;
- width;
- height;
- FPS;
- codec;
- bitrate;
- audio codec;
- audio bitrate;
- frame rate;
- rotation/orientation;
- file size.

Contoh metadata:

```json
{
  "duration": 63.4,
  "width": 3840,
  "height": 2160,
  "fps": 59.94,
  "video_codec": "h264",
  "audio_codec": "aac",
  "file_size_mb": 428.2
}
```

---

# 8. Algoritma Target 19 MB

## 8.1 Target

```text
TARGET_SIZE = 19 MB
```

Gunakan margin keamanan agar container MP4 tidak melewati target.

```text
SAFETY_MARGIN = 0.94
```

Target internal:

```text
19 MB × 0.94
```

---

## 8.2 Perhitungan Bitrate

```text
usable_bytes =
    target_bytes × safety_margin

usable_bits =
    usable_bytes × 8

total_bitrate =
    usable_bits / duration

video_bitrate =
    total_bitrate - audio_bitrate
```

Default:

```text
audio_bitrate = 96 kbps
```

---

# 9. Contoh Perhitungan

Video:

```text
Duration = 60 seconds
Target = 19 MB
Audio = 96 kbps
```

Perkiraan:

```text
Target bits:
19 × 1024 × 1024 × 8

Usable bits:
Target bits × 0.94

Total bitrate:
Usable bits / 60

Video bitrate:
Total bitrate - 96 kbps
```

Bitrate tersebut menjadi bitrate awal FFmpeg.

---

# 10. Adaptive Resolution

Target ukuran kecil dapat membuat 4K tidak efisien.

Rule awal:

```text
>= 5 Mbps
    pertahankan resolusi asli

2.5–5 Mbps
    maksimal 1080p

1.2–2.5 Mbps
    maksimal 720p

< 1.2 Mbps
    maksimal 540p
```

Aspect ratio harus selalu dipertahankan.

Resolusi harus dibulatkan ke dimensi genap untuk kompatibilitas encoder.

---

# 11. Encoding

## Default

```text
Video:
H.264 / libx264

Audio:
AAC

Audio bitrate:
96 kbps

Preset:
medium

Container:
MP4

Fast start:
enabled
```

FFmpeg concept:

```bash
ffmpeg \
  -i input.mp4 \
  -vf "scale=..." \
  -c:v libx264 \
  -b:v TARGET_BITRATE \
  -c:a aac \
  -b:a 96k \
  -movflags +faststart \
  output.mp4
```

---

# 12. Two-Pass Encoding

Untuk mode **Maximum Size Accuracy**, gunakan two-pass encoding.

## Pass 1

```text
Input
  ↓
FFmpeg analysis
  ↓
Encoding statistics
```

## Pass 2

```text
Input
  ↓
Target bitrate
  ↓
Final MP4
```

Two-pass digunakan untuk hasil ukuran yang lebih konsisten.

---

# 13. Retry Algorithm

Setelah encoding selesai:

```text
actual_size <= target
    SUCCESS

actual_size > target
    calculate new bitrate
    encode again
```

Formula:

```text
new_bitrate =
    current_bitrate
    × (target_size / actual_size)
    × retry_margin
```

Default:

```text
retry_margin = 0.96
```

Contoh:

```text
Current size = 19.8 MB
Target = 19 MB

new_bitrate =
current_bitrate
× (19 / 19.8)
× 0.96
```

---

# 14. Maximum Retry

Default:

```text
MAX_RETRIES = 4
```

Jika setelah 4 percobaan masih >19 MB:

```text
FAILED
```

Aplikasi harus menyimpan error detail.

---

# 15. Output Folder

Jika source:

```text
DRONE/
├── DAY_01/
│   ├── DJI_001.mp4
│   └── DJI_002.mp4
├── DAY_02/
│   └── DJI_003.mp4
```

Output:

```text
DRONE_COMPRESSED/
├── DAY_01/
│   ├── DJI_001.mp4
│   └── DJI_002.mp4
├── DAY_02/
│   └── DJI_003.mp4
```

Original tidak boleh diubah.

---

# 16. Database

SQLite digunakan untuk job management.

## Table: jobs

```text
id
source_path
output_path
duration
original_size
output_size
video_bitrate
resolution
status
progress
attempt
error
created_at
started_at
completed_at
```

## Status

```text
PENDING
ANALYZING
COMPRESSING
VALIDATING
COMPLETED
FAILED
SKIPPED
CANCELLED
```

---

# 17. Resume

Jika aplikasi berhenti:

```text
127 total
43 completed
84 pending
```

Saat aplikasi dibuka:

```text
Resume previous job?
```

Jika user memilih Resume:

```text
COMPLETED
```

tidak diproses ulang.

File:

```text
PENDING
FAILED
CANCELLED
```

dapat diproses kembali.

---

# 18. GUI

## Main Window

```text
┌─────────────────────────────────────────────────────┐
│ DRONE COMPRESSOR                         ⚙ Settings │
├─────────────────────────────────────────────────────┤
│                                                     │
│ SOURCE                                              │
│ [ /Users/.../DRONE                         ] [📁]   │
│                                                     │
│ OUTPUT                                              │
│ [ /Users/.../DRONE_COMPRESSED             ] [📁]   │
│                                                     │
│ TARGET                                              │
│ [ 19 ] MB                                           │
│                                                     │
│ Codec       [ H.264 ▼ ]                             │
│ Resolution  [ Auto ▼ ]                              │
│ Audio       [ 96 kbps ▼ ]                           │
│                                                     │
│ ☑ Recursive folders                                 │
│ ☑ Preserve structure                                │
│ ☑ Skip existing                                     │
│ ☑ Auto retry                                        │
│                                                     │
│             [ START COMPRESSION ]                    │
│                                                     │
├─────────────────────────────────────────────────────┤
│ CURRENT JOB                                         │
│                                                     │
│ DJI_034.mp4                                         │
│ ███████████████████░░░░ 78%                        │
│                                                     │
│ Original: 87.4 MB                                   │
│ Output:   18.6 MB                                   │
│ Reduction: 78.7%                                    │
│                                                     │
├─────────────────────────────────────────────────────┤
│ Total: 127 | Done: 34 | Failed: 0 | Remaining: 93 │
└─────────────────────────────────────────────────────┘
```

---

# 19. Drag & Drop

User dapat menarik folder:

```text
Finder / Explorer
       ↓
Drop ke aplikasi
       ↓
Source folder otomatis terisi
```

Drag-and-drop harus mendukung:
- folder;
- satu video;
- beberapa video.

---

# 20. Job Table

Tambahkan tabel:

| File | Status | Progress | Original | Output |
|---|---|---:|---:|---:|
| DJI_001.mp4 | Completed | 100% | 82 MB | 18.7 MB |
| DJI_002.mp4 | Compressing | 67% | 91 MB | — |
| DJI_003.mp4 | Pending | 0% | 74 MB | — |
| DJI_004.mp4 | Failed | 0% | 120 MB | — |

User dapat:
- pause;
- resume;
- cancel;
- retry failed;
- open output folder.

---

# 21. Settings

## General

```text
Target size
Codec
Audio bitrate
Preset
Resolution
```

## Processing

```text
Workers
Maximum retries
Safety margin
Hardware acceleration
```

## Output

```text
Preserve folder structure
Overwrite existing
Skip existing
Output suffix
```

---

# 22. Hardware Acceleration

Auto detection:

```text
NVIDIA
    ↓
h264_nvenc

Intel
    ↓
h264_qsv

Apple
    ↓
h264_videotoolbox

Fallback
    ↓
libx264
```

Settings:

```text
Hardware Acceleration:
[ Auto ]
```

Options:

```text
Auto
CPU
NVIDIA NVENC
Intel QSV
Apple VideoToolbox
```

---

# 23. Concurrency

Jangan menggunakan satu FFmpeg untuk setiap CPU core.

Default:

```text
workers = 2
```

Rekomendasi:

```text
CPU 4–8 cores
    workers = 2

CPU 8–16 cores
    workers = 2–3

CPU >16 cores
    workers = 3–4
```

User dapat mengubahnya.

---

# 24. Progress Parsing

FFmpeg output harus diparsing menggunakan:

```text
frame
fps
time
speed
bitrate
```

Kemudian dikonversi menjadi:

```text
progress = processed_duration / total_duration
```

GUI menampilkan:

```text
78%
00:42 / 00:54
Speed 2.3x
```

---

# 25. Logging

Log file:

```text
logs/
├── app.log
├── jobs.log
└── errors.log
```

Contoh:

```text
2026-08-27 18:20:04
JOB START

Input:
DJI_034.mp4

Duration:
54.3 sec

Target:
19 MB

Initial bitrate:
2,650 kbps

Output:
18.62 MB

Status:
COMPLETED
```

---

# 26. Error Handling

Aplikasi harus menangani:

- FFmpeg tidak ditemukan;
- FFprobe tidak ditemukan;
- file rusak;
- permission denied;
- disk penuh;
- source hilang;
- output gagal dibuat;
- encoding gagal;
- codec tidak tersedia;
- target tidak realistis;
- aplikasi ditutup saat encoding.

Pesan error harus mudah dipahami user.

Contoh:

```text
Compression failed.

Reason:
Not enough disk space.

Please free at least 2 GB
and try again.
```

---

# 27. Validasi Disk

Sebelum batch dimulai:

```text
Estimate required temporary disk space
```

Jika tidak cukup:

```text
WARNING

Not enough disk space may be available.

Continue?
[ Cancel ] [ Continue ]
```

---

# 28. Temporary Files

Gunakan folder:

```text
.temp/
```

atau OS temporary directory.

Contoh:

```text
temp/
├── job_001_pass1/
├── job_002_pass1/
└── ...
```

Setelah sukses:

```text
delete temporary files
```

---

# 29. Security & Privacy

Karena aplikasi memproses video lokal:

- tidak ada upload;
- tidak ada cloud storage;
- tidak ada analytics wajib;
- tidak ada video dikirim ke API;
- file original tidak dimodifikasi;
- path file hanya disimpan lokal jika job history diaktifkan.

---

# 30. Development Phases

## Phase 1 — Core Engine

Target:
- scanner;
- FFprobe;
- bitrate calculator;
- FFmpeg encoder;
- validator;
- retry.

Deliverable:

```text
CLI:
python -m app.compress /source /output
```

---

## Phase 2 — GUI MVP

Target:
- source folder;
- output folder;
- target size;
- start;
- progress;
- result.

Deliverable:

```text
Desktop GUI
```

---

## Phase 3 — Batch & Folder Management

Target:
- recursive scan;
- preserve folders;
- skip existing;
- job table;
- batch queue.

---

## Phase 4 — Advanced Encoding

Target:
- two-pass;
- adaptive resolution;
- hardware acceleration;
- automatic codec detection;
- bitrate optimization.

---

## Phase 5 — Persistence

Target:
- SQLite;
- resume;
- job history;
- retry failed.

---

## Phase 6 — Production UI

Target:
- polished UI;
- dark mode;
- drag-and-drop;
- settings;
- notifications;
- keyboard shortcuts.

---

## Phase 7 — Packaging

Target:

### macOS

```text
DroneCompressor.app
```

### Windows

```text
DroneCompressor.exe
```

dan installer.

---

# 31. MVP Acceptance Criteria

MVP dianggap berhasil jika:

- [ ] User dapat memilih source folder.
- [ ] User dapat memilih output folder.
- [ ] Semua video dalam subfolder terdeteksi.
- [ ] Target default adalah 19 MB.
- [ ] Bitrate dihitung berdasarkan durasi.
- [ ] Video dikonversi ke H.264/AAC.
- [ ] Output <=19 MB untuk video yang dapat dikompresi dalam batas minimum kualitas.
- [ ] Jika >19 MB, aplikasi melakukan retry.
- [ ] Struktur folder dipertahankan.
- [ ] File original tidak berubah.
- [ ] Progress ditampilkan.
- [ ] Error ditampilkan.
- [ ] Batch processing berjalan tanpa interaksi per file.

---

# 32. Production Acceptance Criteria

- [ ] Resume job.
- [ ] SQLite job history.
- [ ] Hardware acceleration.
- [ ] Two-pass encoding.
- [ ] Adaptive resolution.
- [ ] Drag-and-drop.
- [ ] Multi-worker queue.
- [ ] Disk space validation.
- [ ] Temporary file cleanup.
- [ ] Crash-safe job state.
- [ ] macOS packaging.
- [ ] Windows packaging.
- [ ] Automated tests.
- [ ] Logging.
- [ ] Versioning.

---

# 33. Testing Strategy

## Unit Test

Test:

```text
bitrate calculation
resolution calculation
path mapping
size validation
retry calculation
```

## Integration Test

Test:

```text
input video
    ↓
FFprobe
    ↓
bitrate
    ↓
FFmpeg
    ↓
validator
```

## Batch Test

Gunakan:

```text
10 videos
50 videos
100 videos
500 videos
```

## Stress Test

Test:

```text
4K
1080p
720p
30 FPS
60 FPS
120 FPS
short video
long video
large source
```

---

# 34. Quality Profiles

Buat tiga mode:

## Fast

```text
Preset:
fast

Encoding:
1-pass

Hardware:
preferred
```

Untuk batch besar.

## Balanced

```text
Preset:
medium

Encoding:
2-pass

Adaptive resolution:
ON
```

Default.

## Maximum Quality

```text
Preset:
slow

Encoding:
2-pass

Adaptive resolution:
conservative
```

Untuk hasil terbaik.

---

# 35. Preset Target

Selain custom size:

```text
5 MB
10 MB
15 MB
19 MB
25 MB
50 MB
Custom
```

Default:

```text
19 MB
```

---

# 36. Future Feature: Smart Compression

Versi lanjutan dapat menganalisis:

```text
motion
scene complexity
noise
dark scenes
sky
water
foliage
```

Kemudian menentukan:

```text
bitrate
resolution
preset
```

secara lebih adaptif.

Ini berguna untuk footage drone karena:
- langit relatif mudah;
- foliage kompleks;
- air memiliki detail;
- gerakan kamera tinggi;
- footage malam membutuhkan bitrate berbeda.

---

# 37. Future Feature: Contact Sheet

Setelah selesai, aplikasi dapat membuat:

```text
Compression Report

127 videos
Original: 14.2 GB
Output: 2.31 GB
Saved: 83.7%
Average size: 18.2 MB
```

---

# 38. Future Feature: Export Report

Format:

```text
CSV
JSON
HTML
PDF
```

Contoh:

```text
DJI_001.mp4
Original: 83.2 MB
Output: 18.7 MB
Reduction: 77.5%
Duration: 00:54
Status: Completed
```

---

# 39. Roadmap

```text
Week 1
├── Project setup
├── FFmpeg integration
├── Scanner
└── FFprobe analyzer

Week 2
├── Bitrate engine
├── Encoder
├── Validator
└── Retry system

Week 3
├── PySide6 GUI
├── Progress
└── Batch queue

Week 4
├── SQLite
├── Resume
├── Job history
└── Error handling

Week 5
├── Adaptive resolution
├── Two-pass
├── Hardware acceleration
└── Performance optimization

Week 6
├── UI polish
├── Testing
├── macOS build
└── Windows build
```

---

# 40. Recommended Development Order

Urutan implementasi yang disarankan:

```text
1. FFmpeg detection
        ↓
2. FFprobe
        ↓
3. Scanner
        ↓
4. Bitrate calculator
        ↓
5. Basic encoder
        ↓
6. Size validator
        ↓
7. Retry algorithm
        ↓
8. Folder preservation
        ↓
9. CLI test
        ↓
10. PySide6 GUI
        ↓
11. Progress parsing
        ↓
12. Batch queue
        ↓
13. SQLite
        ↓
14. Resume
        ↓
15. Adaptive resolution
        ↓
16. Two-pass
        ↓
17. Hardware acceleration
        ↓
18. Drag & drop
        ↓
19. Packaging
        ↓
20. Production testing
```

---

# 41. Definition of Done

Project dinyatakan selesai jika user dapat melakukan:

```text
Pilih Folder
      ↓
Target 19 MB
      ↓
START
      ↓
Aplikasi menemukan seluruh video
      ↓
Aplikasi menganalisis video
      ↓
Aplikasi menentukan bitrate
      ↓
Aplikasi menentukan resolusi
      ↓
FFmpeg melakukan encoding
      ↓
Ukuran dicek
      ↓
Jika >19 MB → retry
      ↓
Jika <=19 MB → SUCCESS
      ↓
Output disimpan dengan struktur folder asli
```

Pengguna tidak perlu melakukan konfigurasi teknis apa pun.

---

# 42. Kesimpulan

Arsitektur terbaik untuk Drone Compressor adalah **desktop-first, local processing, batch-oriented, target-size encoding**.

Teknologi inti:

```text
Python
+
PySide6
+
FFmpeg
+
FFprobe
+
SQLite
+
PyInstaller
```

Fokus teknis terpenting bukan sekadar "mengecilkan video", tetapi membuat engine yang dapat:

```text
MAXIMUM SIZE = 19 MB
        +
MAXIMUM QUALITY
        +
BATCH PROCESSING
        +
AUTOMATIC RETRY
        +
PRESERVE FOLDER STRUCTURE
```

Versi pertama sebaiknya memprioritaskan kestabilan **H.264/AAC + target-size bitrate + validator + retry**, kemudian baru menambahkan two-pass, hardware acceleration, dan adaptive encoding.

---

# 43. Next Implementation

Tahap setelah blueprint ini adalah membangun **MVP runnable** dengan seluruh komponen:

```text
app/
├── core/
├── ffmpeg/
├── models/
├── database/
├── ui/
└── utils/
```

MVP harus dapat dijalankan dengan:

```bash
python -m app.main
```

dan menghasilkan aplikasi:

```text
macOS:
DroneCompressor.app

Windows:
DroneCompressor.exe
```

Target utama MVP:

**Input folder → Batch compression → setiap video <=19 MB → output folder dengan struktur asli → progress real-time → retry otomatis.**
