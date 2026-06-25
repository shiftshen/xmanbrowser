# Xbrowser — open-source fingerprint browser

<sub>powered by **xmanx**</sub>

Xbrowser is a **free, open-source (MIT), local-first** fingerprint browser for macOS & Windows.
It manages multiple isolated browser *profiles* — each with its own internally
consistent fingerprint, its own proxy, and its own cookie/storage isolation —
built on top of [Camoufox](https://github.com/daijro/camoufox) (an open-source
anti-detect Firefox).

It is a free, self-hostable alternative to AdsPower / BitBrowser / GoLogin for
**legitimate** use: multi-account management, data collection, QA/automation
testing, and privacy browsing.

## Legal boundary

XMan only provides **environment isolation + fingerprint consistency + proxy
binding**. It deliberately does **not** include — and will not accept
contributions for — bulk auto-registration, payment/checkout automation, fake
identity generation, or fraud/anti-risk-control bypass tooling. Intended users
are crawler/data engineers, QA, privacy users, and compliant multi-account
operators. Use it only where you are authorized to.

## Status

- **M1 done** — fingerprint generation + proxy binding + isolated user-data-dir,
  runnable CLI, verified against browserleaks (stable per-profile fingerprint,
  no WebRTC leak, no automation tells).
- **M2 done** — SQLite profile store (CRUD, clone, search, import/export) +
  FastAPI local control service + per-profile background launch/stop with process
  tracking.
- **M3 done** — React + Vite desktop UI (profile grid, create/edit, one-click
  launch/stop, live proxy test, fingerprint detail, import/export) wrapped in a
  Tauri shell that auto-starts the backend.
- **M4 done** — geoip auto-consistency (timezone/locale/WebRTC IP follow the proxy
  exit at launch), import/export, and a packaged macOS `.dmg`.

## Desktop app

```bash
cd app/ui
npm install
npm run tauri dev          # dev: opens the window, auto-starts the backend
npm run tauri build        # produces a .dmg under src-tauri/target/release/bundle/dmg/
```

The Tauri shell launches the Python control service on startup and stops it on
exit. The UI (port 5191) talks to the API (port 8723) — both bound to localhost.

## Engines

XMan supports two browser engines per profile (pick one at creation):

| Engine | Based on | Stealth | Per-profile fingerprint | Use when |
|--------|----------|---------|--------------------------|----------|
| **Camoufox** (default) | Firefox | engine-level (C++) spoofing of WebGL/canvas/fonts/navigator | **unique** synthetic fingerprint, stable per profile | you need each profile to look like a *different device* |
| **Chromium** | real Chrome via [patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright) | automation-leak patched (`navigator.webdriver` hidden, no CDP tells) | UA / locale / viewport / timezone differ; **deep hardware fingerprint (cores, GPU, canvas) is the real machine's, shared across Chromium profiles** | a site demands a real Chrome and you mainly need isolation + clean automation |

Both engines get their own user-data-dir (cookie/storage isolation), proxy
binding, and timezone/locale that follow the proxy exit IP.

> Honest limitation: Playwright/patchright can't change `hardwareConcurrency`,
> `deviceMemory`, or the GPU/canvas fingerprint without detectable JS overrides,
> so Chromium profiles on the same machine share those. For *unique* fingerprints
> use Camoufox; use Chromium when Chrome-ness and bot-check evasion matter more.

## How it works

- **Fingerprint identity is generated once and persisted.** Camoufox's config
  merge only fills *absent* keys, so replaying a profile's saved config makes the
  fingerprint byte-stable across launches — the same identity every time.
- **Geo follows the proxy.** Timezone, locale, geolocation, and WebRTC IP are
  resolved at launch from the proxy's exit IP via Camoufox `geoip=True`, so they
  always stay consistent with the egress location.
- **Isolation per profile.** Each profile gets its own `user-data-dir`, so
  cookies / localStorage / cache never cross-contaminate.

## Install (dev)

```bash
cd app
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e .
python -m camoufox fetch      # one-time: download the Camoufox browser + GeoIP
```

## Usage

```bash
# create a profile (optionally bind a proxy)
xman create work --os macos --proxy socks5://user:pass@host:1080

# inspect
xman list
xman show work

# check a proxy's exit IP + geo
xman check-proxy socks5://user:pass@host:1080

# launch the browser (fingerprint + proxy + geoip)
xman launch work --url https://browserleaks.com/webgl
xman launch work --bg          # managed background process
xman running                   # list running instances
xman stop work

# clone / edit / import / export
xman clone work work2
xman edit work --proxy http://host:8080 --note "EU acct"
xman export --out backup.json
xman import backup.json

# local control API for the UI (http://127.0.0.1:8723, docs at /docs)
xman serve
```

### REST API (M2)

`GET /api/health` · `GET/POST /api/profiles` · `GET/PATCH/DELETE /api/profiles/{id}` ·
`POST /api/profiles/{id}/clone|launch|stop` · `GET /api/running` · `POST /api/stop-all` ·
`GET /api/proxy/check?proxy=...` · `GET /api/export` · `POST /api/import`. Binds to
`127.0.0.1` only (local-first; not a network service).

Data lives under `~/.xman/` (override with `XMAN_HOME`):
`profiles/<id>.json` (fingerprint + proxy) and `userdata/<id>/` (isolated storage).

## Verifying

```bash
python -m pytest               # unit tests (parsing, determinism, isolation)
python tools/verify_stability.py work   # launch twice, prove the fingerprint is stable
```

Recommended detection sites for manual acceptance: browserleaks.com
(webgl/canvas/fonts/webrtc/timezone), creepjs, pixelscan.net, iphey.com,
amiunique.org. Checks: same profile → stable fingerprint across launches;
different profiles → different fingerprints; proxy IP matches timezone/locale;
no WebRTC real-IP leak; no CDP/automation tells.

## Install & first run (unsigned build)

The public builds are **not yet notarized** (that needs a paid Apple Developer
account). macOS Gatekeeper will warn on first open:

- **macOS:** right-click `Xbrowser.app` → **Open** → **Open** (only needed once),
  or run `xattr -dr com.apple.quarantine /Applications/Xbrowser.app`.
- **Windows:** SmartScreen → **More info** → **Run anyway**.

The first launch is a little slower (the OS scans the bundle once); after that the
local engine starts in **under a second** (PyInstaller onedir — no per-launch
extraction).

### Enabling signed + notarized releases

CI is already wired for it — add these repo secrets and the next
`Desktop build` produces signed, notarized installers (no Gatekeeper warning):

- macOS: `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`,
  `APPLE_ID`, `APPLE_PASSWORD` (app-specific), `APPLE_TEAM_ID`
- Windows: `TAURI_SIGNING_PRIVATE_KEY`, `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`

## License

MIT.
