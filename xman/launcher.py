"""Launch a Camoufox instance for a profile: stable fingerprint + proxy + geoip.

Stable identity comes from the persisted `config`; geo surfaces (timezone,
locale, WebRTC IP, geolocation) are resolved at launch from the proxy exit IP
via `geoip=True`, keeping them consistent with the egress location.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .profile import Profile


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
        # Replay the baked, stable identity. Camoufox only fills *absent* keys,
        # so every launch reproduces this fingerprint byte-for-byte.
        "config": dict(spec.config),
        "os": spec.os,
        "headless": headless,
        # Per-profile isolation: own user-data-dir => own cookies/storage/cache.
        "persistent_context": True,
        "user_data_dir": str(profile.user_data_dir),
        "humanize": humanize,
        "block_webrtc": block_webrtc,
        # We intentionally replay a pinned navigator/screen/webgl config to keep
        # the per-profile identity stable. That's the whole point of a fingerprint
        # browser, so acknowledge Camoufox's "manually setting properties" warning.
        "i_know_what_im_doing": True,
    }

    proxy = profile.proxy
    if proxy:
        opts["proxy"] = proxy.to_camoufox()
        # geoip=True => timezone/locale/geolocation (and WebRTC IP if not blocked)
        # follow the proxy's exit IP. This is the consistency guarantee.
        opts["geoip"] = True

    # Keep WebGL2 flag consistent with the pinned WebGL fingerprint.
    if not spec.webgl2_enabled:
        opts.setdefault("firefox_user_prefs", {})["webgl.enable-webgl2"] = False

    return opts


def launch(profile: Profile, *, headless: bool = False, **kw):
    """Open the browser and return the Camoufox context manager.

    Usage:
        with launch(profile) as browser:
            page = browser.new_page(); page.goto("https://browserleaks.com")
    """
    from camoufox.sync_api import Camoufox

    opts = build_launch_options(profile, headless=headless, **kw)
    return Camoufox(**opts)
