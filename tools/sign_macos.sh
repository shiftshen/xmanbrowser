#!/usr/bin/env bash
# Deep-sign Xbrowser.app with a Developer ID identity for notarization.
# Signs every embedded Mach-O (the PyInstaller sidecar has ~100) with hardened
# runtime + secure timestamp, gives the Python binaries the entitlements they
# need under hardened runtime, then seals the bundle. Inside-out order matters.
#
#   tools/sign_macos.sh "Developer ID Application: NAME (TEAMID)" path/to/Xbrowser.app
IDENTITY="$1"
APP="$2"
ENT="/tmp/xbrowser-entitlements.plist"
cat > "$ENT" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>com.apple.security.cs.allow-jit</key><true/>
  <key>com.apple.security.cs.allow-unsigned-executable-memory</key><true/>
  <key>com.apple.security.cs.allow-dyld-environment-variables</key><true/>
  <key>com.apple.security.cs.disable-library-validation</key><true/>
</dict></plist>
PLIST

csign() { codesign --force --timestamp --options runtime --entitlements "$ENT" --sign "$IDENTITY" "$1" 2>&1 | grep -v "replacing existing signature" || true; }

echo "[1/4] collecting every Mach-O in the bundle…"
# Build the full Mach-O list (libs, frozen exes, the sidecar, frameworks).
MACHO=$(mktemp)
find "$APP" -type f | while IFS= read -r f; do
  case "$f" in *.py|*.pyc|*.txt|*.json|*.yml|*.yaml|*.dat|*.pem|*.html|*.css|*.js) continue;; esac
  if file "$f" 2>/dev/null | grep -q "Mach-O"; then echo "$f"; fi
done > "$MACHO"
echo "    $(wc -l < "$MACHO") Mach-O files"

echo "[2/4] signing all embedded Mach-O (parallel)…"
# deepest paths first so nested code is signed before its container
sort -r "$MACHO" | xargs -P6 -I{} codesign --force --timestamp --options runtime --entitlements "$ENT" --sign "$IDENTITY" {} >/dev/null 2>&1

echo "[3/4] signing sidecar entry + main app binary…"
csign "$APP/Contents/Resources/sidecar/xman-server"
[ -f "$APP/Contents/MacOS/Xbrowser" ] && csign "$APP/Contents/MacOS/Xbrowser"

echo "[4/4] sealing the .app bundle with Developer ID…"
codesign --force --timestamp --options runtime --entitlements "$ENT" --sign "$IDENTITY" "$APP"

echo "=== verify ==="
codesign --verify --deep --strict --verbose=2 "$APP" 2>&1 | tail -2
codesign -dvv "$APP" 2>&1 | grep -E "Authority=|TeamIdentifier|flags|Runtime" | head -5
rm -f "$MACHO"
echo "SIGN_DONE"
