#!/usr/bin/env bash
# Link system ffmpeg/ffprobe into bin/ so the app prefers bundled paths.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OS="$(uname -s)"
case "$OS" in
  Darwin) DEST="$ROOT/bin/macos" ;;
  Linux) DEST="$ROOT/bin/linux" ;;
  *) echo "Unsupported OS: $OS"; exit 1 ;;
esac
mkdir -p "$DEST"
for name in ffmpeg ffprobe; do
  src="$(command -v "$name" || true)"
  if [[ -z "$src" ]]; then
    echo "ERROR: $name not found in PATH. Install with: brew install ffmpeg"
    exit 1
  fi
  ln -sfn "$src" "$DEST/$name"
  echo "linked $DEST/$name -> $src"
done
echo "Done."
