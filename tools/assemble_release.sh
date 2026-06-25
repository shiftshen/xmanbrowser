#!/usr/bin/env bash
# Publish a XmanBrowser GitHub release WITH the auto-update manifest (latest.json).
# Run AFTER release_macos.sh (mac, local) and the Windows CI build have finished.
#
#   bash tools/assemble_release.sh <version> <windows-ci-run-id> "<release notes>"
set -euo pipefail
cd "$(dirname "$0")/.."
VER="$1"; CI_RUN="$2"; NOTES="${3:-XmanBrowser v$1}"
REPO="shiftshen/xmanbrowser"
BASE="https://github.com/$REPO/releases/download/v$VER"

DMG="/tmp/XmanBrowser_${VER}_aarch64.dmg"
TARGZ="/tmp/XmanBrowser_${VER}_aarch64.app.tar.gz"
[ -f "$TARGZ.sig" ] || { echo "missing $TARGZ.sig — run release_macos.sh first"; exit 1; }

echo "── download Windows artifacts from CI run $CI_RUN"
WIN=/tmp/winrel; rm -rf "$WIN"; mkdir -p "$WIN"
gh run download "$CI_RUN" -R "$REPO" -n xman-x86_64-pc-windows-msvc -D "$WIN"
WIN_EXE="$(find "$WIN" -name '*-setup.exe' | head -1)"
WIN_SIG_FILE="$(find "$WIN" -name '*-setup.exe.sig' | head -1)"
[ -n "$WIN_EXE" ] && [ -n "$WIN_SIG_FILE" ] || { echo "Windows exe/.sig not found in CI artifact"; exit 1; }

echo "── build latest.json"
VER="$VER" BASE="$BASE" NOTES="$NOTES" \
MAC_TARGZ="$(basename "$TARGZ")" MAC_SIG_FILE="$TARGZ.sig" \
WIN_NAME="$(basename "$WIN_EXE")" WIN_SIG_FILE="$WIN_SIG_FILE" \
python3 - <<'PY' > /tmp/latest.json
import json, os
out = {
  "version": os.environ["VER"],
  "notes": os.environ["NOTES"],
  "pub_date": __import__("datetime").datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
  "platforms": {
    "darwin-aarch64": {
      "signature": open(os.environ["MAC_SIG_FILE"]).read().strip(),
      "url": f'{os.environ["BASE"]}/{os.environ["MAC_TARGZ"]}',
    },
    "windows-x86_64": {
      "signature": open(os.environ["WIN_SIG_FILE"]).read().strip(),
      "url": f'{os.environ["BASE"]}/{os.environ["WIN_NAME"]}',
    },
  },
}
print(json.dumps(out, indent=2))
PY
echo "  latest.json:"; cat /tmp/latest.json

echo "── create GitHub release v$VER"
gh release create "v$VER" \
  "$DMG" "$TARGZ" "$TARGZ.sig" \
  "$WIN_EXE" "$WIN_SIG_FILE" \
  /tmp/latest.json \
  -R "$REPO" --title "XmanBrowser v$VER" --notes "$NOTES" --latest
echo "✅ released v$VER (with auto-update manifest)"
