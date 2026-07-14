"""Run one profile's browser as a standalone, long-lived process.

Invoked by the manager as:  python -m xman.runner <profile_id> [--url URL]
Holds the Camoufox window open until the user closes it or the process is
terminated (SIGTERM/SIGINT). Keeping each browser in its own OS process means a
crash or close of one profile never affects the others or the API service.
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import time

_should_stop = False
HEARTBEAT_INTERVAL = 2.0


def _handle(signum, frame):
    global _should_stop
    _should_stop = True


def _pump_browser_events(ctx, interval_ms: int = 400) -> bool:
    """Keep the sync Playwright transport flowing and detect a dead browser."""
    pages = list(ctx.pages)
    if not pages:
        return False
    attempted = set()
    while pages:
        page = pages[-1]
        attempted.add(id(page))
        try:
            page.wait_for_timeout(interval_ms)
            return bool(ctx.pages)
        except Exception as exc:
            remaining = [candidate for candidate in list(ctx.pages) if id(candidate) not in attempted]
            if remaining:
                pages = remaining
                continue
            if _is_expected_browser_close(exc) or not ctx.pages:
                return False
            raise


def _heartbeat_due(*, last_at: float, now: float) -> bool:
    return now - last_at >= HEARTBEAT_INTERVAL


def _is_expected_browser_close(exc: BaseException) -> bool:
    message = str(exc).casefold()
    return (
        "target page, context or browser has been closed" in message
        or "connection closed while reading from the driver" in message
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("profile_id")
    ap.add_argument("--url", default="about:blank")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--run-token", default="")
    args = ap.parse_args()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)

    from .store import get
    from .launcher import launch

    prof = get(args.profile_id)
    print(f"LAUNCH {prof.id} {prof.name} engine={prof.fingerprint.engine} os={prof.fingerprint.os}", flush=True)
    if prof.fingerprint.engine != "chromium":
        try:
            from camoufox.pkgman import INSTALL_DIR, launch_path
            print(f"camoufox INSTALL_DIR={INSTALL_DIR} exe={launch_path()}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"camoufox path probe failed: {e}", flush=True)
    try:
        _run(prof, args)
    except BaseException:  # noqa: BLE001 — log the real reason the browser died
        import traceback
        print("LAUNCH FAILED:\n" + traceback.format_exc(), flush=True)
        return 1
    return 0


def _run(prof, args) -> None:
    from .launcher import launch
    from .manager import clear_heartbeat, write_heartbeat

    try:
        try:
            with launch(prof, headless=args.headless) as ctx:
                # A persistent context already opens with one blank page — reuse it
                # instead of calling new_page(), which would leave the user with 2 tabs.
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                # Mark the bounded startup/navigation phase before goto. The
                # manager gives this phase a longer grace period than a running
                # browser, so a legal 45-second navigation cannot be mistaken
                # for a stalled transport.
                write_heartbeat(
                    prof.id, pid=os.getpid(), token=args.run_token, phase="starting",
                )
                if args.url and args.url != "about:blank":
                    try:
                        page.goto(args.url, wait_until="domcontentloaded", timeout=45000)
                    except Exception as e:  # noqa: BLE001 - navigation failures shouldn't kill the window
                        print(f"nav warning: {e}", file=sys.stderr)
                write_heartbeat(
                    prof.id, pid=os.getpid(), token=args.run_token, phase="running",
                )
                print(f"READY {prof.id} {prof.name}", flush=True)

                # A sync Playwright connection must keep pumping events. A plain
                # time.sleep lets transport messages accumulate and can leave a
                # dead browser behind a live runner/driver process.
                last_heartbeat = time.monotonic()
                while not _should_stop:
                    if not _pump_browser_events(ctx):
                        break
                    now = time.monotonic()
                    if _heartbeat_due(last_at=last_heartbeat, now=now):
                        write_heartbeat(prof.id, pid=os.getpid(), token=args.run_token)
                        last_heartbeat = now
        except BaseException as exc:  # normal window close can make context cleanup race
            if not _is_expected_browser_close(exc):
                raise
    finally:
        clear_heartbeat(prof.id, pid=os.getpid())
    print(f"STOPPED {prof.id}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
