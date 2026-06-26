"""Launch a browser for a profile — Camoufox (Firefox) or Chromium (patchright).

Both paths give per-profile isolation (own user-data-dir), proxy binding, and
geo that follows the proxy exit IP. They return an object usable as
`with launch(profile) as ctx:` where `ctx` exposes `new_page()` / `pages`.

- camoufox: engine-level fingerprint spoofing (the persisted Camoufox config).
- chromium: real Chrome via patchright (automation-leak-patched); identity set
  through Playwright context options (UA/locale/viewport/timezone) — no
  detectable JS overrides. Best when a site demands a Chrome fingerprint.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, Optional

from .profile import Profile


def _safe_geo(proxy):
    """Resolve a proxy's exit geo, or None if it can't be reached."""
    try:
        from .proxy import check_and_locate
        return check_and_locate(proxy)
    except Exception:
        return None


# ----------------------------- Camoufox -----------------------------

def build_launch_options(
    profile: Profile,
    *,
    headless: bool = False,
    humanize: bool = True,
    block_webrtc: bool = True,
) -> Dict[str, Any]:
    """Assemble the kwargs passed to Camoufox for this profile."""
    spec = profile.fingerprint
    opts: Dict[str, Any] = {
        "config": dict(spec.config),
        "os": spec.os,
        "headless": headless,
        "persistent_context": True,
        "user_data_dir": str(profile.ensure_user_data_dir()),
        "humanize": humanize,
        "block_webrtc": block_webrtc,
        "i_know_what_im_doing": True,
    }
    proxy = profile.proxy
    if proxy:
        opts["proxy"] = proxy.to_camoufox()
        # Resolve the exit geo once so timezone AND language stay consistent.
        # Pass the exact IP to Camoufox (it derives tz/geolocation/WebRTC IP) and
        # pin a country-appropriate locale ourselves — Camoufox's auto locale can
        # pick odd values (e.g. bar-DE for a Thai exit).
        geo = _safe_geo(proxy)
        if geo and geo.ip:
            from .proxy import locale_for_country
            opts["geoip"] = geo.ip
            opts["locale"] = locale_for_country(geo.country_code)
        else:
            opts["geoip"] = True
    if not spec.webgl2_enabled:
        opts.setdefault("firefox_user_prefs", {})["webgl.enable-webgl2"] = False
    return opts


def _launch_camoufox(profile: Profile, *, headless: bool, **kw):
    from camoufox.sync_api import Camoufox

    opts = build_launch_options(profile, headless=headless, **kw)
    return Camoufox(**opts)


# ----------------------------- Chromium (patchright) -----------------------------

def _set_browsers_path() -> None:
    """Point patchright at the shared user browser cache.

    A PyInstaller-frozen build otherwise looks for browsers inside its temp
    extraction dir (empty); the standard ms-playwright user cache is where dev
    installs land and where we download to on first run.
    """
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        path = os.path.join(home, "Library", "Caches", "ms-playwright")
    elif os.name == "nt":
        path = os.path.join(os.environ.get("LOCALAPPDATA", home), "ms-playwright")
    else:
        path = os.path.join(home, ".cache", "ms-playwright")
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = path


def _ensure_chromium() -> None:
    """Download the patchright Chromium browser on first use if it's missing."""
    _set_browsers_path()
    # Cheap, process-free disk check (no sync_playwright / Node driver). The
    # driver probe is what hangs the frozen sidecar, so avoid it on the hot path.
    try:
        from . import engine
        if engine.is_installed("chromium"):
            return
    except Exception:
        pass
    try:
        print("[xman] downloading Chromium engine (one-time)…", flush=True)
        # Run patchright's bundled Node driver directly — `python -m patchright`
        # doesn't exist inside a PyInstaller-frozen exe.
        import subprocess
        from patchright._impl._driver import compute_driver_executable, get_driver_env
        drv = compute_driver_executable()
        cmd = list(drv) if isinstance(drv, (list, tuple)) else [drv]
        subprocess.run([*cmd, "install", "chromium"],
                       env={**os.environ, **get_driver_env()}, check=False)
        print("[xman] chromium ready.", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[xman] chromium fetch failed: {e}", flush=True)


class _ChromiumContext:
    """Context-manager wrapper so the runner can `with launch(...) as ctx:`.

    Mirrors the Camoufox persistent-context interface (new_page / pages) and
    tears down both the browser context and the Playwright driver on exit.
    """

    def __init__(self, profile: Profile, headless: bool):
        self._profile = profile
        self._headless = headless
        self._pw = None
        self._ctx = None

    def __enter__(self):
        _ensure_chromium()
        from patchright.sync_api import sync_playwright

        prof = self._profile
        c = prof.fingerprint.config
        sw, sh = (c.get("screen") or [1280, 800])
        vw, vh = (c.get("viewport") or [sw, sh])

        kw: Dict[str, Any] = {
            "user_data_dir": str(prof.ensure_user_data_dir()),
            "headless": self._headless,
            "user_agent": c.get("userAgent"),
            "locale": c.get("language") or "en-US",
            "viewport": {"width": int(vw), "height": int(vh)},
            "screen": {"width": int(sw), "height": int(sh)},
            "color_scheme": c.get("colorScheme") or "light",
            "ignore_default_args": ["--enable-automation"],
        }

        proxy = prof.proxy
        if proxy:
            kw["proxy"] = proxy.to_camoufox()
            # Geo follows the proxy exit IP (timezone + locale + geolocation).
            geo = _safe_geo(proxy)
            if geo:
                from .proxy import locale_for_country
                if geo.timezone:
                    kw["timezone_id"] = geo.timezone
                kw["locale"] = locale_for_country(geo.country_code)
                if geo.latitude is not None and geo.longitude is not None:
                    kw["geolocation"] = {"latitude": geo.latitude, "longitude": geo.longitude}
                    kw["permissions"] = ["geolocation"]

        self._pw = sync_playwright().start()
        self._ctx = self._pw.chromium.launch_persistent_context(**kw)
        return self._ctx

    def __exit__(self, *exc):
        try:
            if self._ctx:
                self._ctx.close()
        finally:
            if self._pw:
                self._pw.stop()
        return False


# ----------------------------- dispatch -----------------------------

def launch(profile: Profile, *, headless: bool = False, **kw):
    """Open the browser for `profile`, dispatching on its engine.

        with launch(profile) as ctx:
            page = ctx.new_page(); page.goto("https://browserleaks.com")
    """
    if profile.fingerprint.engine == "chromium":
        return _ChromiumContext(profile, headless)
    return _launch_camoufox(profile, headless=headless, **kw)
