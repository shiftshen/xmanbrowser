"""Profile model + JSON storage (M1).

A profile bundles a stable fingerprint, an optional proxy, an isolated
user-data-dir, and metadata. M1 persists profiles as JSON files under a data
dir; M2 will move this behind SQLite while keeping the same shape.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .fingerprint import FingerprintSpec, generate_spec
from .proxy import Proxy


def data_dir() -> Path:
    """Root data dir for XMan (overridable via XMAN_HOME)."""
    root = os.environ.get("XMAN_HOME")
    base = Path(root) if root else Path.home() / ".xman"
    return base


def profiles_dir() -> Path:
    d = data_dir() / "profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class Profile:
    id: str
    name: str
    fingerprint: FingerprintSpec
    proxy_raw: Optional[str] = None  # original proxy string as entered
    group: str = "default"
    note: str = ""

    @property
    def user_data_dir(self) -> Path:
        # Pure path — no side effect on read (GET /api/profiles/{id} shouldn't
        # create directories). The dir is created at launch via ensure_user_data_dir().
        return data_dir() / "userdata" / self.id

    def ensure_user_data_dir(self) -> Path:
        d = self.user_data_dir
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def proxy(self) -> Optional[Proxy]:
        return Proxy.parse(self.proxy_raw) if self.proxy_raw else None

    # --- persistence ---
    def path(self) -> Path:
        return profiles_dir() / f"{self.id}.json"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "group": self.group,
            "note": self.note,
            "proxy_raw": self.proxy_raw,
            "fingerprint": self.fingerprint.to_dict(),
        }

    def save(self) -> Path:
        p = self.path()
        p.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))
        return p

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        return cls(
            id=d["id"],
            name=d["name"],
            fingerprint=FingerprintSpec.from_dict(d["fingerprint"]),
            proxy_raw=d.get("proxy_raw"),
            group=d.get("group", "default"),
            note=d.get("note", ""),
        )

    @classmethod
    def load(cls, profile_id: str) -> "Profile":
        p = profiles_dir() / f"{profile_id}.json"
        if not p.exists():
            # allow load by name
            for f in profiles_dir().glob("*.json"):
                d = json.loads(f.read_text())
                if d.get("name") == profile_id:
                    return cls.from_dict(d)
            raise FileNotFoundError(f"profile not found: {profile_id}")
        return cls.from_dict(json.loads(p.read_text()))


def create_profile(
    name: str,
    *,
    os_name: str = "macos",
    proxy_raw: Optional[str] = None,
    group: str = "default",
    note: str = "",
    seed: Optional[int] = None,
) -> Profile:
    spec = generate_spec(os_name, seed=seed)
    prof = Profile(
        id=uuid.uuid4().hex[:12],
        name=name,
        fingerprint=spec,
        proxy_raw=proxy_raw,
        group=group,
        note=note,
    )
    prof.save()
    return prof


def list_profiles() -> list[Profile]:
    out = []
    for f in sorted(profiles_dir().glob("*.json")):
        try:
            out.append(Profile.from_dict(json.loads(f.read_text())))
        except Exception:
            continue
    return out
