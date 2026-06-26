"""First-run browser-engine download with progress tracking.

Camoufox (~300MB) and Chromium (~170MB) are fetched on first use, not bundled.
Without feedback a user thinks the app is frozen, so we expose a live progress
percentage. Rather than parse each downloader's output, we watch the engine
cache directory grow toward its known approximate size — engine-agnostic and
robust. The bar caps at 99% until the real "installed" check passes.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Dict, Optional

SUPPORTED = ("camoufox", "chromium")

# Approximate fully-installed sizes (bytes), for the progress bar only.
_APPROX = {"camoufox": 380_000_000, "chromium": 520_000_000}

_status: Dict[str, dict] = {}
_lock = threading.Lock()


# ---------- locations ----------

def _camoufox_dir() -> Optional[Path]:
    try:
        from camoufox.pkgman import INSTALL_DIR
        return Path(INSTALL_DIR)
    except Exception:
        return None


def _chromium_dir() -> Path:
    from .launcher import _set_browsers_path
    _set_browsers_path()
    return Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"])


def _dir_size(path: Optional[Path]) -> int:
    if not path or not path.exists():
        return 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


# ---------- install checks ----------

def _patchright_chromium_revision() -> Optional[str]:
    """Patchright's pinned Chromium build number, read from its bundled
    browsers.json — a plain file read, no driver process."""
    try:
        import glob
        import json
        from patchright._impl._driver import compute_driver_executable
        drv = compute_driver_executable()
        drv0 = drv[0] if isinstance(drv, (list, tuple)) else drv
        pkg = os.path.dirname(os.fspath(drv0))
        for bj in glob.glob(os.path.join(pkg, "**", "browsers.json"), recursive=True):
            try:
                data = json.load(open(bj))
            except Exception:
                continue
            for b in data.get("browsers", []):
                if b.get("name") == "chromium" and b.get("revision"):
                    return str(b["revision"])
    except Exception:
        return None
    return None


def _chromium_dir_installed(d: Path) -> bool:
    """A `chromium-<rev>` dir is usable iff Playwright's own post-install marker
    is present AND a platform browser payload sits next to it. The marker is the
    canonical signal Playwright writes after a validated download; checking it
    avoids guessing the (arch- and branding-specific) executable path."""
    if not (d / "INSTALLATION_COMPLETE").exists():
        return False
    return any(d.glob("chrome-*"))


def is_installed(engine: str) -> bool:
    if engine == "camoufox":
        try:
            from camoufox.pkgman import installed_verstr
            installed_verstr()
            return True
        except Exception:
            return False
    if engine == "chromium":
        # NB: do NOT start a Playwright driver here (sync_playwright →
        # executable_path). This runs inside the API server (status poll + every
        # launch); in the PyInstaller-frozen sidecar starting the bundled Node
        # driver hangs, wedging /api/engine/status and chromium launches while
        # Camoufox stays fine. Resolve the browser from disk instead — cheap and
        # process-free.
        try:
            base = _chromium_dir()
            rev = _patchright_chromium_revision()
            if rev and _chromium_dir_installed(base / f"chromium-{rev}"):
                return True
            # Revision unknown (or pinned build absent) — accept any complete one.
            return any(_chromium_dir_installed(d) for d in base.glob("chromium-*"))
        except Exception:
            return False
    return False


# ---------- status ----------

def _set(engine: str, **kw) -> None:
    with _lock:
        cur = _status.setdefault(engine, {"state": "unknown", "percent": 0, "message": ""})
        cur.update(kw)


def status(engine: str) -> dict:
    if is_installed(engine):
        return {"engine": engine, "state": "ready", "percent": 100, "message": "ready"}
    with _lock:
        s = _status.get(engine)
        if s:
            return {"engine": engine, **s}
    return {"engine": engine, "state": "missing", "percent": 0, "message": "not installed"}


def status_all() -> dict:
    return {e: status(e) for e in SUPPORTED}


# ---------- download ----------

def _monitor(engine: str, target: Optional[Path]) -> None:
    approx = _APPROX.get(engine, 300_000_000)
    while True:
        with _lock:
            st = _status.get(engine, {}).get("state")
        if st != "downloading":
            return
        pct = min(99, int(_dir_size(target) * 100 / approx))
        _set(engine, percent=pct)
        if is_installed(engine):
            return
        time.sleep(0.5)


def _run_download(engine: str) -> None:
    target = _camoufox_dir() if engine == "camoufox" else _chromium_dir()
    threading.Thread(target=_monitor, args=(engine, target), daemon=True).start()
    try:
        if engine == "camoufox":
            from camoufox.__main__ import cli
            cli(["fetch"], standalone_mode=False)
        else:
            import subprocess
            from .launcher import _set_browsers_path
            _set_browsers_path()
            from patchright._impl._driver import compute_driver_executable, get_driver_env
            drv = compute_driver_executable()
            cmd = list(drv) if isinstance(drv, (list, tuple)) else [drv]
            subprocess.run([*cmd, "install", "chromium"],
                           env={**os.environ, **get_driver_env()}, check=False)
    except SystemExit:
        pass
    except Exception as e:  # noqa: BLE001
        _set(engine, state="error", message=str(e)[:200])
        return
    if is_installed(engine):
        _set(engine, state="ready", percent=100, message="ready")
    else:
        _set(engine, state="error", message="download finished but engine not found")


def ensure_async(engine: str) -> dict:
    """Kick off the engine download if needed; returns the current status."""
    if engine not in SUPPORTED:
        return {"engine": engine, "state": "error", "message": "unknown engine"}
    if is_installed(engine):
        return status(engine)
    with _lock:
        st = _status.get(engine, {}).get("state")
        if st == "downloading":
            return status(engine)
        _status[engine] = {"state": "downloading", "percent": 0,
                           "message": f"Downloading the {engine} engine…"}
    threading.Thread(target=_run_download, args=(engine,), daemon=True).start()
    return status(engine)
