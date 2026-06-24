"""Proxy parsing, health check, and exit-IP geo lookup.

Engineering pattern adapted from aBaiAutoplus core/proxy_pool.py (health-check
idea only) — no business logic carried over.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Optional

import httpx

# A single proxy bound to a profile. We support http / https / socks5.
_SCHEME_RE = re.compile(r"^(?P<scheme>https?|socks5h?)://", re.IGNORECASE)


@dataclass
class Proxy:
    scheme: str  # "http" | "https" | "socks5"
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None

    @classmethod
    def parse(cls, raw: str) -> "Proxy":
        """Parse a proxy from common formats:

        - scheme://user:pass@host:port
        - scheme://host:port
        - host:port:user:pass        (AdsPower/BitBrowser style)
        - host:port
        Default scheme is http when omitted.
        """
        raw = raw.strip()
        if not raw:
            raise ValueError("empty proxy string")

        m = _SCHEME_RE.match(raw)
        if m:
            scheme = m.group("scheme").lower().replace("socks5h", "socks5")
            rest = raw[m.end():]
        else:
            scheme = "http"
            rest = raw

        # user:pass@host:port
        if "@" in rest:
            cred, hostport = rest.rsplit("@", 1)
            username, _, password = cred.partition(":")
            host, _, port = hostport.partition(":")
            return cls(scheme, host, int(port), username or None, password or None)

        parts = rest.split(":")
        if len(parts) == 4:  # host:port:user:pass
            host, port, username, password = parts
            return cls(scheme, host, int(port), username or None, password or None)
        if len(parts) == 2:  # host:port
            host, port = parts
            return cls(scheme, host, int(port))
        raise ValueError(f"unrecognized proxy format: {raw!r}")

    def server_url(self) -> str:
        """server URL without credentials (Camoufox/Playwright wants creds split out)."""
        return f"{self.scheme}://{self.host}:{self.port}"

    def full_url(self) -> str:
        if self.username:
            cred = self.username + (f":{self.password}" if self.password else "")
            return f"{self.scheme}://{cred}@{self.host}:{self.port}"
        return self.server_url()

    def to_camoufox(self) -> dict:
        """dict shape Camoufox/Playwright `proxy=` expects."""
        d: dict = {"server": self.server_url()}
        if self.username:
            d["username"] = self.username
        if self.password:
            d["password"] = self.password
        return d

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GeoInfo:
    ip: str
    country: Optional[str] = None
    country_code: Optional[str] = None
    city: Optional[str] = None
    timezone: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


def _httpx_proxy(proxy: Optional[Proxy]) -> Optional[str]:
    return proxy.full_url() if proxy else None


def check_and_locate(proxy: Optional[Proxy], timeout: float = 15.0) -> GeoInfo:
    """Verify the proxy works and return the exit IP + geo.

    Uses ip-api.com (free, no key) through the proxy so the geo reflects the
    *exit* node — the same vantage point the browser will use. Raises on failure.
    """
    proxy_url = _httpx_proxy(proxy)
    with httpx.Client(proxy=proxy_url, timeout=timeout) as client:
        r = client.get(
            "http://ip-api.com/json/?fields=status,message,country,countryCode,city,timezone,lat,lon,query"
        )
        r.raise_for_status()
        data = r.json()
    if data.get("status") != "success":
        raise RuntimeError(f"geo lookup failed: {data.get('message', data)}")
    return GeoInfo(
        ip=data["query"],
        country=data.get("country"),
        country_code=data.get("countryCode"),
        city=data.get("city"),
        timezone=data.get("timezone"),
        latitude=data.get("lat"),
        longitude=data.get("lon"),
    )
