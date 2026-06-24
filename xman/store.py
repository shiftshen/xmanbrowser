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
"""


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
    name: str,
    *,
    os_name: str = "macos",
    proxy_raw: Optional[str] = None,
    group: str = "default",
    note: str = "",
    seed: Optional[int] = None,
) -> Profile:
    if proxy_raw:
        Proxy.parse(proxy_raw)  # validate
    spec = generate_spec(os_name, seed=seed)
    prof = Profile(id=uuid.uuid4().hex[:12], name=name, fingerprint=spec,
                   proxy_raw=proxy_raw, group=group, note=note)
    _insert(prof)
    return prof


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
    return prof
