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
