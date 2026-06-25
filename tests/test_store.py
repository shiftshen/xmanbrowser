"""SQLite store + API smoke tests (no browser launch)."""
import tempfile

import pytest


@pytest.fixture()
def home(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("XMAN_HOME", d)
        # store caches nothing global; just init fresh
        from xman import store
        store.init(migrate=False)
        yield d


def test_crud_cycle(home):
    from xman import store
    p = store.create("acct1", os_name="macos", proxy_raw="1.2.3.4:8080:u:p", seed=3)
    assert store.get("acct1").id == p.id
    assert store.get(p.id).name == "acct1"

    p2 = store.update("acct1", note="hello", group="g1")
    assert p2.note == "hello" and p2.group == "g1"

    assert len(store.all_profiles()) == 1
    assert len(store.all_profiles(group="g1")) == 1
    assert len(store.all_profiles(group="nope")) == 0
    assert len(store.all_profiles(search="acct")) == 1

    store.delete("acct1")
    with pytest.raises(KeyError):
        store.get("acct1")


def test_unique_name(home):
    from xman import store
    store.create("dup", seed=1)
    with pytest.raises(Exception):
        store.create("dup", seed=2)


def test_clone_regenerates_fingerprint(home):
    from xman import store
    a = store.create("a", os_name="macos", seed=1)
    b = store.clone("a", "b")  # regenerate by default
    assert b.name == "b" and b.id != a.id
    # different identity surface
    assert a.fingerprint.config.get("canvas:aaOffset") != b.fingerprint.config.get("canvas:aaOffset") \
        or a.fingerprint.config.get("navigator.userAgent") != b.fingerprint.config.get("navigator.userAgent")
    c = store.clone("a", "c", regenerate_fingerprint=False)
    assert c.fingerprint.config == a.fingerprint.config


def test_export_import_roundtrip(home):
    from xman import store
    store.create("x", os_name="windows", seed=4)
    data = store.export_all()
    assert len(data) == 1
    imp = store.import_profile(data[0])  # auto-rename on conflict
    assert imp.name != "x"
    assert imp.fingerprint.config == store.get("x").fingerprint.config


def test_auto_name(home):
    from xman import store
    a = store.create(os_name="macos", seed=1)
    b = store.create(os_name="macos", seed=2)
    assert a.name == "xman01" and b.name == "xman02"
    # custom names don't disturb the sequence
    store.create("mine", seed=3)
    c = store.create(os_name="macos", seed=4)
    assert c.name == "xman03"


def test_groups(home):
    from xman import store
    store.create("a", group="shopping", seed=1)
    names = {g["name"] for g in store.list_groups()}
    assert {"default", "shopping"} <= names
    counts = {g["name"]: g["count"] for g in store.list_groups()}
    assert counts["shopping"] == 1
    store.delete_group("shopping")
    assert store.get("a").group == "default"  # reassigned, not deleted


def test_proxy_pool(home):
    from xman import store
    p = store.add_proxy("socks5://u:pw@host:1080")
    assert p["label"] == "proxy01"
    p2 = store.add_proxy("http://h:8080", label="dc")
    assert {x["label"] for x in store.list_proxies()} == {"proxy01", "dc"}
    store.update_proxy(p["id"], note="hello")
    assert store.get_proxy(p["id"])["note"] == "hello"
    store.delete_proxy(p2["id"])
    assert len(store.list_proxies()) == 1
    with pytest.raises(Exception):
        store.add_proxy("not-a-proxy://")


def test_proxy_bulk_import(home):
    from xman import store
    # non-proxy lines (comments, prose) are silently ignored, not errored —
    # so a whole `docker ps` block can be pasted.
    res = store.add_proxies_bulk(
        "socks5://u:p@1.2.3.4:1080\n# comment\n\nhttp://h:8080\nbad no port here\n5.6.7.8:3128:u:p"
    )
    assert len(res["added"]) == 3
    assert len(store.list_proxies()) == 3


def test_bulk_import_docker_ps(home):
    """Paste a `docker ps`-style block (one field per line) — extract the port
    mappings as http://127.0.0.1:PORT, ignore names/ids/cpu/time."""
    from xman import store
    text = (
        "nordvpn-th40-proxy\n67d0d4051f5f\nqmcgaw/gluetun:latest\n18893:8888\n0.05%\n3 hours ago\n"
        "nordvpn-th31-proxy\n84cb82f9123a\n127.0.0.1:18888->8888/tcp\n0%\n"
    )
    res = store.add_proxies_bulk(text)
    raws = sorted(p["raw"] for p in res["added"])
    assert raws == ["http://127.0.0.1:18888", "http://127.0.0.1:18893"]


def test_proxy_auto_disable(home):
    from xman import store
    p = store.add_proxy("socks5://h:1080")
    for _ in range(store.AUTO_DISABLE_AFTER):
        store.record_proxy_check(p["id"], None)
    got = store.get_proxy(p["id"])
    assert got["enabled"] is False and got["fail_count"] == store.AUTO_DISABLE_AFTER
    # re-enable + a success resets the fail counter
    store.set_proxy_enabled(p["id"], True)

    class _Geo:
        ip, country, country_code, timezone = "1.1.1.1", "US", "US", "America/New_York"
    got = store.record_proxy_check(p["id"], _Geo())
    assert got["last_ok"] is True and got["fail_count"] == 0 and got["enabled"] is True


def test_proxy_groups(home):
    from xman import store
    store.add_proxy("socks5://h1:1080", label="a", group="us")
    store.add_proxy("http://h2:8080", label="b", group="us")
    store.add_proxy("http://h3:8080", label="c")  # ungrouped
    assert {g["name"]: g["count"] for g in store.proxy_groups()} == {"us": 2}
    assert len(store.list_proxies(group="us")) == 2
    p = store.update_proxy("c", group="eu")
    assert p["group"] == "eu"
    assert {g["name"] for g in store.proxy_groups()} == {"us", "eu"}


def test_providers(home):
    from xman import store
    prov = store.add_provider("rotating_gateway", "socks5://u:p@gw:7000", label="gw")
    assert prov["kind"] == "rotating_gateway"
    res = store.refresh_provider(prov["id"])
    assert res["added"] == 1
    assert store.list_proxies()[0]["source"] == "gw"
    # refresh again is idempotent (same raw already present)
    assert store.refresh_provider(prov["id"])["added"] == 0
    store.delete_provider(prov["id"])
    assert store.list_providers() == []
    with pytest.raises(ValueError):
        store.add_provider("bogus", "x")


def test_provider_parsing():
    from xman import proxy_providers as pp
    assert pp._parse_payload(["1.2.3.4:8080", "bad", "socks5://h:1080"]) == ["1.2.3.4:8080", "socks5://h:1080"]
    out = pp._parse_payload({"data": [{"ip": "9.9.9.9", "port": 3128, "protocol": "http"}]})
    assert out == ["http://9.9.9.9:3128"]


def test_proxy_api(home):
    from fastapi.testclient import TestClient
    from xman.service import app
    c = TestClient(app)
    r = c.post("/api/proxies", json={"raw": "socks5://u:p@h:1080", "label": "x"})
    assert r.status_code == 201 and r.json()["label"] == "x"
    assert c.get("/api/proxies").json()[0]["label"] == "x"
    assert c.get("/api/next-name").json()["name"] == "xman01"
    assert any(g["name"] == "default" for g in c.get("/api/groups").json())


def test_user_data_dir_no_side_effect(home):
    from xman import store
    p = store.create("u", os_name="macos", seed=1)
    d = p.user_data_dir
    assert not d.exists()          # reading the path must NOT create it
    assert p.ensure_user_data_dir().exists()  # explicit create works


def test_batch_launch_handles_missing_engine(home, monkeypatch):
    from fastapi.testclient import TestClient
    from xman import service, engine
    monkeypatch.setattr(engine, "is_installed", lambda e: False)
    monkeypatch.setattr(engine, "ensure_async", lambda e: {"engine": e, "state": "downloading", "percent": 0})
    client = TestClient(service.app)
    client.post("/api/profiles", json={"name": "b1", "os": "macos", "engine": "camoufox", "seed": 1})
    r = client.post("/api/batch/launch", json={"ids": ["b1"]})
    assert r.status_code == 200
    assert r.json()[0].get("engine_downloading") == "camoufox"  # not a runner spawn


def test_api_health_and_create(home):
    from fastapi.testclient import TestClient
    from xman.service import app
    client = TestClient(app)
    assert client.get("/api/health").json()["ok"] is True
    r = client.post("/api/profiles", json={"name": "viaapi", "os": "macos", "seed": 7})
    assert r.status_code == 201
    assert r.json()["name"] == "viaapi"
    assert client.get("/api/profiles/viaapi").json()["running"] is False
    assert client.delete("/api/profiles/viaapi").status_code == 204
