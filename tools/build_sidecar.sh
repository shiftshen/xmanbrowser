#!/usr/bin/env bash
# Build the standalone backend executable ("sidecar") with PyInstaller.
# Output: dist/xman-server  → copied to ui/src-tauri/binaries/xman-server-<triple>
# so Tauri can bundle it as an externalBin. Camoufox's browser binary is NOT
# bundled; the sidecar downloads it to the user cache on first run.
set -euo pipefail
cd "$(dirname "$0")/.."

TRIPLE="${1:-$(rustc -vV | sed -n 's/host: //p')}"
echo "target triple: $TRIPLE"

rm -rf build dist
pyinstaller --noconfirm --clean --onefile \
  --name xman-server \
  --collect-all camoufox \
  --collect-all browserforge \
  --collect-all apify_fingerprint_datapoints \
  --collect-all language_tags \
  --collect-all playwright \
  --collect-all patchright \
  --collect-all uvicorn \
  --collect-submodules fastapi \
  --hidden-import xman.service \
  --hidden-import xman.cli \
  sidecar_main.py

mkdir -p ui/src-tauri/binaries
EXT=""
case "$TRIPLE" in *windows*) EXT=".exe";; esac
cp "dist/xman-server$EXT" "ui/src-tauri/binaries/xman-server-$TRIPLE$EXT"
echo "sidecar -> ui/src-tauri/binaries/xman-server-$TRIPLE$EXT"
