"""Run one profile's browser as a standalone, long-lived process.

Invoked by the manager as:  python -m xman.runner <profile_id> [--url URL]
Holds the Camoufox window open until the user closes it or the process is
terminated (SIGTERM/SIGINT). Keeping each browser in its own OS process means a
crash or close of one profile never affects the others or the API service.
"""
from __future__ import annotations

import argparse
import signal
import sys
import time

_should_stop = False


def _handle(signum, frame):
    global _should_stop
    _should_stop = True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("profile_id")
    ap.add_argument("--url", default="about:blank")
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)

    from .store import get
    from .launcher import launch

    prof = get(args.profile_id)
    with launch(prof, headless=args.headless) as ctx:
        page = ctx.new_page()
        if args.url and args.url != "about:blank":
            try:
                page.goto(args.url, wait_until="domcontentloaded", timeout=45000)
            except Exception as e:  # noqa: BLE001 - navigation failures shouldn't kill the window
                print(f"nav warning: {e}", file=sys.stderr)
        print(f"READY {prof.id} {prof.name}", flush=True)

        # Stay alive until the user closes the last window or we're asked to stop.
        while not _should_stop:
            try:
                if not ctx.pages:  # all windows closed by the user
                    break
            except Exception:
                break  # context/browser gone
            time.sleep(0.4)
    print(f"STOPPED {prof.id}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
