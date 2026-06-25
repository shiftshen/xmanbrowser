---
name: release-xmanbrowser
description: Build, sign, notarize and publish a XmanBrowser desktop release (macOS + Windows). Use whenever packaging/shipping the app — it encodes the exact steps and the bugs that broke past builds.
---

# Releasing XmanBrowser

A release = a notarized macOS `.dmg` + a Windows `.exe`, attached to a GitHub Release.
**Gate: a codex review must pass before packaging** (owner rule — see `xmanbrowser-release-process` memory).

## Steps

1. **Code-complete + push.** `git push`, ensure `python -m pytest` (47+), `npm run build`, `cargo check` all green.
2. **codex review** (company-kernel `dispatch_task` to codex). Wait for `STATUS: pass`. Fix findings, repeat.
3. **Bump version** in `ui/src-tauri/tauri.conf.json` if shipping a new version.
4. **macOS** — run the one-shot script (does sidecar→build→sign→**scan gate**→dmg→notarize→staple→verify):
   ```bash
   source .venv/bin/activate
   bash tools/release_macos.sh        # → /tmp/XmanBrowser_<ver>_aarch64.dmg
   ```
   Local-only `Developer ID` cert + `xbrowser-notary` keychain profile required (owner sets the profile up once with `xcrun notarytool store-credentials`; never type the app-specific password yourself).
5. **Windows** — via CI (no Windows box locally):
   ```bash
   gh workflow run desktop-build.yml -R shiftshen/xmanbrowser
   gh run watch <id> --exit-status
   gh run download <id> -n xman-x86_64-pc-windows-msvc -D /tmp/win
   ```
6. **Publish:**
   ```bash
   gh release create v<ver> /tmp/XmanBrowser_<ver>_aarch64.dmg \
     /tmp/win/nsis/XmanBrowser_<ver>_x64-setup.exe \
     -R shiftshen/xmanbrowser --title "XmanBrowser v<ver>" --notes "…" --latest
   ```

## Hard-won gotchas (every one of these broke a build)

| Symptom | Cause | Fix |
|---|---|---|
| Camoufox "DefaultAddons" / "version.json not found" on launch | PyInstaller missed `camoufox.pkgman`'s lazy deps | `build_sidecar.sh` `--collect-all requests urllib3 platformdirs screeninfo ua_parser` + `--hidden-import typing_extensions` |
| First-run **profile create** crashes ("run camoufox fetch") | `fingerprint.py` read `installed_verstr()` before engine present | fall back to a default FF version on failure |
| Want **zero first-run download** | browser not bundled | `build_sidecar.sh` copies the fetched browser to `sidecar/camoufox-data/`; `sidecar_main._use_bundled_camoufox()` points `pkgman.INSTALL_DIR` there |
| Notarization **Invalid**: nested `.app` main exe adhoc | `codesign` refuses to sign a bundle's main exe standalone | `sign_macos.sh` skips the 3 nested `Camoufox/plugin-container/media-plugin-helper` main exes in the per-file pass and signs those `.app`s with `--deep` |
| Notarization **Invalid**: `gmp-clearkey/*.dylib` adhoc | `--deep` doesn't recurse into arbitrary `Resources/` subdirs | per-file pass signs **all** loose Mach-O (don't exclude camoufox-data) |
| Notarization keeps failing on a different binary each round | finding them one-by-one via the slow upload | **`release_macos.sh` step 4 scans every Mach-O for a Developer ID signature and aborts before upload** — fix locally, then notarize |
| Windows build fails at `light.exe` (WiX/MSI) | MSI can't handle the ~600MB bundled payload | `tauri.conf` `targets: ["nsis","app","dmg"]` (drop msi) |
| Windows CI smoke test fails (403) | the local-API guard rejects unheadered `/api/*` | smoke step sets `XMAN_API_OPEN=1` |
| Black `cmd` window / launch `0xc0000142` on Windows | console-subsystem sidecar; runner child had no cwd | `lib.rs hidden_command()` (CREATE_NO_WINDOW) + `manager.py` sets `cwd=exe dir` + CREATE_NO_WINDOW for the frozen runner |
| Export file won't re-import | webview blob `<a download>` is unreliable | native `dlgSave/dlgOpen` + Rust `save_text/read_text`; success only after write |
| Affiliate/external links don't open | webview `<a target=_blank>` does nothing | `tauri-plugin-opener` `openUrl()` |
| Delete / New group do nothing in the app | WKWebView ignores `window.confirm/prompt` | in-app React modals |
| Two app icons in Launchpad | `/Applications` copy + the build-dir `.app` both registered | keep one in `/Applications`, remove the build-dir copy, `lsregister -kill -r -domain local -domain user` |

## Verify before declaring done
- `spctl -a -vv <app>` → `source=Notarized Developer ID`, `accepted`.
- Launch the installed app, confirm `/api/health` responds (with `X-XMan-Client: xman`).
- macOS is arm64-only locally; Intel-mac needs CI signing secrets (not configured).
