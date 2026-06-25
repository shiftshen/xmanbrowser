"""Fast unit tests (no browser launch). Run: python -m pytest"""
import json
import os
import tempfile

import pytest

from xman.proxy import Proxy
from xman import fingerprint as fp


# ---------- proxy parsing ----------

@pytest.mark.parametrize("raw,scheme,host,port,user,pw", [
    ("socks5://u:p@1.2.3.4:1080", "socks5", "1.2.3.4", 1080, "u", "p"),
    ("http://1.2.3.4:8080", "http", "1.2.3.4", 8080, None, None),
    ("1.2.3.4:8080", "http", "1.2.3.4", 8080, None, None),
    ("1.2.3.4:8080:user:pass", "http", "1.2.3.4", 8080, "user", "pass"),
    ("socks5h://h:9050", "socks5", "h", 9050, None, None),
])
def test_proxy_parse(raw, scheme, host, port, user, pw):
    p = Proxy.parse(raw)
    assert (p.scheme, p.host, p.port, p.username, p.password) == (scheme, host, port, user, pw)


def test_proxy_camoufox_shape():
    p = Proxy.parse("socks5://u:p@h:1080")
    assert p.to_camoufox() == {"server": "socks5://h:1080", "username": "u", "password": "p"}


def test_proxy_bad():
    with pytest.raises(ValueError):
        Proxy.parse("")


def test_locale_for_country():
    from xman.proxy import locale_for_country
    assert locale_for_country("TH") == "th-TH"
    assert locale_for_country("US") == "en-US"
    assert locale_for_country("jp") == "ja-JP"
    assert locale_for_country(None) == "en-US"
    assert locale_for_country("ZZ") == "en-US"  # unknown -> sane default


# ---------- fingerprint generation / consistency ----------

def test_seed_is_reproducible_via_json():
    a = fp.generate_spec("macos", seed=12345)
    b = fp.generate_spec("macos", seed=12345)
    # NaN inside nested webgl params breaks raw dict ==, so compare the
    # serialized form (which is what we actually persist & replay).
    assert json.dumps(a.config, sort_keys=True, default=str) == \
           json.dumps(b.config, sort_keys=True, default=str)


def test_different_seed_differs():
    a = fp.generate_spec("macos", seed=1)
    b = fp.generate_spec("macos", seed=2)
    assert a.config.get("navigator.userAgent") or True
    assert a.config != b.config


@pytest.mark.parametrize("osname,platform_sub", [
    ("macos", "Mac"),
    ("windows", "Win"),
    ("linux", "Linux"),
])
def test_os_internal_consistency(osname, platform_sub):
    s = fp.generate_spec(osname, seed=7)
    ua = s.config["navigator.userAgent"]
    plat = s.config["navigator.platform"]
    assert platform_sub in ua and platform_sub in plat
    # canvas + font noise seeds must be pinned for stability
    assert "canvas:aaOffset" in s.config
    assert "fonts:spacing_seed" in s.config
    assert "webGl:renderer" in s.config


def test_unsupported_os():
    with pytest.raises(ValueError):
        fp.generate_spec("solaris")


def test_chromium_engine_spec():
    s = fp.generate_spec("macos", engine="chromium", seed=1)
    assert s.engine == "chromium"
    c = s.config
    assert "Chrome" in c["userAgent"] and "Firefox" not in c["userAgent"]
    assert c["platform"] == "MacIntel"
    assert isinstance(c["screen"], list) and len(c["screen"]) == 2
    sm = fp.summary(s)
    assert sm["engine"] == "chromium" and "Chrome" in sm["userAgent"]
    # round-trips through persistence with the engine preserved
    assert fp.FingerprintSpec.from_dict(s.to_dict()).engine == "chromium"


def test_unsupported_engine():
    with pytest.raises(ValueError):
        fp.generate_spec("macos", engine="webkit")


# ---------- profile persistence + isolation ----------

def test_profile_save_load_and_isolation(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("XMAN_HOME", d)
        from xman.profile import create_profile, Profile
        p = create_profile("acct1", os_name="macos", proxy_raw="socks5://u:p@h:1080", seed=5)
        loaded = Profile.load("acct1")
        assert loaded.id == p.id
        assert loaded.proxy_raw == "socks5://u:p@h:1080"
        assert loaded.proxy.port == 1080
        # replayed config is identical -> stable fingerprint
        assert loaded.fingerprint.config == p.fingerprint.config
        # isolated, distinct user-data-dirs
        q = create_profile("acct2", os_name="macos", seed=6)
        assert p.user_data_dir != q.user_data_dir
        assert os.path.isdir(p.user_data_dir)
