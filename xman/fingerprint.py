"""Internally-consistent fingerprint generation for XMan profiles.

Design: a profile's *identity* (UA, platform, screen, hardware, WebGL, canvas/
font noise seeds) is generated **once** at profile creation and persisted as a
Camoufox `config` dict. Because Camoufox's `set_into`/`merge_into` only fill keys
that are *absent*, replaying the persisted config on every launch makes the
fingerprint byte-stable across runs — exactly the AdsPower/BitBrowser model.

Geo-dependent surfaces (timezone, locale, WebRTC IP, geolocation) are deliberately
*not* baked in. They are resolved at launch time from the proxy's exit IP via
Camoufox `geoip=True`, so they always stay consistent with the egress location.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from browserforge.fingerprints import Screen

from camoufox.fingerprints import generate_fingerprint, from_browserforge
from camoufox.pkgman import installed_verstr
from camoufox.utils import get_target_os, sample_webgl, update_fonts

# OS choices we expose. Camoufox keeps UA/platform/fonts/webgl internally
# consistent per OS, so picking one OS keeps the fingerprint coherent.
SUPPORTED_OS = ("macos", "windows", "linux")

# Common, non-exotic screen sizes per OS — keeps resolution plausible for the UA.
_SCREENS = {
    "macos": [(1512, 982), (1440, 900), (1728, 1117), (2560, 1440)],
    "windows": [(1920, 1080), (1366, 768), (1536, 864), (2560, 1440)],
    "linux": [(1920, 1080), (1680, 1050), (1366, 768)],
}


SUPPORTED_ENGINES = ("camoufox", "chromium")


@dataclass
class FingerprintSpec:
    """A persisted, replayable fingerprint identity for one profile.

    `engine` selects the browser backend:
      - camoufox: `config` is a Camoufox property dict (engine-level spoofing).
      - chromium: `config` holds Playwright context options (ua/locale/viewport/…)
        applied to a patchright-driven Chromium for clean automation stealth.
    """

    os: str
    # Engine-specific identity dict (see `engine`).
    config: Dict[str, Any]
    engine: str = "camoufox"
    # Firefox version the fingerprint was generated against (for traceability).
    ff_version: str = ""
    # Whether WebGL2 should be enabled (kept consistent with the pinned WebGL fp).
    webgl2_enabled: bool = True
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "os": self.os,
            "engine": self.engine,
            "ff_version": self.ff_version,
            "webgl2_enabled": self.webgl2_enabled,
            "notes": self.notes,
            "config": self.config,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FingerprintSpec":
        return cls(
            os=d["os"],
            config=d["config"],
            engine=d.get("engine", "camoufox"),
            ff_version=d.get("ff_version", ""),
            webgl2_enabled=d.get("webgl2_enabled", True),
            notes=d.get("notes", ""),
        )


def _generate(os: str, screen: Optional[tuple[int, int]]) -> FingerprintSpec:
    """Core generation against whatever the global RNG state currently is.

    BrowserForge/Camoufox sample from the *global* `random` module, so
    reproducibility is controlled by the caller seeding `random` (see
    `generate_spec`), not by a private Random instance.
    """
    if screen is None:
        screen = random.choice(_SCREENS[os])
    w, h = screen
    # Pin the resolution to a realistic, OS-appropriate value. The joint
    # header/screen sampler occasionally rejects a tight constraint; the retry
    # loop in generate_spec() covers that.
    screen_cons = Screen(min_width=w, max_width=w, min_height=h, max_height=h)

    ff_version = installed_verstr().split(".", 1)[0]

    # 1. Coherent base fingerprint (UA, platform, hardware, screen) from BrowserForge.
    bf = generate_fingerprint(screen=screen_cons, os=os)
    config: Dict[str, Any] = from_browserforge(bf, ff_version)

    target_os = get_target_os(config)

    # 2. Bake the per-launch RNG surfaces NOW so every relaunch is identical.
    config["window.history.length"] = random.randrange(1, 6)

    update_fonts(config, target_os)  # OS-appropriate font set
    config["fonts:spacing_seed"] = random.randrange(0, 1_073_741_823)

    # 3. Pin a WebGL vendor/renderer/params set coherent with the OS.
    webgl_fp = sample_webgl(target_os)
    webgl2_enabled = bool(webgl_fp.pop("webGl2Enabled", True))
    config.update(webgl_fp)

    # 4. Pin canvas anti-fingerprint noise so the canvas hash is stable per profile.
    config["canvas:aaOffset"] = random.randint(-50, 50)
    config["canvas:aaCapOffset"] = True

    return FingerprintSpec(
        os=os,
        config=config,
        ff_version=ff_version,
        webgl2_enabled=webgl2_enabled,
        notes=f'{os} {config.get("screen.width")}x{config.get("screen.height")}',
    )


def _generate_chromium(os: str, screen: Optional[tuple[int, int]]) -> FingerprintSpec:
    """Generate a coherent Chrome fingerprint for the patchright/Chromium engine.

    Stores Playwright context options — the surfaces that can be set WITHOUT
    detectable JS overrides (UA, platform, locale, languages, viewport, screen,
    hardware). Timezone/locale still auto-follow the proxy at launch via geoip.
    """
    from browserforge.fingerprints import FingerprintGenerator

    fg = FingerprintGenerator()
    fp = fg.generate(browser="chrome", os=os)
    nav = fp.navigator
    sc = fp.screen
    w, h = (screen or (sc.width, sc.height))
    cfg: Dict[str, Any] = {
        "userAgent": nav.userAgent,
        "platform": nav.platform,
        "language": nav.language,
        "languages": list(nav.languages or [nav.language]),
        "hardwareConcurrency": nav.hardwareConcurrency,
        "deviceMemory": getattr(nav, "deviceMemory", None),
        "screen": [w, h],
        "viewport": [w, max(600, h - 120)],
        "colorScheme": "light",
    }
    return FingerprintSpec(
        os=os, config=cfg, engine="chromium",
        notes=f'chromium {os} {w}x{h}',
    )


def generate_spec(
    os: str = "macos",
    *,
    engine: str = "camoufox",
    screen: Optional[tuple[int, int]] = None,
    seed: Optional[int] = None,
    _max_attempts: int = 8,
) -> FingerprintSpec:
    """Generate one internally-consistent fingerprint for the chosen engine.

    `seed` makes generation reproducible (useful for tests / cloning); omit it
    for a fresh random identity. BrowserForge occasionally rejects an over-
    constrained sample, so we retry a few times before giving up.
    """
    if os not in SUPPORTED_OS:
        raise ValueError(f"unsupported os {os!r}; choose from {SUPPORTED_OS}")
    if engine not in SUPPORTED_ENGINES:
        raise ValueError(f"unsupported engine {engine!r}; choose from {SUPPORTED_ENGINES}")

    if engine == "chromium":
        if seed is not None:
            import random as _r
            st = _r.getstate()
            try:
                _r.seed(seed)
                try:
                    import numpy as _np
                    _np.random.seed(seed % (2 ** 32))
                except Exception:
                    pass
                return _generate_chromium(os, screen)
            finally:
                _r.setstate(st)
        return _generate_chromium(os, screen)

    if seed is None:
        return _attempt(os, screen, _max_attempts)

    # Reproducible path: BrowserForge/Camoufox sample from BOTH `random` and
    # `numpy.random`, so seed (and restore) both to get byte-stable output.
    state = random.getstate()
    np_state = None
    try:
        import numpy as _np
        np_state = _np.random.get_state()
        _np.random.seed(seed % (2 ** 32))
    except Exception:
        _np = None
    try:
        random.seed(seed)
        last_err: Optional[Exception] = None
        for _ in range(_max_attempts):
            try:
                return _generate(os, screen)
            except ValueError as e:
                last_err = e
        raise RuntimeError(f"fingerprint generation failed after retries: {last_err}")
    finally:
        random.setstate(state)
        if _np is not None and np_state is not None:
            _np.random.set_state(np_state)


def _attempt(os: str, screen, attempts: int) -> FingerprintSpec:
    last_err: Optional[Exception] = None
    for _ in range(attempts):
        try:
            return _generate(os, screen)
        except ValueError as e:
            last_err = e
    raise RuntimeError(f"fingerprint generation failed after retries: {last_err}")


def summary(spec: FingerprintSpec) -> Dict[str, Any]:
    """Human-readable highlights of a fingerprint for CLI/UI display."""
    c = spec.config
    if spec.engine == "chromium":
        sc = c.get("screen") or [None, None]
        return {
            "os": spec.os,
            "engine": "chromium",
            "userAgent": c.get("userAgent"),
            "platform": c.get("platform"),
            "hardwareConcurrency": c.get("hardwareConcurrency"),
            "screen": f"{sc[0]}x{sc[1]}",
            "webglVendor": "Chromium (real GPU)",
            "webglRenderer": "patchright stealth",
            "canvasOffset": None,
            "fontSpacingSeed": None,
        }
    return {
        "os": spec.os,
        "engine": "camoufox",
        "userAgent": c.get("navigator.userAgent"),
        "platform": c.get("navigator.platform"),
        "hardwareConcurrency": c.get("navigator.hardwareConcurrency"),
        "screen": f'{c.get("screen.width")}x{c.get("screen.height")}',
        "webglVendor": c.get("webGl:vendor") or c.get("webGl:unmaskedVendor"),
        "webglRenderer": c.get("webGl:renderer") or c.get("webGl:unmaskedRenderer"),
        "canvasOffset": c.get("canvas:aaOffset"),
        "fontSpacingSeed": c.get("fonts:spacing_seed"),
    }
