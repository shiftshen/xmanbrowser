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


# A sensible primary locale per country so the browser's language stays
# consistent with the proxy's exit timezone (avoids tells like tz=Asia/Bangkok
# with lang=bar-DE). Falls back to en-US.
_COUNTRY_LOCALE = {
    "US": "en-US", "GB": "en-GB", "CA": "en-CA", "AU": "en-AU", "IE": "en-IE",
    "TH": "th-TH", "SG": "en-SG", "MY": "ms-MY", "ID": "id-ID", "VN": "vi-VN",
    "PH": "en-PH", "JP": "ja-JP", "KR": "ko-KR", "CN": "zh-CN", "HK": "zh-HK",
    "TW": "zh-TW", "IN": "en-IN", "DE": "de-DE", "FR": "fr-FR", "ES": "es-ES",
    "IT": "it-IT", "NL": "nl-NL", "PT": "pt-PT", "BR": "pt-BR", "RU": "ru-RU",
    "PL": "pl-PL", "TR": "tr-TR", "SE": "sv-SE", "NO": "nb-NO", "DK": "da-DK",
    "FI": "fi-FI", "CH": "de-CH", "AT": "de-AT", "BE": "nl-BE", "MX": "es-MX",
    "AR": "es-AR", "AE": "ar-AE", "SA": "ar-SA", "ZA": "en-ZA", "NZ": "en-NZ",
}


def locale_for_country(country_code: Optional[str]) -> str:
    return _COUNTRY_LOCALE.get((country_code or "").upper(), "en-US")


# Geo providers tried in order (all free, no key, HTTPS). Each returns a parser
# that maps the JSON to a GeoInfo. Multiple providers because any single one can
# rate-limit or 500 for a given exit IP (e.g. datacenter/VPN ranges).
def _parse_ipwho(d: dict) -> Optional[GeoInfo]:
    if d.get("success") is False:
        return None
    return GeoInfo(ip=d.get("ip"), country=d.get("country"), country_code=d.get("country_code"),
                   city=d.get("city"), timezone=(d.get("timezone") or {}).get("id"),
                   latitude=d.get("latitude"), longitude=d.get("longitude"))


def _parse_ipinfo(d: dict) -> Optional[GeoInfo]:
    if not d.get("ip"):
        return None
    loc = (d.get("loc") or ",").split(",")
    lat = float(loc[0]) if loc[0] else None
    lon = float(loc[1]) if len(loc) > 1 and loc[1] else None
    return GeoInfo(ip=d.get("ip"), country=d.get("country"), country_code=d.get("country"),
                   city=d.get("city"), timezone=d.get("timezone"), latitude=lat, longitude=lon)


def _parse_ipapi(d: dict) -> Optional[GeoInfo]:
    if d.get("status") != "success":
        return None
    return GeoInfo(ip=d.get("query"), country=d.get("country"), country_code=d.get("countryCode"),
                   city=d.get("city"), timezone=d.get("timezone"),
                   latitude=d.get("lat"), longitude=d.get("lon"))


_GEO_PROVIDERS = [
    ("https://ipwho.is/", _parse_ipwho),
    ("https://ipinfo.io/json", _parse_ipinfo),
    ("http://ip-api.com/json/?fields=status,message,country,countryCode,city,timezone,lat,lon,query", _parse_ipapi),
]


def check_and_locate(proxy: Optional[Proxy], timeout: float = 15.0) -> GeoInfo:
    """Verify the proxy works and return the exit IP + geo.

    The lookup goes *through* the proxy so the geo reflects the exit node — the
    same vantage point the browser will use. Tries several geo providers so one
    flaky/blocked service doesn't fail an otherwise-working proxy.
    """
    proxy_url = _httpx_proxy(proxy)
    last_err: Optional[str] = None
    with httpx.Client(proxy=proxy_url, timeout=timeout, follow_redirects=True) as client:
        for url, parser in _GEO_PROVIDERS:
            try:
                r = client.get(url)
                if r.status_code != 200:
                    last_err = f"{url.split('/')[2]} -> HTTP {r.status_code}"
                    continue
                geo = parser(r.json())
                if geo and geo.ip:
                    return geo
                last_err = f"{url.split('/')[2]} -> unexpected response"
            except Exception as e:  # noqa: BLE001 — try the next provider
                last_err = f"{url.split('/')[2]} -> {str(e)[:60]}"
                continue
    raise RuntimeError(f"could not reach any geo service through the proxy ({last_err})")
