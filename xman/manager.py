"""Track running browser instances (one OS process per profile).

PIDs are persisted to a small JSON under the data dir so `status` survives an API
restart and stale entries get reaped. Liveness is checked against the real OS
process, not just our in-memory view.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from .profile import data_dir


def _runtime_file() -> Path:
    data_dir().mkdir(parents=True, exist_ok=True)
    return data_dir() / "running.json"


def _load() -> dict[str, dict]:
    f = _runtime_file()
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text())
    except Exception:
        return {}


def _save(d: dict[str, dict]) -> None:
    _runtime_file().write_text(json.dumps(d, indent=2))


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return pid_exists_fallback(pid)
    except Exception:
        return False


def pid_exists_fallback(pid: int) -> bool:
    # PermissionError means the pid exists but isn't ours — still "alive".
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _reap(d: dict[str, dict]) -> dict[str, dict]:
    live = {pid: rec for pid, rec in d.items() if _alive(rec["pid"])}
    if len(live) != len(d):
        _save(live)
    return live


def is_running(profile_id: str) -> bool:
    return profile_id in _reap(_load())


def status() -> list[dict]:
    out = []
    for pid_key, rec in _reap(_load()).items():
        out.append({"profile_id": pid_key, "pid": rec["pid"], "started_at": rec.get("started_at")})
    return out


def launch(profile_id: str, *, url: str = "about:blank", headless: bool = False) -> dict:
    d = _reap(_load())
    if profile_id in d:
        return {"profile_id": profile_id, "pid": d[profile_id]["pid"], "already_running": True}

    cmd = [sys.executable, "-m", "xman.runner", profile_id, "--url", url]
    if headless:
        cmd.append("--headless")
    # Detach into its own process group so terminating the API won't kill browsers.
    # POSIX: new session. Windows: new process group (no setsid).
    popen_kw: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "env": {**os.environ},
    }
    if os.name == "nt":
        popen_kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        popen_kw["start_new_session"] = True
    proc = subprocess.Popen(cmd, **popen_kw)
    rec = {"pid": proc.pid, "started_at": time.time()}
    d[profile_id] = rec
    _save(d)
    return {"profile_id": profile_id, "pid": proc.pid, "already_running": False}


def stop(profile_id: str) -> bool:
    d = _reap(_load())
    rec = d.pop(profile_id, None)
    _save(d)
    if not rec:
        return False
    pid = rec["pid"]
    if os.name == "nt":
        # Force-kill the whole tree (runner + Camoufox children).
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
        except Exception:
            return False
        return True
    try:
        # Kill the whole process group (runner + its Camoufox child).
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except ProcessLookupError:
        return True
    except Exception:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            return False
    return True


def stop_all() -> int:
    n = 0
    for pid_key in list(_reap(_load()).keys()):
        if stop(pid_key):
            n += 1
    return n
