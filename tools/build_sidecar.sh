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
# --onedir (NOT onefile): no ~100MB self-extraction on every launch, so the
# backend cold-starts in ~1s instead of ~4s. Bundled into the app via Tauri
# resources (see tauri.conf.json) rather than externalBin.
pyinstaller --noconfirm --clean --onedir \
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

# dist/xman-server/ holds the exe + _internal/. Copy the tree into the Tauri
# resources folder (same layout: xman-server next to _internal/).
rm -rf ui/src-tauri/sidecar
mkdir -p ui/src-tauri/sidecar
cp -R dist/xman-server/. ui/src-tauri/sidecar/
echo "sidecar (onedir) -> ui/src-tauri/sidecar/ ($(du -sh ui/src-tauri/sidecar | cut -f1))"
