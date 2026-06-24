"""SQLite-backed profile store (M2).

Source of truth for profiles. Fingerprint config is stored as a JSON blob so the
schema stays small and the stable-config replay model from M1 is preserved.
One-time migration imports any M1 JSON profiles found under profiles/.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from .fingerprint import FingerprintSpec, generate_spec
from .profile import Profile, data_dir, profiles_dir
from .proxy import Proxy

_SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    grp          TEXT NOT NULL DEFAULT 'default',
    note         TEXT NOT NULL DEFAULT '',
    proxy_raw    TEXT,
    os           TEXT NOT NULL,
    fingerprint  TEXT NOT NULL,         -- FingerprintSpec.to_dict() JSON
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS proxies (
    id           TEXT PRIMARY KEY,
    label        TEXT NOT NULL UNIQUE,
    raw          TEXT NOT NULL,
    note         TEXT NOT NULL DEFAULT '',
    last_ip      TEXT,
    last_country TEXT,
    last_cc      TEXT,
    last_tz      TEXT,
    last_ok      INTEGER,               -- 1 ok / 0 fail / NULL never checked
    checked_at   REAL,
    enabled      INTEGER NOT NULL DEFAULT 1,
    fail_count   INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    source       TEXT,                  -- provider label this proxy came from (NULL = manual)
    grp          TEXT NOT NULL DEFAULT '',
    created_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS proxy_providers (
    id           TEXT PRIMARY KEY,
    label        TEXT NOT NULL UNIQUE,
    kind         TEXT NOT NULL,         -- 'api_extract' | 'rotating_gateway'
    url          TEXT NOT NULL,
    note         TEXT NOT NULL DEFAULT '',
    last_count   INTEGER,
    refreshed_at REAL,
    created_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS groups (
    name         TEXT PRIMARY KEY,
    created_at   REAL NOT NULL
);
"""

# Columns added after the proxies table first shipped — added in-place for DBs
# created by an earlier version.
_PROXY_MIGRATIONS = {
    "enabled": "ALTER TABLE proxies ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1",
    "fail_count": "ALTER TABLE proxies ADD COLUMN fail_count INTEGER NOT NULL DEFAULT 0",
    "success_count": "ALTER TABLE proxies ADD COLUMN success_count INTEGER NOT NULL DEFAULT 0",
    "source": "ALTER TABLE proxies ADD COLUMN source TEXT",
    "grp": "ALTER TABLE proxies ADD COLUMN grp TEXT NOT NULL DEFAULT ''",
}


def _migrate_columns(c: sqlite3.Connection) -> None:
    have = {r[1] for r in c.execute("PRAGMA table_info(proxies)").fetchall()}
    for col, ddl in _PROXY_MIGRATIONS.items():
        if col not in have:
            c.execute(ddl)


def db_path() -> Path:
    data_dir().mkdir(parents=True, exist_ok=True)
    return data_dir() / "xman.db"


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(db_path())
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(_SCHEMA)
        _migrate_columns(c)
        yield c
        c.commit()
    finally:
        c.close()


def _row_to_profile(r: sqlite3.Row) -> Profile:
    return Profile(
        id=r["id"],
        name=r["name"],
        fingerprint=FingerprintSpec.from_dict(json.loads(r["fingerprint"])),
        proxy_raw=r["proxy_raw"],
        group=r["grp"],
        note=r["note"],
    )


def init(migrate: bool = True) -> None:
    with _conn():
        pass
    if migrate:
        _migrate_json()


def _migrate_json() -> None:
    """Import M1 JSON profiles once (skips names already in the DB)."""
    pdir = profiles_dir()
    existing = {p.name for p in all_profiles()}
    for f in pdir.glob("*.json"):
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        if d.get("name") in existing:
            continue
        prof = Profile.from_dict(d)
        try:
            _insert(prof)
            existing.add(prof.name)
        except sqlite3.IntegrityError:
            pass


def _insert(prof: Profile) -> None:
    now = time.time()
    with _conn() as c:
        c.execute(
            "INSERT INTO profiles (id,name,grp,note,proxy_raw,os,fingerprint,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                prof.id, prof.name, prof.group, prof.note, prof.proxy_raw,
                prof.fingerprint.os, json.dumps(prof.fingerprint.to_dict()), now, now,
            ),
        )


def create(
    name: Optional[str] = None,
    *,
    os_name: str = "macos",
    proxy_raw: Optional[str] = None,
    group: str = "default",
    note: str = "",
    seed: Optional[int] = None,
) -> Profile:
    if proxy_raw:
        Proxy.parse(proxy_raw)  # validate
    name = name or next_profile_name()
    spec = generate_spec(os_name, seed=seed)
    prof = Profile(id=uuid.uuid4().hex[:12], name=name, fingerprint=spec,
                   proxy_raw=proxy_raw, group=group, note=note)
    _insert(prof)
    _ensure_group(group)
    return prof


def next_profile_name(prefix: str = "xman") -> str:
    """Next free auto name like xman01, xman02 … (zero-padded to 2+ digits)."""
    import re
    names = {p.name for p in all_profiles()}
    pat = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    used = [int(m.group(1)) for n in names if (m := pat.match(n))]
    nxt = (max(used) + 1) if used else 1
    width = max(2, len(str(nxt)))
    cand = f"{prefix}{nxt:0{width}d}"
    while cand in names:  # guard against gaps/collisions
        nxt += 1
        cand = f"{prefix}{nxt:0{max(2, len(str(nxt))) }d}"
    return cand


def get(name_or_id: str) -> Profile:
    with _conn() as c:
        r = c.execute(
            "SELECT * FROM profiles WHERE id=? OR name=?", (name_or_id, name_or_id)
        ).fetchone()
    if not r:
        raise KeyError(f"profile not found: {name_or_id}")
    return _row_to_profile(r)


def all_profiles(group: Optional[str] = None, search: Optional[str] = None) -> list[Profile]:
    q = "SELECT * FROM profiles"
    args: list = []
    conds = []
    if group:
        conds.append("grp=?"); args.append(group)
    if search:
        conds.append("(name LIKE ? OR note LIKE ?)"); args += [f"%{search}%", f"%{search}%"]
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY created_at"
    with _conn() as c:
        rows = c.execute(q, args).fetchall()
    return [_row_to_profile(r) for r in rows]


def update(name_or_id: str, *, proxy_raw=..., group=..., note=..., name=...) -> Profile:
    prof = get(name_or_id)
    fields, args = [], []
    if proxy_raw is not ...:
        if proxy_raw:
            Proxy.parse(proxy_raw)
        fields.append("proxy_raw=?"); args.append(proxy_raw)
    if group is not ...:
        fields.append("grp=?"); args.append(group)
    if note is not ...:
        fields.append("note=?"); args.append(note)
    if name is not ...:
        fields.append("name=?"); args.append(name)
    if not fields:
        return prof
    fields.append("updated_at=?"); args.append(time.time())
    args.append(prof.id)
    with _conn() as c:
        c.execute(f"UPDATE profiles SET {','.join(fields)} WHERE id=?", args)
    return get(prof.id)


def clone(name_or_id: str, new_name: str, *, regenerate_fingerprint: bool = True) -> Profile:
    src = get(name_or_id)
    if regenerate_fingerprint:
        spec = generate_spec(src.fingerprint.os)
    else:
        spec = src.fingerprint
    prof = Profile(id=uuid.uuid4().hex[:12], name=new_name, fingerprint=spec,
                   proxy_raw=src.proxy_raw, group=src.group, note=src.note)
    _insert(prof)
    return prof


def delete(name_or_id: str, *, wipe_userdata: bool = True) -> None:
    prof = get(name_or_id)
    with _conn() as c:
        c.execute("DELETE FROM profiles WHERE id=?", (prof.id,))
    if wipe_userdata:
        import shutil
        d = data_dir() / "userdata" / prof.id
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)


# --- import / export ---

def export_profile(name_or_id: str) -> dict:
    return get(name_or_id).to_dict()


def export_all() -> list[dict]:
    return [p.to_dict() for p in all_profiles()]


def import_profile(d: dict, *, new_id: bool = True, rename_on_conflict: bool = True) -> Profile:
    prof = Profile.from_dict(d)
    if new_id:
        prof.id = uuid.uuid4().hex[:12]
    if rename_on_conflict:
        base = prof.name
        i = 1
        names = {p.name for p in all_profiles()}
        while prof.name in names:
            i += 1
            prof.name = f"{base}-{i}"
    _insert(prof)
    _ensure_group(prof.group)
    return prof


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------

def _ensure_group(name: str) -> None:
    if not name:
        return
    with _conn() as c:
        c.execute("INSERT OR IGNORE INTO groups (name, created_at) VALUES (?, ?)",
                  (name, time.time()))


def list_groups() -> list[dict]:
    """Groups with their profile counts. 'default' is always present."""
    _ensure_group("default")
    with _conn() as c:
        rows = c.execute("SELECT name FROM groups ORDER BY name").fetchall()
        counts = dict(c.execute("SELECT grp, COUNT(*) FROM profiles GROUP BY grp").fetchall())
    return [{"name": r["name"], "count": counts.get(r["name"], 0)} for r in rows]


def add_group(name: str) -> None:
    _ensure_group(name)


def delete_group(name: str) -> None:
    """Remove a group; its profiles fall back to 'default'."""
    if name == "default":
        raise ValueError("cannot delete the default group")
    with _conn() as c:
        c.execute("UPDATE profiles SET grp='default' WHERE grp=?", (name,))
        c.execute("DELETE FROM groups WHERE name=?", (name,))


# ---------------------------------------------------------------------------
# Proxy pool
# ---------------------------------------------------------------------------

def _proxy_row(r: sqlite3.Row) -> dict:
    keys = r.keys()
    return {
        "id": r["id"],
        "label": r["label"],
        "raw": r["raw"],
        "note": r["note"],
        "last_ip": r["last_ip"],
        "last_country": r["last_country"],
        "last_cc": r["last_cc"],
        "last_tz": r["last_tz"],
        "last_ok": None if r["last_ok"] is None else bool(r["last_ok"]),
        "checked_at": r["checked_at"],
        "enabled": bool(r["enabled"]) if "enabled" in keys else True,
        "fail_count": r["fail_count"] if "fail_count" in keys else 0,
        "success_count": r["success_count"] if "success_count" in keys else 0,
        "source": r["source"] if "source" in keys else None,
        "group": r["grp"] if "grp" in keys else "",
    }


def list_proxies(group: Optional[str] = None) -> list[dict]:
    with _conn() as c:
        if group:
            rows = c.execute("SELECT * FROM proxies WHERE grp=? ORDER BY created_at", (group,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM proxies ORDER BY created_at").fetchall()
    return [_proxy_row(r) for r in rows]


def proxy_groups() -> list[dict]:
    """Distinct non-empty proxy groups with counts."""
    with _conn() as c:
        rows = c.execute(
            "SELECT grp, COUNT(*) c FROM proxies WHERE grp != '' GROUP BY grp ORDER BY grp"
        ).fetchall()
    return [{"name": r["grp"], "count": r["c"]} for r in rows]


def get_proxy(pid: str) -> dict:
    with _conn() as c:
        r = c.execute("SELECT * FROM proxies WHERE id=? OR label=?", (pid, pid)).fetchone()
    if not r:
        raise KeyError(f"proxy not found: {pid}")
    return _proxy_row(r)


def add_proxy(raw: str, *, label: Optional[str] = None, note: str = "",
              source: Optional[str] = None, group: str = "") -> dict:
    Proxy.parse(raw)  # validate
    label = label or _next_proxy_label()
    pid = uuid.uuid4().hex[:12]
    with _conn() as c:
        c.execute(
            "INSERT INTO proxies (id,label,raw,note,source,grp,created_at) VALUES (?,?,?,?,?,?,?)",
            (pid, label, raw, note, source, group, time.time()),
        )
    return get_proxy(pid)


def set_proxy_enabled(pid: str, enabled: bool) -> dict:
    p = get_proxy(pid)
    with _conn() as c:
        c.execute("UPDATE proxies SET enabled=? WHERE id=?", (1 if enabled else 0, p["id"]))
    return get_proxy(p["id"])


def add_proxies_bulk(text: str) -> dict:
    """Add many proxies at once — one per line (blank / '#' lines skipped).

    Borrowed pattern from the legacy proxy-management UI. Returns the rows that
    were added and any per-line errors so the UI can report them.
    """
    added, errors = [], []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        try:
            added.append(add_proxy(raw))
        except Exception as e:  # noqa: BLE001 — surface bad lines, keep going
            errors.append({"line": raw, "error": str(e)})
    return {"added": added, "errors": errors}


def _next_proxy_label(prefix: str = "proxy") -> str:
    import re
    labels = {p["label"] for p in list_proxies()}
    pat = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    used = [int(m.group(1)) for n in labels if (m := pat.match(n))]
    nxt = (max(used) + 1) if used else 1
    return f"{prefix}{nxt:02d}"


def update_proxy(pid: str, *, label=..., raw=..., note=..., group=...) -> dict:
    p = get_proxy(pid)
    fields, args = [], []
    if label is not ...:
        fields.append("label=?"); args.append(label)
    if raw is not ...:
        Proxy.parse(raw)
        fields.append("raw=?"); args.append(raw)
    if note is not ...:
        fields.append("note=?"); args.append(note)
    if group is not ...:
        fields.append("grp=?"); args.append(group)
    if fields:
        args.append(p["id"])
        with _conn() as c:
            c.execute(f"UPDATE proxies SET {','.join(fields)} WHERE id=?", args)
    return get_proxy(p["id"])


def delete_proxy(pid: str) -> None:
    p = get_proxy(pid)
    with _conn() as c:
        c.execute("DELETE FROM proxies WHERE id=?", (p["id"],))


# A proxy is auto-disabled after this many consecutive failed checks.
AUTO_DISABLE_AFTER = 3


def record_proxy_check(pid: str, geo) -> dict:
    """Persist the latest health-check result (geo is a proxy.GeoInfo or None).

    Updates success/fail counters and auto-disables a proxy after
    AUTO_DISABLE_AFTER consecutive failures (the "kick bad proxies" behaviour).
    """
    p = get_proxy(pid)
    with _conn() as c:
        if geo is None:
            fails = (p["fail_count"] or 0) + 1
            enabled = 0 if fails >= AUTO_DISABLE_AFTER else (1 if p["enabled"] else 0)
            c.execute(
                "UPDATE proxies SET last_ok=0, fail_count=?, enabled=?, checked_at=? WHERE id=?",
                (fails, enabled, time.time(), p["id"]),
            )
        else:
            c.execute(
                "UPDATE proxies SET last_ok=1, fail_count=0, success_count=success_count+1, "
                "last_ip=?, last_country=?, last_cc=?, last_tz=?, checked_at=? WHERE id=?",
                (geo.ip, geo.country, geo.country_code, geo.timezone, time.time(), p["id"]),
            )
    return get_proxy(p["id"])


def check_all_proxies() -> dict:
    """Health-check every pool proxy; returns counts. Auto-disables dead ones."""
    from .proxy import check_and_locate
    ok = bad = 0
    for p in list_proxies():
        try:
            geo = check_and_locate(Proxy.parse(p["raw"]))
            record_proxy_check(p["id"], geo)
            ok += 1
        except Exception:
            record_proxy_check(p["id"], None)
            bad += 1
    return {"checked": ok + bad, "ok": ok, "failed": bad}


def next_enabled_proxy() -> Optional[dict]:
    """Round-robin an enabled proxy (rotation). Skips disabled ones."""
    pool = [p for p in list_proxies() if p["enabled"]]
    if not pool:
        return None
    # rotate by least-recently-checked to spread usage
    pool.sort(key=lambda p: p["checked_at"] or 0)
    return pool[0]


# ---------------------------------------------------------------------------
# Dynamic proxy providers (api_extract / rotating_gateway)
# ---------------------------------------------------------------------------

def _provider_row(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"], "label": r["label"], "kind": r["kind"], "url": r["url"],
        "note": r["note"], "last_count": r["last_count"], "refreshed_at": r["refreshed_at"],
    }


def list_providers() -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM proxy_providers ORDER BY created_at").fetchall()
    return [_provider_row(r) for r in rows]


def get_provider(pid: str) -> dict:
    with _conn() as c:
        r = c.execute("SELECT * FROM proxy_providers WHERE id=? OR label=?", (pid, pid)).fetchone()
    if not r:
        raise KeyError(f"provider not found: {pid}")
    return _provider_row(r)


def add_provider(kind: str, url: str, *, label: Optional[str] = None, note: str = "") -> dict:
    if kind not in ("api_extract", "rotating_gateway"):
        raise ValueError(f"unknown provider kind: {kind!r}")
    label = label or _next_label("proxy_providers", "provider")
    pid = uuid.uuid4().hex[:12]
    with _conn() as c:
        c.execute(
            "INSERT INTO proxy_providers (id,label,kind,url,note,created_at) VALUES (?,?,?,?,?,?)",
            (pid, label, kind, url, note, time.time()),
        )
    return get_provider(pid)


def delete_provider(pid: str) -> None:
    p = get_provider(pid)
    with _conn() as c:
        c.execute("DELETE FROM proxy_providers WHERE id=?", (p["id"],))


def refresh_provider(pid: str) -> dict:
    """Fetch proxies from the provider and add new ones to the pool."""
    from . import proxy_providers as pp
    prov = get_provider(pid)
    raws = pp.fetch(prov["kind"], prov["url"])
    existing = {p["raw"] for p in list_proxies()}
    added = []
    for raw in raws:
        if raw in existing:
            continue
        try:
            added.append(add_proxy(raw, source=prov["label"]))
            existing.add(raw)
        except Exception:
            pass
    with _conn() as c:
        c.execute("UPDATE proxy_providers SET last_count=?, refreshed_at=? WHERE id=?",
                  (len(raws), time.time(), prov["id"]))
    return {"fetched": len(raws), "added": len(added), "provider": get_provider(prov["id"])}


def _next_label(table: str, prefix: str) -> str:
    import re
    with _conn() as c:
        labels = {r[0] for r in c.execute(f"SELECT label FROM {table}").fetchall()}
    pat = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    used = [int(m.group(1)) for n in labels if (m := pat.match(n))]
    nxt = (max(used) + 1) if used else 1
    return f"{prefix}{nxt:02d}"
