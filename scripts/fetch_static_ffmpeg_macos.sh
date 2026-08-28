#!/usr/bin/env bash
# Download static ffmpeg/ffprobe for macOS into bin/macos (replaces symlinks).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/bin/macos"
TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

mkdir -p "$DEST"
echo "Downloading static ffmpeg/ffprobe (evermeet.cx)…"

curl -fsSL "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip" -o "$TMP/ffmpeg.zip"
curl -fsSL "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip" -o "$TMP/ffprobe.zip"

unzip -qo "$TMP/ffmpeg.zip" -d "$TMP"
unzip -qo "$TMP/ffprobe.zip" -d "$TMP"

# Remove old symlinks/files
rm -f "$DEST/ffmpeg" "$DEST/ffprobe"
cp "$TMP/ffmpeg" "$DEST/ffmpeg"
cp "$TMP/ffprobe" "$DEST/ffprobe"
chmod +x "$DEST/ffmpeg" "$DEST/ffprobe"

echo "Installed:"
ls -lh "$DEST/ffmpeg" "$DEST/ffprobe"
"$DEST/ffmpeg" -version | head -1
