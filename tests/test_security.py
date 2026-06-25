"""The local-API guard that stops a malicious webpage from driving the app."""
import os

from fastapi.testclient import TestClient

from xman import service, store


def _client(monkeypatch, host="127.0.0.1"):
    monkeypatch.delenv("XMAN_API_OPEN", raising=False)  # guard active
    store.init(migrate=False)
    return TestClient(service.app, base_url=f"http://{host}")


def test_health_is_open(monkeypatch):
    c = _client(monkeypatch)
    assert c.get("/api/health").status_code == 200


def test_api_requires_client_header(monkeypatch):
    c = _client(monkeypatch)
    # no X-XMan-Client header -> rejected
    assert c.get("/api/profiles").status_code == 403
    # with the header the app always sends -> allowed
    assert c.get("/api/profiles", headers={"X-XMan-Client": "xman"}).status_code == 200


def test_non_loopback_host_is_rejected(monkeypatch):
    # DNS-rebinding style: Host is a foreign domain
    c = _client(monkeypatch, host="evil.example")
    r = c.get("/api/health", headers={"X-XMan-Client": "xman"})
    assert r.status_code == 421
