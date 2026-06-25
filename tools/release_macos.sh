#!/usr/bin/env bash
# One-shot macOS release: sidecar (+ bundled Camoufox) → tauri build → Developer
# ID sign → SIGNATURE SCAN (the gate that catches notarization failures before
# the slow upload) → DMG → notarize → staple → verify.
#
# Prereqs (one-time):
#   - Developer ID Application cert in the login keychain
#   - notarytool keychain profile (default name below), created once by the owner:
#       xcrun notarytool store-credentials xbrowser-notary \
#         --apple-id "<id>" --team-id PGJ5BY2925   (then paste the app-specific pw)
#
# Usage:  source .venv/bin/activate && bash tools/release_macos.sh
set -euo pipefail
cd "$(dirname "$0")/.."

IDENTITY="${SIGN_IDENTITY:-Developer ID Application: Chinda Lorcharoen (PGJ5BY2925)}"
PROFILE="${NOTARY_PROFILE:-xbrowser-notary}"
UPD_KEY="${TAURI_UPDATER_KEY:-$HOME/.tauri/xmanbrowser-updater.key}"
VERSION="$(python3 -c "import json;print(json.load(open('ui/src-tauri/tauri.conf.json'))['version'])")"
APP="ui/src-tauri/target/release/bundle/macos/XmanBrowser.app"
DMG="/tmp/XmanBrowser_${VERSION}_aarch64.dmg"

# tauri build signs the updater artifact it generates (createUpdaterArtifacts),
# so it needs the key in the env or it errors. We re-make + re-sign the tar.gz
# from the NOTARIZED app in step 8, so this just satisfies the build.
export TAURI_SIGNING_PRIVATE_KEY="$(cat "$UPD_KEY")"
export TAURI_SIGNING_PRIVATE_KEY_PASSWORD=""

echo "▶ releasing XmanBrowser $VERSION (arm64)"

echo "── [1/7] sidecar (+ bundled Camoufox browser)"
bash tools/build_sidecar.sh

echo "── [2/7] tauri build"
pkill -f "XmanBrowser.app/Contents/MacOS/app" 2>/dev/null || true
( cd ui && npx tauri build )

scan_unsigned() {
  find "$APP" -type f | while IFS= read -r f; do
    case "$f" in *.py|*.pyc|*.txt|*.json|*.yml|*.yaml|*.dat|*.pem|*.html|*.css|*.js|*.svg|*.png|*.ico|*.icns) continue;; esac
    if file "$f" 2>/dev/null | grep -q "Mach-O"; then
      codesign -dvv "$f" 2>&1 | grep -q "Authority=Developer ID Application" || echo "$f"
    fi
  done
}

echo "── [3+4/7] Developer ID deep-sign + scan gate (retry — Apple's timestamp server is flaky)"
UNSIGNED=""
for attempt in 1 2 3 4 5 6; do
  bash tools/sign_macos.sh "$IDENTITY" "$APP" >/dev/null 2>&1 || true
  UNSIGNED="$(scan_unsigned)"
  [ -z "$UNSIGNED" ] && { echo "  ✓ all Mach-O signed (attempt $attempt)"; break; }
  echo "  attempt $attempt: $(echo "$UNSIGNED" | grep -c . ) still unsigned (timestamp.apple.com rate-limit) — waiting then retrying"
  sleep 20
done
if [ -n "$UNSIGNED" ]; then
  echo "✗ ABORT — still unsigned after retries (notarization would fail):"
  echo "$UNSIGNED" | sed 's/^/    /'
  exit 1
fi

echo "── [5/7] build DMG"
STAGE="$(mktemp -d)/dmg"; mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"; ln -s /Applications "$STAGE/Applications"
rm -f "$DMG"
hdiutil create -volname "XmanBrowser" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
echo "  dmg: $(du -sh "$DMG" | cut -f1)"

echo "── [6/7] notarize (keychain profile: $PROFILE)"
xcrun notarytool submit "$DMG" --keychain-profile "$PROFILE" --wait

echo "── [7/8] staple + verify"
xcrun stapler staple "$DMG"
xcrun stapler staple "$APP"
spctl -a -vv "$APP" 2>&1 | grep -E "source=|accepted|rejected" || true

echo "── [8/8] auto-updater artifact (tar.gz of the NOTARIZED app + updater signature)"
UPD_KEY="${TAURI_UPDATER_KEY:-$HOME/.tauri/xmanbrowser-updater.key}"
TARGZ="/tmp/XmanBrowser_${VERSION}_aarch64.app.tar.gz"
rm -f "$TARGZ" "$TARGZ.sig"
tar czf "$TARGZ" -C "$(dirname "$APP")" "XmanBrowser.app"
npx --prefix ui tauri signer sign -f "$UPD_KEY" -p "" "$TARGZ" >/dev/null
echo "  updater: $TARGZ (+ .sig)"

echo "✅ DONE"
echo "   dmg     : $DMG"
echo "   updater : $TARGZ"
echo "   sig     : $TARGZ.sig"
