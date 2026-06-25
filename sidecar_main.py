"""PyInstaller entry point for the bundled backend ("sidecar").

Frozen into a standalone executable so the desktop app ships without a Python
install. On first run it ensures the Camoufox browser engine is downloaded
(kept in the user cache, not bundled — that keeps the installer small), then
serves the control API exactly like `xman serve`.
"""
from __future__ import annotations

import os
import sys


def _ensure_engine() -> None:
    """Download the Camoufox browser on first run if it isn't cached yet."""
    try:
        from camoufox.pkgman import installed_verstr
        installed_verstr()  # raises if not installed
        return
    except Exception:
        pass
    try:
        print("[xman] downloading browser engine (one-time)…", flush=True)
        # Invoke Camoufox's own `fetch` CLI in-process (downloads browser + geoip
        # + addons). Works in a frozen build where `python -m camoufox` can't run.
        from camoufox.__main__ import cli as camoufox_cli
        camoufox_cli(["fetch"], standalone_mode=False)
        print("[xman] engine ready.", flush=True)
    except SystemExit:
        pass
    except Exception as e:  # noqa: BLE001
        print(f"[xman] engine fetch failed: {e}", flush=True)


def main() -> None:
    # Frozen exes can't do `python -m xman.runner`, so the manager re-invokes
    # THIS executable with a "runner" subcommand to open a profile's browser.
    if len(sys.argv) > 1 and sys.argv[1] == "runner":
        from xman.runner import main as runner_main
        sys.argv = ["xman-runner", *sys.argv[2:]]
        raise SystemExit(runner_main())

    host = os.environ.get("XMAN_HOST", "127.0.0.1")
    port = int(os.environ.get("XMAN_PORT", "8723"))
    # Engines are downloaded on demand (per profile engine) with progress shown
    # in the UI — see xman/engine.py — so startup is instant and we never force a
    # 340MB Camoufox download on a user who only uses Chromium.
    import uvicorn
    from xman.service import app
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
