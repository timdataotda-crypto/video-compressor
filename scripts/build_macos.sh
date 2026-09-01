#!/usr/bin/env bash
# Build DroneCompressor.app with PyInstaller
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  echo "Create venv first: python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate

pip install -q "pyinstaller>=6.0"

FFMPEG="$ROOT/bin/macos/ffmpeg"
if [[ ! -e "$FFMPEG" ]] || [[ -L "$FFMPEG" ]]; then
  echo "FFmpeg di bin/macos belum static. Mengunduh…"
  bash "$ROOT/scripts/fetch_static_ffmpeg_macos.sh"
fi

echo "Building DroneCompressor.app…"
rm -rf build dist
pyinstaller --noconfirm build_macos.spec

APP="$ROOT/dist/DroneCompressor.app"
if [[ -d "$APP" ]]; then
  codesign --force --deep --sign - "$APP" || true
  xattr -cr "$APP" || true
  echo ""
  echo "OK: $APP"
  file "$APP/Contents/MacOS/DroneCompressor"
  echo "Jalankan: open \"$APP\""
else
  echo "Build gagal — app tidak ditemukan"
  exit 1
fi
