"""Regression tests for long-running browser responsiveness and reaping."""

import json
from types import SimpleNamespace

import pytest

from xman import manager, runner


class _Page:
    def __init__(self, error=None, on_wait=None):
        self.error = error
        self.on_wait = on_wait
        self.waits = []

    def wait_for_timeout(self, milliseconds):
        self.waits.append(milliseconds)
        if self.on_wait:
            self.on_wait(self)
        if self.error:
            raise self.error


class _Context:
    def __init__(self, pages):
        self.pages = pages


def test_runner_pumps_playwright_transport_instead_of_sleeping():
    page = _Page()
    assert runner._pump_browser_events(_Context([page]), 400) is True
    assert page.waits == [400]


@pytest.mark.parametrize("pages", [
    [],
    [_Page(RuntimeError("Target page, context or browser has been closed"))],
])
def test_runner_stops_when_browser_transport_is_gone(pages):
    assert runner._pump_browser_events(_Context(pages), 400) is False


def test_runner_keeps_session_when_one_of_multiple_pages_closes():
    remaining = _Page()
    context = _Context([])
    closing = _Page(
        RuntimeError("Target page, context or browser has been closed"),
        on_wait=lambda page: context.pages.remove(page),
    )
    context.pages = [remaining, closing]

    assert runner._pump_browser_events(context, 400) is True
    assert closing.waits == [400]
    assert remaining.waits == [400]


def test_runner_surfaces_unexpected_transport_errors():
    with pytest.raises(RuntimeError, match="protocol corruption"):
        runner._pump_browser_events(_Context([_Page(RuntimeError("protocol corruption"))]), 400)


def test_heartbeat_write_is_throttled_independently_from_event_pump():
    assert runner._heartbeat_due(last_at=100.0, now=101.9) is False
    assert runner._heartbeat_due(last_at=100.0, now=102.0) is True


def test_runner_marks_starting_before_navigation(monkeypatch):
    events = []
    context = _Context([])

    class Page(_Page):
        def goto(self, *args, **kwargs):
            events.append("goto")

        def wait_for_timeout(self, milliseconds):
            context.pages.clear()
            raise RuntimeError("Target page, context or browser has been closed")

    class LaunchContext:
        def __enter__(self):
            return context

        def __exit__(self, *args):
            return False

    context.pages = [Page()]
    monkeypatch.setattr("xman.launcher.launch", lambda *args, **kwargs: LaunchContext())
    monkeypatch.setattr(
        "xman.manager.write_heartbeat",
        lambda *args, phase="running", **kwargs: events.append(phase),
    )
    monkeypatch.setattr("xman.manager.clear_heartbeat", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, "_should_stop", False)

    runner._run(
        SimpleNamespace(id="profile", name="Profile"),
        SimpleNamespace(headless=True, url="https://example.test", run_token="token"),
    )

    assert events[:3] == ["starting", "goto", "running"]


@pytest.mark.parametrize("message", [
    "BrowserContext.close: Target page, context or browser has been closed",
    "BrowserContext.close: Connection closed while reading from the driver",
])
def test_expected_browser_close_is_not_reported_as_launch_failure(message):
    assert runner._is_expected_browser_close(RuntimeError(message)) is True
    assert runner._is_expected_browser_close(RuntimeError("proxy authentication failed")) is False


def test_heartbeat_freshness_is_pid_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv("XMAN_HOME", str(tmp_path))

    assert manager._heartbeat_fresh("profile", 123, now=100.0) is None
    manager.write_heartbeat("profile", pid=123, at=100.0)
    assert manager._heartbeat_fresh("profile", 123, now=104.0) is True
    assert manager._heartbeat_fresh("profile", 123, now=106.0) is False
    assert manager._heartbeat_fresh("profile", 456, now=101.0) is None


def test_starting_heartbeat_uses_startup_grace_not_running_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("XMAN_HOME", str(tmp_path))
    manager.write_heartbeat("profile", pid=123, at=1.0, token="run", phase="starting")

    assert manager._heartbeat_fresh(
        "profile", 123, now=50.0, token="run", started_at=1.0,
    ) is True
    assert manager._heartbeat_fresh(
        "profile", 123, now=manager.STARTUP_GRACE + 2.0, token="run", started_at=1.0,
    ) is False


def test_running_heartbeat_still_uses_short_stall_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("XMAN_HOME", str(tmp_path))
    manager.write_heartbeat("profile", pid=123, at=1.0, token="run", phase="running")

    assert manager._heartbeat_fresh(
        "profile", 123, now=1.0 + manager.HEARTBEAT_TIMEOUT + 1, token="run", started_at=1.0,
    ) is False


def test_reap_terminates_runner_with_stale_matching_heartbeat(tmp_path, monkeypatch):
    monkeypatch.setenv("XMAN_HOME", str(tmp_path))
    manager._runtime_file().write_text(json.dumps({
        "profile": {"pid": 123, "started_at": 50.0},
    }))
    manager.write_heartbeat("profile", pid=123, at=90.0, token="run-123")
    data = manager._load()
    data["profile"]["run_token"] = "run-123"
    manager._save(data)
    terminated = []
    monkeypatch.setattr(manager, "_alive", lambda pid: True)
    monkeypatch.setattr(manager, "_process_matches_runner", lambda pid, token: True)
    monkeypatch.setattr(manager, "_terminate_process_tree", terminated.append)
    monkeypatch.setattr(manager.time, "time", lambda: 100.0)

    assert manager._reap(manager._load()) == {}
    assert terminated == [123]
    assert not manager._heartbeat_file("profile").exists()


def test_current_runner_without_heartbeat_is_reaped_after_startup_grace(tmp_path, monkeypatch):
    monkeypatch.setenv("XMAN_HOME", str(tmp_path))
    record = {"pid": 123, "started_at": 1.0, "run_token": "current-token"}
    manager._save({"profile": record})
    terminated = []
    monkeypatch.setattr(manager, "_alive", lambda pid: True)
    monkeypatch.setattr(manager, "_process_matches_runner", lambda pid, token: True)
    monkeypatch.setattr(manager, "_terminate_process_tree", terminated.append)
    monkeypatch.setattr(manager.time, "time", lambda: 1.0 + manager.STARTUP_GRACE + 1)

    assert manager._reap(manager._load()) == {}
    assert terminated == [123]


def test_legacy_runner_without_heartbeat_keeps_pid_only_compatibility(tmp_path, monkeypatch):
    monkeypatch.setenv("XMAN_HOME", str(tmp_path))
    record = {"pid": 123, "started_at": 1.0}
    manager._save({"profile": record})
    monkeypatch.setattr(manager, "_alive", lambda pid: True)
    monkeypatch.setattr(manager.time, "time", lambda: 999.0)

    assert manager._reap(manager._load()) == {"profile": record}


def test_reap_never_kills_a_reused_unrelated_pid(tmp_path, monkeypatch):
    monkeypatch.setenv("XMAN_HOME", str(tmp_path))
    record = {"pid": 123, "started_at": 1.0, "run_token": "old-token"}
    manager._save({"profile": record})
    manager.write_heartbeat("profile", pid=123, at=1.0, token="old-token")
    terminated = []
    monkeypatch.setattr(manager, "_alive", lambda pid: True)
    monkeypatch.setattr(manager, "_process_matches_runner", lambda pid, token: False)
    monkeypatch.setattr(manager, "_terminate_process_tree", terminated.append)
    monkeypatch.setattr(manager.time, "time", lambda: 999.0)

    assert manager._reap(manager._load()) == {}
    assert terminated == []


def test_reap_preserves_state_when_process_identity_probe_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("XMAN_HOME", str(tmp_path))
    record = {"pid": 123, "started_at": 1.0, "run_token": "current-token"}
    manager._save({"profile": record})
    manager.write_heartbeat("profile", pid=123, at=1.0, token="current-token")
    monkeypatch.setattr(manager, "_alive", lambda pid: True)
    monkeypatch.setattr(manager, "_process_matches_runner", lambda pid, token: None)
    monkeypatch.setattr(manager.time, "time", lambda: 999.0)

    assert manager._reap(manager._load()) == {"profile": record}
    assert manager._heartbeat_file("profile").exists()


def test_stop_preserves_state_when_process_identity_probe_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("XMAN_HOME", str(tmp_path))
    record = {"pid": 123, "started_at": 1.0, "run_token": "current-token"}
    manager._save({"profile": record})
    manager.write_heartbeat("profile", pid=123, at=10.0, token="current-token")
    monkeypatch.setattr(manager, "_alive", lambda pid: True)
    monkeypatch.setattr(manager, "_process_matches_runner", lambda pid, token: None)
    monkeypatch.setattr(manager.time, "time", lambda: 10.0)

    assert manager.stop("profile") is False
    assert manager._load() == {"profile": record}
    assert manager._heartbeat_file("profile").exists()


def test_process_identity_probe_failure_is_unknown(monkeypatch):
    monkeypatch.setattr(manager.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("ps unavailable")))

    assert manager._process_matches_runner(123, "run-token") is None
