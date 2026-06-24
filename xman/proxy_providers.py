"""Dynamic proxy providers — fetch proxies from an external source.

Engineering pattern borrowed from the legacy aBaiAutoplus
`providers/proxy/*` (api_extract + rotating_gateway), rewritten clean and
scoped to a fingerprint browser. No registration/payment logic.

Two kinds:
  - api_extract:     GET a URL that returns a list of proxies (JSON or plain
                     lines); each becomes a pool entry.
  - rotating_gateway: a single fixed gateway endpoint whose exit IP rotates
                     server-side; stored as one pool entry.
"""
from __future__ import annotations

import re
from typing import List

import httpx

from .proxy import Proxy

_LINE_RE = re.compile(r"\s+")
# JSON keys commonly holding the proxy list
_LIST_KEYS = ("data", "proxies", "list", "result", "results", "items")


def _normalize(item) -> str | None:
    """Coerce one API item (string or dict) into a proxy raw string."""
    if isinstance(item, str):
        raw = item.strip()
        if not raw:
            return None
        try:
            Proxy.parse(raw)
            return raw
        except Exception:
            return None
    if isinstance(item, dict):
        host = item.get("ip") or item.get("host") or item.get("server") or item.get("addr")
        port = item.get("port")
        if not host or not port:
            return None
        scheme = (item.get("scheme") or item.get("protocol") or item.get("type") or "http").lower()
        if scheme not in ("http", "https", "socks5"):
            scheme = "http"
        user = item.get("user") or item.get("username")
        pw = item.get("pass") or item.get("password")
        cred = f"{user}:{pw}@" if user else ""
        raw = f"{scheme}://{cred}{host}:{port}"
        try:
            Proxy.parse(raw)
            return raw
        except Exception:
            return None
    return None


def _parse_payload(payload) -> List[str]:
    out: List[str] = []
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = None
        for k in _LIST_KEYS:
            v = payload.get(k)
            if isinstance(v, list):
                items = v
                break
        if items is None:
            # maybe {host,port} single object
            single = _normalize(payload)
            return [single] if single else []
    else:
        return []
    for it in items:
        n = _normalize(it)
        if n:
            out.append(n)
    return out


def fetch_api_extract(url: str, *, timeout: float = 20.0) -> List[str]:
    """GET `url` and return a list of normalized proxy raw strings.

    Accepts a JSON body (list, or an object with a list under a common key) or
    a plain-text body with one proxy per line.
    """
    with httpx.Client(timeout=timeout, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        body = r.text
    proxies: List[str] = []
    if "json" in ctype or body.lstrip().startswith(("{", "[")):
        try:
            proxies = _parse_payload(r.json())
        except Exception:
            proxies = []
    if not proxies:
        # plain-text: one per line (also handles whitespace-separated)
        for line in body.splitlines():
            for tok in _LINE_RE.split(line.strip()):
                n = _normalize(tok)
                if n:
                    proxies.append(n)
    # de-dup, keep order
    seen, uniq = set(), []
    for p in proxies:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def fetch(kind: str, url: str) -> List[str]:
    """Fetch proxies for a provider of the given kind."""
    if kind == "rotating_gateway":
        raw = url.strip()
        Proxy.parse(raw)  # validate
        return [raw]
    if kind == "api_extract":
        return fetch_api_extract(url)
    raise ValueError(f"unknown provider kind: {kind!r}")
