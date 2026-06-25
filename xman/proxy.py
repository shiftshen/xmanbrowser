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
_IPV4_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


def _host_score(tok: str) -> int:
    """How host-like a token is: IPv4=3, dotted hostname=2, bare word=1, else 0.
    A pure number is a port, never a host."""
    if _IPV4_RE.match(tok):
        return 3
    if tok.isdigit():
        return 0
    if "." in tok:
        return 2
    if re.search(r"[a-zA-Z]", tok):
        return 1
    return 0


def _assign_fields(scheme: str, fields: list) -> "Proxy":
    """Given 2-4 fields in ANY order/separator, work out host / port / user / pass
    by content: the port is a number 1-65535, the host is the most host-like token
    (IP or domain), and the remaining two are user/pass in order."""
    fields = [f for f in fields if f != ""]
    ports = [i for i, f in enumerate(fields) if f.isdigit() and 1 <= int(f) <= 65535]
    if not ports or len(fields) < 2:
        raise ValueError("no host:port found")
    # host = highest host-score token (prefer one that isn't the port)
    ranked = sorted(range(len(fields)), key=lambda i: (_host_score(fields[i]), -i), reverse=True)
    host_i = next((i for i in ranked if i not in ports or len(ports) == len(fields)), ranked[0])
    if _host_score(fields[host_i]) == 0:
        raise ValueError("no host found")
    # port = a port-looking field adjacent to the host, else the first port
    port_i = next((c for c in (host_i + 1, host_i - 1) if c in ports), ports[0])
    if port_i == host_i:
        port_i = next((p for p in ports if p != host_i), None)
    if port_i is None:
        raise ValueError("no port found")
    others = [fields[i] for i in range(len(fields)) if i not in (host_i, port_i)]
    user = others[0] if len(others) >= 1 else None
    pw = others[1] if len(others) >= 2 else None
    return Proxy(scheme, fields[host_i], int(fields[port_i]), user or None, pw or None)


@dataclass
class Proxy:
    scheme: str  # "http" | "https" | "socks5"
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None

    @classmethod
    def parse(cls, raw: str) -> "Proxy":
        """Parse a proxy from (almost) any common format, auto-detecting which
        field is the host / port / user / pass regardless of order or separator:

        - scheme://user:pass@host:port  ·  scheme://host:port
        - host:port  ·  host:port:user:pass  ·  user:pass:host:port
        - host:port@user:pass  ·  user:pass@host:port
        - space / tab / comma / pipe separated, or dash-separated IP lists
        Default scheme is http when omitted.
        """
        raw = raw.strip()
        if not raw:
            raise ValueError("empty proxy string")

        scheme = "http"
        m = _SCHEME_RE.match(raw)
        if m:
            scheme = m.group("scheme").lower().replace("socks5h", "socks5")
            raw = raw[m.end():]

        # creds and server split by '@', either order (host side identified by content)
        if "@" in raw:
            a, b = raw.rsplit("@", 1)
            for creds, server in ((a, b), (b, a)):
                try:
                    sp = cls._fields(server)
                    cp = cls._fields(creds)
                    if len(sp) == 2 and 1 <= len(cp) <= 2:
                        return _assign_fields(scheme, [*sp, *cp])
                except Exception:
                    continue
            raise ValueError(f"unrecognized proxy format: {raw!r}")

        # try separators in order of confidence; first that yields host:port wins
        for fields in cls._candidate_splits(raw):
            try:
                return _assign_fields(scheme, fields)
            except Exception:
                continue
        raise ValueError(f"unrecognized proxy format: {raw!r}")

    @staticmethod
    def _fields(s: str) -> list:
        s = s.strip()
        if re.search(r"[\s,|]", s):
            return [f for f in re.split(r"[\s,|]+", s) if f]
        return [f for f in s.split(":") if f]

    @classmethod
    def _candidate_splits(cls, raw: str):
        # whitespace / comma / pipe / tab
        if re.search(r"[\s,|]", raw):
            yield [f for f in re.split(r"[\s,|]+", raw) if f]
        # colon (the classic host:port:user:pass)
        yield [f for f in raw.split(":") if f]
        # dash, only for an IP-led list (avoid splitting hostnames like my-proxy.com)
        if re.match(r"^\d{1,3}(?:\.\d{1,3}){3}-\d", raw):
            yield [f for f in raw.split("-") if f]

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
    isp: Optional[str] = None
    # "datacenter" | "residential" | "mobile" | None — quality signal: datacenter
    # IPs get flagged (hosting/proxy) by anti-fraud, residential/mobile look clean.
    ip_type: Optional[str] = None


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
                    _classify_ip(geo, timeout=timeout)
                    return geo
                last_err = f"{url.split('/')[2]} -> unexpected response"
            except Exception as e:  # noqa: BLE001 — try the next provider
                last_err = f"{url.split('/')[2]} -> {str(e)[:60]}"
                continue
    raise RuntimeError(f"could not reach any geo service through the proxy ({last_err})")


def _classify_ip(geo: GeoInfo, timeout: float = 8.0) -> None:
    """Tag the exit IP's quality (datacenter / residential / mobile) + ISP.

    Queried directly (not through the proxy) against ip-api's free proxy/hosting/
    mobile flags. Best-effort — failures leave the fields None.
    """
    try:
        with httpx.Client(timeout=timeout) as c:
            r = c.get(f"http://ip-api.com/json/{geo.ip}?fields=status,isp,proxy,hosting,mobile")
            d = r.json()
        if d.get("status") != "success":
            return
        geo.isp = d.get("isp")
        if d.get("mobile"):
            geo.ip_type = "mobile"
        elif d.get("hosting"):
            geo.ip_type = "datacenter"
        elif d.get("proxy"):
            geo.ip_type = "datacenter"  # flagged proxy IP, treat as risky
        else:
            geo.ip_type = "residential"
    except Exception:
        pass
