#!/usr/bin/env bash
# Buat zip source untuk dibawa ke mesin Windows (untuk build installer).
# Hasil: dist/DroneCompressor-source.zip
#
# Memakai whitelist agar artefak besar (dist, .venv, ffmpeg) tidak ikut terbawa.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p dist

OUT="$ROOT/dist/DroneCompressor-source.zip"
rm -f "$OUT"

INCLUDE=(
  "app"
  "tests"
  "scripts"
  "installer"
  ".github"
  "BUILD_WINDOWS.bat"
  "run_app.py"
  "build_windows.spec"
  "build_macos.spec"
  "config.json"
  "requirements.txt"
  "pytest.ini"
  ".gitignore"
  "README.md"
  "drone-compress-dev.md"
)

# Dokumen rencana (nama mengandung spasi)
for doc in *.md; do
  case "$doc" in
    README.md|drone-compress-dev.md) ;;
    *) INCLUDE+=("$doc") ;;
  esac
done

MISSING=()
EXISTING=()
for item in "${INCLUDE[@]}"; do
  if [[ -e "$item" ]]; then
    EXISTING+=("$item")
  else
    MISSING+=("$item")
  fi
done

if ((${#MISSING[@]})); then
  echo "Lewati (tidak ada): ${MISSING[*]}"
fi

zip -r -q "$OUT" "${EXISTING[@]}" \
  -x "**/__pycache__/*" \
  -x "**/.pytest_cache/*" \
  -x "**/*.pyc" \
  -x "**/.DS_Store"

echo "OK: $OUT"
du -h "$OUT"
echo ""
echo "Isi:"
unzip -l "$OUT" | tail -3
echo ""
echo "Di mesin Windows: extract zip, lalu double-click BUILD_WINDOWS.bat"
