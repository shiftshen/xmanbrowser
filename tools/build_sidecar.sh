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
  --collect-all requests \
  --collect-all urllib3 \
  --collect-all platformdirs \
  --collect-all screeninfo \
  --collect-all ua_parser \
  --hidden-import typing_extensions \
  --hidden-import xman.service \
  --hidden-import xman.cli \
  sidecar_main.py

# dist/xman-server/ holds the exe + _internal/. Copy the tree into the Tauri
# resources folder (same layout: xman-server next to _internal/).
rm -rf ui/src-tauri/sidecar
mkdir -p ui/src-tauri/sidecar
cp -R dist/xman-server/. ui/src-tauri/sidecar/

# Bundle the Camoufox BROWSER (the Firefox binary + fonts/properties) so the app
# works with zero first-run download. Fetch it for THIS platform if missing,
# then copy the whole install dir to sidecar/camoufox-data/. At runtime the
# sidecar points camoufox.pkgman.INSTALL_DIR here (see sidecar_main.py).
echo "fetching + bundling the Camoufox browser…"
python -c "from camoufox.__main__ import cli; cli(['fetch'], standalone_mode=False)" || true
python - <<'PY'
import shutil
from pathlib import Path
from camoufox.pkgman import INSTALL_DIR
dst = Path("ui/src-tauri/sidecar/camoufox-data")
if dst.exists():
    shutil.rmtree(dst)
if INSTALL_DIR.exists() and any(INSTALL_DIR.iterdir()):
    shutil.copytree(INSTALL_DIR, dst)
    print(f"bundled Camoufox browser: {INSTALL_DIR} -> {dst}")
else:
    raise SystemExit(f"ERROR: Camoufox browser not found at {INSTALL_DIR}; fetch failed")
PY
echo "sidecar (onedir + Camoufox) -> ui/src-tauri/sidecar/ ($(du -sh ui/src-tauri/sidecar | cut -f1))"
