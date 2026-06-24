# Contributing to XMan

Thanks for your interest! XMan is a free, open-source (MIT) fingerprint browser
for **legitimate** use — multi-account management, data collection, QA, and
privacy browsing.

## Scope & boundaries (please read first)

XMan provides **environment isolation + fingerprint consistency + proxy binding**
only. We do **not** accept contributions for:

- bulk auto-registration of accounts,
- payment / checkout automation,
- fake identity generation,
- bypassing paywalls, anti-fraud, or risk-control systems.

PRs in that direction will be declined regardless of code quality.

## Project layout

```
app/
  xman/           Python package (fingerprint, proxy, store, service, runner)
  tests/          pytest (no browser launch — fast)
  tools/          verify_stability.py, capture_browserleaks.py, patch script
  ui/             React + Vite frontend
  ui/src-tauri/   Tauri desktop shell (Rust)
```

## Dev setup

```bash
cd app
uv venv --python 3.12 .venv && source .venv/bin/activate
uv pip install -e . pytest
python -m camoufox fetch
python tools/patch_playwright_pageerror.py   # one-time driver fix

# UI
cd ui && npm install

# run everything as a desktop app (auto-starts the backend)
npm run tauri dev          # or: cargo tauri dev
# or run pieces separately:
#   xman serve             # backend on 127.0.0.1:8723
#   npm run dev            # UI on 127.0.0.1:5191
```

## Tests

```bash
python -m pytest                       # unit + API (fast, no browser)
python tools/verify_stability.py       # real-browser fingerprint stability proof
```

Please keep `pytest` green and add tests for new store/API behavior. UI changes
should `npm run build` cleanly (typecheck included).

## Commit style

Small, focused commits. Describe the *why*. Match the surrounding code style.
