# Drone Compressor

Aplikasi desktop lokal untuk kompresi batch video drone ke ukuran maksimum tertentu (default **19 MB**).

## Fitur MVP

- Scan folder recursive (MP4/MOV/M4V/MKV/AVI)
- Target size bitrate + safety margin + adaptive resolution
- H.264/AAC encoding via FFmpeg (ABR + CRF fallback)
- Auto-retry, rotation handling, audio-less support
- Preserve struktur folder
- Progress real-time + job table + resume (SQLite)
- CLI dan GUI (PySide6)
- Packaging macOS `.app` / Windows folder build

## Setup (dev)

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# FFmpeg: Homebrew ATAU static binary
brew install ffmpeg
# atau:
./scripts/link_ffmpeg.sh
# atau static (disarankan untuk packaging):
./scripts/fetch_static_ffmpeg_macos.sh
```

## Jalankan (dev)

```bash
python -m app.main
python -m app.compress /path/to/source /path/to/output --target 19
pytest -q
```

## Build macOS app

```bash
./scripts/build_macos.sh
open dist/DroneCompressor.app
```

App menyimpan config/log/DB di:
`~/Library/Application Support/DroneCompressor/`

## Build Windows

PyInstaller tidak bisa cross-compile dari macOS, jadi pilih salah satu:

### A. Via GitHub Actions (tanpa PC Windows) — disarankan

Push repo ke GitHub, lalu ambil artifact dari workflow **Build**:

- `DroneCompressor-Setup-windows` → satu file `DroneCompressor-Setup.exe`
- `DroneCompressor-windows-portable` → folder portable (tanpa install)

### B. Di mesin Windows — satu kali double-click

1. Di macOS: `./scripts/package_source.sh` → `dist/DroneCompressor-source.zip`
2. Pindahkan zip ke Windows, extract
3. **Double-click `BUILD_WINDOWS.bat`**

Bat itu otomatis install Python + Inno Setup (via winget), unduh FFmpeg,
build app, dan bungkus installer. Hasil: `dist\DroneCompressor-Setup.exe`

Manual (kalau mau kontrol penuh):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows_installer.ps1
# atau hanya folder portable:
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

### Untuk user akhir

Kirim **`DroneCompressor-Setup.exe`** saja — double-click, next, selesai.
FFmpeg sudah termasuk di dalamnya, tidak perlu install apa pun lagi.

App menyimpan config/log/DB di `%LOCALAPPDATA%\DroneCompressor\`

## Dokumentasi

- Rencana: `Drone_Compressor_Development_Plan (1).md`
- Backlog: `drone-compress-dev.md`
