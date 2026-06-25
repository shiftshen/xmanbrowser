<p align="center">
  <img src="brand/logo-horizontal.png" alt="XmanBrowser — Fingerprint Protection" width="440">
</p>

<h1 align="center">XmanBrowser</h1>
<p align="center">Open-source proxy & profile browser · <sub>by <b>XmanX</b></sub></p>

XmanBrowser is a **free, open-source (MIT), local-first** fingerprint browser for macOS & Windows.
It manages multiple isolated browser *profiles* — each with its own internally
consistent fingerprint, its own proxy, and its own cookie/storage isolation —
built on top of [Camoufox](https://github.com/daijro/camoufox) (an open-source
anti-detect Firefox).

It is a free, self-hostable alternative to AdsPower / BitBrowser / GoLogin for
**legitimate** use: multi-account management, data collection, QA/automation
testing, and privacy browsing.

## Features

- **Isolated profiles** — each profile is its own browser environment: unique
  fingerprint, own proxy, own cookie/storage jar. Create, clone, edit, search,
  group, import/export. Launch/stop each independently, or all at once.
- **Two engines per profile** — **Camoufox** (Firefox, engine-level spoofing →
  *unique* WebGL/canvas/font fingerprint) or **Chromium** (real Chrome via
  patchright, automation-leak patched). Pick at creation.
- **Smart proxy handling** — paste almost any format (it auto-detects host /
  port / user / pass regardless of order or separator), bulk-import lists, keep a
  health-checked pool, or auto-fetch from a provider API / rotating gateway.
- **Geo follows the proxy** — timezone, locale/language, geolocation and WebRTC
  IP are set from the proxy's exit IP at launch, so you never leak a mismatch
  like `timezone=Asia/Bangkok` + `language=de-DE`.
- **One-click environment check** — score the current egress (0–100) from
  aggregated signals (geo + datacenter/proxy/mobile flags) and see IP · region ·
  ISP · IP type inline, per profile and across the whole proxy pool. Datacenter /
  VPN IPs are flagged so you know when an environment will trip anti-fraud.
- **Default home = whoer.net** — every profile opens to an instant
  IP/fingerprint self-check (configurable in source).
- **Hardened local API** — the control service refuses cross-origin calls from
  any webpage you visit (see [Security](#security)).
- **Local-first & free** — no account, no cloud, no telemetry. Everything lives
  under `~/.xman/`. MIT-licensed.

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
- **M5 done** — one-click environment/IP detection with a 0–100 trust score,
  per-profile and pool-wide; whoer.net default home; signed + notarized macOS and
  Windows installers via CI.
- **M6 done** — local-API hardening (custom-header + Host + CORS guard against
  malicious-webpage drive-by) following an independent security audit.

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

## Proxies

- **Types:** `http`, `https`, `socks5` (and `socks5h`). Bind one per profile, or
  manage a **pool** and pick by label; **providers** auto-fetch proxies from an
  API or a rotating gateway, and a health check auto-disables dead ones.
- **Paste any format — auto-detected:**
  `scheme://user:pass@host:port`, `host:port:user:pass`, or `host:port`
  (scheme defaults to http). Bulk-paste many, one per line.
- **Geo follows the proxy.** On launch the exit IP is looked up (several
  providers, with fallback) and the browser's **timezone, locale/language, and
  geolocation** are set to match the exit country — so you never get a tell like
  `timezone=Asia/Bangkok` with `language=de-DE`.

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

### REST API

`GET /api/health` · `GET/POST /api/profiles` · `GET/PATCH/DELETE /api/profiles/{id}` ·
`POST /api/profiles/{id}/clone|launch|stop` · `POST /api/batch/launch|stop` ·
`GET /api/running` · `POST /api/stop-all` · `GET/POST /api/proxies` ·
`GET /api/proxy/check?proxy=...` · `GET /api/detect?proxy=...` (0–100 trust score) ·
`GET/POST /api/providers` · `GET /api/export` · `POST /api/import`.
Binds to `127.0.0.1` only (local-first; not a network service).

Data lives under `~/.xman/` (override with `XMAN_HOME`):
`profiles/<id>.json` (fingerprint + proxy) and `userdata/<id>/` (isolated storage).

## Security

The control API binds to `127.0.0.1`, but any webpage you open in a normal
browser can still reach `127.0.0.1:8723`. To stop a malicious page from driving
the app, every `/api/*` call (except `/api/health`) must:

- carry the `X-XMan-Client: xman` header — a cross-origin page can't add a custom
  header without a CORS preflight, which the API denies (its CORS allowlist is
  the app's own origins, **not** `*`);
- arrive with a loopback `Host` header — defeats DNS-rebinding.

The desktop UI sends the header automatically. If you call the API yourself, add
`-H "X-XMan-Client: xman"`. Set `XMAN_API_OPEN=1` to disable the guard for trusted
local scripting/tests. Proxy credentials are currently stored locally in plaintext
SQLite under `~/.xman/` — keychain-backed storage is on the roadmap; protect that
directory accordingly.

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

## Install & first run

The macOS build is **signed + notarized** (Developer ID), so it opens with no
Gatekeeper warning — just drag `XmanBrowser.app` to Applications and launch.

The Windows build is signed with a self-generated key, so SmartScreen may warn on
first run: **More info → Run anyway**.

The first launch is a little slower (the OS scans the bundle once); after that the
local engine starts in **under a second** (PyInstaller onedir — no per-launch
extraction).

### Enabling signed + notarized releases

CI is already wired for it — add these repo secrets and the next
`Desktop build` produces signed, notarized installers (no Gatekeeper warning):

- macOS: `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`,
  `APPLE_ID`, `APPLE_PASSWORD` (app-specific), `APPLE_TEAM_ID`
- Windows: `TAURI_SIGNING_PRIVATE_KEY`, `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`

## Need proxies for XmanBrowser?

XmanBrowser supports proxy pools, rotating gateways, and isolated browser
profiles. Datacenter/VPN IPs get flagged by anti-fraud — for clean results use
residential / ISP / 4G proxies:

- **High-quality residential · 中文/支付宝:** [711Proxy](https://www.711proxy.com/signup?code=812411) — 90M+ residential IPs, anti-fraud grade
- **Budget · free tier to start:** [Webshare](https://www.webshare.io/?referral_code=a408k2bpaeid) — 10 free proxies, pay-as-you-grow, card/PayPal

_Disclosure: these are affiliate links. If you buy through them, XmanBrowser may
earn a commission to support open-source development._

## License

MIT.
