"""Regression: the chromium install check must be process-free.

Calling sync_playwright() (the Node driver) from inside the API server hangs the
PyInstaller-frozen sidecar, wedging /api/engine/status and every chromium launch
while Camoufox stays fine. is_installed() must resolve the browser from disk
only — never start a driver.
"""
import sys
import types

from xman import engine


def test_is_installed_chromium_never_starts_playwright(monkeypatch):
    # Poison sync_playwright so the test fails loudly if the check regresses to
    # spawning the driver.
    fake = types.ModuleType("patchright.sync_api")
    def _boom(*a, **k):
        raise AssertionError("is_installed must not start a Playwright driver")
    fake.sync_playwright = _boom
    monkeypatch.setitem(sys.modules, "patchright.sync_api", fake)
    # Must not raise and must return a bool.
    assert isinstance(engine.is_installed("chromium"), bool)


def test_is_installed_chromium_true_when_marker_present(tmp_path, monkeypatch):
    base = tmp_path / "ms-playwright"
    d = base / "chromium-9999"
    (d / "chrome-mac-arm64").mkdir(parents=True)
    (d / "INSTALLATION_COMPLETE").write_text("")
    monkeypatch.setattr(engine, "_chromium_dir", lambda: base)
    monkeypatch.setattr(engine, "_patchright_chromium_revision", lambda: "9999")
    assert engine.is_installed("chromium") is True


def test_is_installed_chromium_false_without_marker(tmp_path, monkeypatch):
    base = tmp_path / "ms-playwright"
    (base / "chromium-9999" / "chrome-mac-arm64").mkdir(parents=True)  # no marker
    monkeypatch.setattr(engine, "_chromium_dir", lambda: base)
    monkeypatch.setattr(engine, "_patchright_chromium_revision", lambda: "9999")
    assert engine.is_installed("chromium") is False


def _complete(d):
    (d / "chrome-mac-arm64").mkdir(parents=True)
    (d / "INSTALLATION_COMPLETE").write_text("")


def test_pinned_revision_missing_does_not_accept_stale_cache(tmp_path, monkeypatch):
    """codex regression: when the pinned build is known but absent, an older
    complete chromium-* must NOT satisfy the check — otherwise _ensure_chromium
    skips the required download and the launch fails."""
    base = tmp_path / "ms-playwright"
    _complete(base / "chromium-1111")          # an old, complete cache
    monkeypatch.setattr(engine, "_chromium_dir", lambda: base)
    monkeypatch.setattr(engine, "_patchright_chromium_revision", lambda: "9999")  # pinned, absent
    assert engine.is_installed("chromium") is False


def test_unknown_revision_falls_back_to_any_complete(tmp_path, monkeypatch):
    base = tmp_path / "ms-playwright"
    _complete(base / "chromium-1234")
    monkeypatch.setattr(engine, "_chromium_dir", lambda: base)
    monkeypatch.setattr(engine, "_patchright_chromium_revision", lambda: None)  # unreadable
    assert engine.is_installed("chromium") is True
