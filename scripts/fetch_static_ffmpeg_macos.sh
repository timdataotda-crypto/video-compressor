#!/usr/bin/env bash
# Download static ffmpeg/ffprobe for macOS into bin/macos (replaces symlinks).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/bin/macos"
TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

# evermeet.cx stopped serving downloads (HTTP 410); these are copies of its
# 9.0.1 static builds (x86_64, minos 10.13; Apple Silicon runs them via Rosetta).
BASE_URL="https://github.com/timdataotda-crypto/video-compressor/releases/download/ffmpeg-macos-9.0.1"
FFMPEG_SHA256="e27de05e3a9f9c758f9766d15d1a069fddeed5f725e35d9ab28683be4740dad7"
FFPROBE_SHA256="a1508faa028bfb8e20c9d182c3d41fcff29ee7584ae21b2d6c357472a3ecbc24"

mkdir -p "$DEST"
echo "Downloading static ffmpeg/ffprobe 9.0.1…"

curl -fsSL "$BASE_URL/ffmpeg-9.0.1-macos-x86_64.zip" -o "$TMP/ffmpeg.zip"
curl -fsSL "$BASE_URL/ffprobe-9.0.1-macos-x86_64.zip" -o "$TMP/ffprobe.zip"

unzip -qo "$TMP/ffmpeg.zip" -d "$TMP"
unzip -qo "$TMP/ffprobe.zip" -d "$TMP"

echo "$FFMPEG_SHA256  $TMP/ffmpeg" | shasum -a 256 -c -
echo "$FFPROBE_SHA256  $TMP/ffprobe" | shasum -a 256 -c -

# Remove old symlinks/files
rm -f "$DEST/ffmpeg" "$DEST/ffprobe"
cp "$TMP/ffmpeg" "$DEST/ffmpeg"
cp "$TMP/ffprobe" "$DEST/ffprobe"
chmod +x "$DEST/ffmpeg" "$DEST/ffprobe"

echo "Installed:"
ls -lh "$DEST/ffmpeg" "$DEST/ffprobe"
"$DEST/ffmpeg" -version | head -1
