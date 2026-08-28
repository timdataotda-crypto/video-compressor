# Drone Compressor — Development Backlog

Dokumen ini melacak status implementasi terhadap
`Drone_Compressor_Development_Plan (1).md`.

Terakhir di-update: 2026-08-28

---

## Status ringkas

| Area | Status |
|---|---|
| Phase 1 — Core Engine | ✅ Done |
| Phase 2 — GUI MVP | ✅ Done |
| Phase 3 — Batch & Folder | ✅ Done |
| Phase 4 — Advanced Encoding | ✅ Done |
| Phase 5 — Persistence | ✅ Done (MVP) |
| Phase 6 — Production UI | ⬜ Todo |
| Phase 7 — Packaging | 🟡 Partial (macOS .app OK) |

Legenda: ✅ Done · 🟡 Partial · ⬜ Todo · 🔴 Blocked

---

## Done (sudah diimplementasikan)

### Core
- [x] Project structure `app/core|ffmpeg|models|database|ui|utils`
- [x] `config.json` + load/save
- [x] Scanner recursive (mp4/mov/m4v/mkv/avi), ignore temp files
- [x] FFprobe analyzer (duration, resolution, fps, codec, size, rotation)
- [x] Bitrate calculator (target × safety_margin − audio)
- [x] Adaptive resolution (5M / 2.5M / 1.2M thresholds)
- [x] FFmpeg encoder H.264/AAC + faststart
- [x] Size validator
- [x] Retry algorithm (margin 0.96, max 4)
- [x] Folder structure preservation (resolve symlink `/tmp` → `/private/tmp`)
- [x] Skip existing outputs
- [x] Temp file cleanup
- [x] Hardware encoder detection (VideoToolbox / NVENC / QSV / libx264)
- [x] Two-pass encoding (saat quality profile balanced/maximum + libx264)
- [x] Progress parsing dari FFmpeg stderr (`time=`)
- [x] Copy cepat (`shutil.copy2`) jika file sudah ≤ target
- [x] Validasi target realistis (bitrate floor 200 kbps + saran target)
- [x] Dependency check FFmpeg/FFprobe (CLI + GUI first-run)
- [x] `scripts/link_ffmpeg.sh` → symlink ke `bin/macos/`
- [x] Rotation/orientation → transpose + scale (display-aware)
- [x] Audio-less: encode dengan `-an` (tanpa track AAC kosong)
- [x] Bitrate floor/ceiling per resolusi output
- [x] CRF hybrid fallback setelah ABR retries habis
- [x] Strip metadata `rotate=0` setelah transpose

### Persistence
- [x] SQLite job table + status lifecycle
- [x] Resume prompt saat ada job incomplete
- [x] Job update real-time ke DB
- [x] Crash-safe: reset ANALYZING/COMPRESSING/VALIDATING → PENDING saat startup
- [x] Retry Failed button di GUI
- [x] Resume path inference via common ancestor folder

### CLI / GUI
- [x] CLI: `python -m app.compress /source /output`
- [x] GUI: `python -m app.main`
- [x] Source / output picker
- [x] Target size control
- [x] Options: recursive, preserve, skip, auto-retry
- [x] Progress bar + current job stats
- [x] Job table
- [x] Settings dialog
- [x] Drag & drop folder/file
- [x] Disk space warning
- [x] Target realism warning sebelum batch
- [x] Cancel batch (semua worker aktif)
- [x] Pause / Resume queue
- [x] Retry Failed
- [x] Blok Start jika FFmpeg hilang + pesan instalasi

### Quality / Ops
- [x] Unit tests + integration + engine edge (34 passed)
- [x] Smoke test CLI encode
- [x] Logging ke `logs/app.log`, `jobs.log`, `errors.log`
- [x] Local-first (tidak ada upload)
- [x] Preset target di main window: 5 / 10 / 15 / 19 / 25 / 50 MB / Custom
- [x] Quality profiles UI: Fast / Balanced / Maximum Quality

---

## Backlog aktif

### P0 — Selesai untuk MVP stabil

- [x] Detect FFmpeg + first-run UX
- [x] Integration test sample video
- [x] Validasi target tidak realistis
- [x] Resume path inference (common ancestor)
- [x] Link script FFmpeg ke `bin/macos`
- [ ] Bundle **static** FFmpeg (bukan symlink) untuk distribusi offline — deferred ke packaging

### P1 — Advanced Encoding — selesai

- [x] Preset target cepat di main window: 5 / 10 / 15 / 19 / 25 / 50 MB / Custom
- [x] Quality profiles UI: Fast / Balanced / Maximum
- [x] CRF hybrid mode sebagai fallback jika ABR gagal konsisten
- [x] Audio-less input handling lebih bersih
- [x] Rotation/orientation handling di filter scale
- [x] Bitrate floor / ceiling per resolusi
- [ ] Codec auto-detect input + opsi HEVC output (opsional — nice-to-have)
- [ ] Benchmark HW vs CPU pada first run (nice-to-have)

### P2 — Persistence lanjutan

- [ ] Job history browser (filter by date/status)
- [ ] Multi-batch sessions (bukan satu DB flat)
- [ ] Export job history CSV/JSON

### P3 — Phase 6 / Production UI

- [ ] Dark/light theme toggle
- [ ] Notifications OS saat batch selesai
- [ ] Keyboard shortcuts
- [ ] Polished empty states & onboarding
- [ ] Per-file detail drawer
- [ ] Localization (EN / ID)
- [ ] About / version dialog

### P4 — Phase 7 / Packaging

- [x] `build_macos.spec` + `DroneCompressor.app`
- [x] Static FFmpeg fetch script (`scripts/fetch_static_ffmpeg_macos.sh`)
- [x] Build script `scripts/build_macos.sh`
- [x] Frozen-aware paths (Application Support untuk config/logs/DB)
- [x] `build_windows.spec` + `scripts/build_windows.ps1`
- [x] `scripts/fetch_static_ffmpeg_windows.ps1`
- [x] CI GitHub Actions: test + build macOS & Windows artifact
- [x] Inno Setup installer satu file (`DroneCompressor-Setup.exe`)
- [x] `scripts/build_windows_installer.ps1` (build + bungkus installer)
- [x] `BUILD_WINDOWS.bat` — one-click build di Windows (auto-install Python/Inno)
- [x] `scripts/package_source.sh` — zip source untuk dibawa ke Windows
- [x] `%LOCALAPPDATA%\DroneCompressor` untuk config/logs/DB di Windows
- [ ] Code signing (macOS + Windows)
- [ ] Notarization / DMG + MSI installer
- [ ] Uji `.exe` di Windows nyata

### P5 — Future features

- [ ] Smart compression (motion / scene complexity)
- [ ] Contact sheet / compression report
- [ ] Export report HTML/PDF
- [ ] Linux desktop support

---

## Known issues / risks

1. **FFmpeg di `bin/macos` masih symlink** ke Homebrew — cocok untuk dev, belum portable untuk distribusi.
2. **Pause** menjeda antrian, bukan FFmpeg mid-frame.
3. **Two-pass** lebih lambat; profile `fast` memakai 1-pass.

---

## Cara menjalankan (dev)

```bash
cd /Users/mac/myprojects/video-compressor
source .venv/bin/activate
./scripts/link_ffmpeg.sh   # sekali, jika perlu

python -m app.main
python -m app.compress /path/to/DRONE /path/to/OUT --target 19
pytest -q
```

---

## Urutan kerja berikutnya

1. Uji `.app` dengan footage drone nyata  
2. Job history / export report  
3. Production UI polish (shortcuts, notifications)  
4. Code signing + DMG  

> **Engine:** tuntas · **macOS packaging:** `dist/DroneCompressor.app` (~818 MB termasuk FFmpeg static)

---

## Definition of Done (MVP)

- [x] Semua kriteria plan §31 (kecuali verifikasi footage drone nyata)
- [ ] Diverifikasi manual dengan footage drone nyata (pending user test)
