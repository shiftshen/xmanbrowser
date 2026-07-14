"""Track running browser instances (one OS process per profile).

PIDs are persisted to a small JSON under the data dir so `status` survives an API
restart and stale entries get reaped. Liveness is checked against the real OS
process, not just our in-memory view.
"""
from __future__ import annotations

import json
import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from .profile import data_dir

HEARTBEAT_TIMEOUT = 5.0
STARTUP_GRACE = 90.0


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


def _heartbeat_file(profile_id: str) -> Path:
    path = data_dir() / "heartbeats"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{profile_id}.json"


def write_heartbeat(
    profile_id: str,
    *,
    pid: Optional[int] = None,
    at: Optional[float] = None,
    token: str = "",
    phase: str = "running",
) -> None:
    """Atomically record that a runner is still pumping browser events."""
    runner_pid = pid if pid is not None else os.getpid()
    heartbeat = _heartbeat_file(profile_id)
    temporary = heartbeat.with_suffix(f".{runner_pid}.tmp")
    temporary.write_text(json.dumps({
        "pid": runner_pid,
        "at": at if at is not None else time.time(),
        "token": token,
        "phase": phase,
    }))
    temporary.replace(heartbeat)


def clear_heartbeat(profile_id: str, *, pid: Optional[int] = None) -> None:
    """Remove a heartbeat, without deleting one written by a replacement runner."""
    heartbeat = _heartbeat_file(profile_id)
    if not heartbeat.exists():
        return
    if pid is not None:
        try:
            if int(json.loads(heartbeat.read_text())["pid"]) != pid:
                return
        except Exception:
            pass
    heartbeat.unlink(missing_ok=True)


def _heartbeat_fresh(
    profile_id: str,
    pid: int,
    *,
    now: Optional[float] = None,
    token: Optional[str] = None,
    started_at: Optional[float] = None,
) -> Optional[bool]:
    """Return freshness for this PID, or None for a legacy/mismatched runner."""
    heartbeat = _heartbeat_file(profile_id)
    current_time = now if now is not None else time.time()
    if not heartbeat.exists():
        if token is None:
            return None
        return started_at is not None and current_time - started_at <= STARTUP_GRACE
    try:
        payload = json.loads(heartbeat.read_text())
        if int(payload["pid"]) != pid:
            return None if token is None else False
        if token is not None and payload.get("token") != token:
            return False
        if token is not None and payload.get("phase") == "starting":
            return started_at is not None and current_time - started_at <= STARTUP_GRACE
        age = current_time - float(payload["at"])
        return age <= HEARTBEAT_TIMEOUT
    except Exception:
        return False


def _process_matches_runner(pid: int, token: str) -> Optional[bool]:
    """Return True/False for match/mismatch, or None when probing failed."""
    if not token:
        return False
    try:
        if os.name == "nt":
            completed = subprocess.run(
                [
                    "powershell", "-NoProfile", "-NonInteractive", "-Command",
                    f"(Get-CimInstance Win32_Process -Filter 'ProcessId = {int(pid)}').CommandLine",
                ],
                capture_output=True,
                text=True,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            )
        else:
            completed = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True,
                text=True,
                check=False,
            )
        if completed.returncode != 0 or not completed.stdout.strip():
            return None
        command = completed.stdout
        return token in command and "runner" in command
    except Exception:
        return None


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
    live: dict[str, dict] = {}
    for profile_id, rec in d.items():
        pid = rec["pid"]
        process_alive = _alive(pid)
        token = rec.get("run_token")
        heartbeat_fresh = _heartbeat_fresh(
            profile_id,
            pid,
            token=token,
            started_at=rec.get("started_at"),
        )
        if process_alive and heartbeat_fresh is not False:
            live[profile_id] = rec
            continue
        if process_alive and heartbeat_fresh is False and token:
            identity = _process_matches_runner(pid, token)
            if identity is None:
                live[profile_id] = rec
                continue
            if identity:
                _terminate_process_tree(pid)
        clear_heartbeat(profile_id, pid=pid)
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

    # In a PyInstaller-frozen sidecar there is no `python -m`; re-invoke the
    # frozen exe with the "runner" subcommand instead.
    frozen = getattr(sys, "frozen", False)
    run_token = secrets.token_hex(16)
    if frozen:
        cmd = [sys.executable, "runner", profile_id, "--url", url]
    else:
        cmd = [sys.executable, "-m", "xman.runner", profile_id, "--url", url]
    cmd.extend(["--run-token", run_token])
    if headless:
        cmd.append("--headless")
    # Capture the runner's output to a per-profile log so launch failures (e.g. a
    # browser that crashes on start) are diagnosable instead of vanishing.
    from .profile import data_dir
    logdir = data_dir() / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    logf = open(logdir / f"launch-{profile_id}.log", "w", buffering=1)
    # Detach into its own process group so terminating the API won't kill browsers.
    # POSIX: new session. Windows: new process group (no setsid).
    popen_kw: dict = {
        "stdout": logf,
        "stderr": subprocess.STDOUT,
        "env": {**os.environ},
    }
    # A frozen (PyInstaller onedir) re-invocation must run from the exe's own
    # directory; otherwise Windows can't resolve the sidecar's _internal DLLs and
    # the child dies with 0xc0000142 (STATUS_DLL_INIT_FAILED).
    if frozen:
        popen_kw["cwd"] = os.path.dirname(os.path.abspath(sys.executable))
    if os.name == "nt":
        # New group so Ctrl-C on the API won't kill browsers; no console window
        # (the sidecar is a console-subsystem exe — a window would flash).
        flags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        popen_kw["creationflags"] = flags
    else:
        popen_kw["start_new_session"] = True
    clear_heartbeat(profile_id)
    proc = subprocess.Popen(cmd, **popen_kw)
    logf.close()  # the child keeps its own inherited handle
    rec = {"pid": proc.pid, "started_at": time.time(), "run_token": run_token}
    d[profile_id] = rec
    _save(d)
    return {"profile_id": profile_id, "pid": proc.pid, "already_running": False}


def _terminate_process_tree(pid: int) -> bool:
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


def stop(profile_id: str) -> bool:
    d = _reap(_load())
    rec = d.get(profile_id)
    if not rec:
        return False
    pid = rec["pid"]
    token = rec.get("run_token")
    if token:
        identity = _process_matches_runner(pid, token)
        if identity is None:
            return False
        if identity is False:
            d.pop(profile_id, None)
            _save(d)
            clear_heartbeat(profile_id, pid=pid)
            return False
    stopped = _terminate_process_tree(pid)
    if stopped:
        d.pop(profile_id, None)
        _save(d)
        clear_heartbeat(profile_id, pid=pid)
    return stopped


def stop_all() -> int:
    n = 0
    for pid_key in list(_reap(_load()).keys()):
        if stop(pid_key):
            n += 1
    return n
