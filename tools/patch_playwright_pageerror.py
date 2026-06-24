"""Patch a Playwright-Firefox driver crash.

Camoufox's Firefox sometimes emits a `pageError` event with no `location`
(common with ad/analytics scripts on sites like browserleaks). The bundled
Playwright Node driver does `pageError.location.url` unguarded and crashes the
*entire* browser process — taking down any automation/navigation.

This rewrites those accesses to optional chaining (`?.`). Idempotent; safe to
re-run after `pip install` re-vendors the driver.

    python tools/patch_playwright_pageerror.py
"""
from __future__ import annotations

import pathlib
import sys

import playwright

BROKEN = """location: {
              url: pageError.location.url,
              line: pageError.location.lineNumber,
              column: pageError.location.columnNumber
            }"""

FIXED = """location: {
              url: pageError.location?.url ?? "",
              line: pageError.location?.lineNumber ?? 0,
              column: pageError.location?.columnNumber ?? 0
            }"""


def main() -> int:
    root = pathlib.Path(playwright.__file__).parent
    target = root / "driver" / "package" / "lib" / "coreBundle.js"
    if not target.exists():
        print(f"driver bundle not found: {target}", file=sys.stderr)
        return 1
    src = target.read_text()
    if 'pageError.location?.url ?? ""' in src:
        print("already patched")
        return 0
    n = src.count(BROKEN)
    if n == 0:
        print("expected pattern not found (driver version changed?) — not patched", file=sys.stderr)
        return 2
    target.write_text(src.replace(BROKEN, FIXED))
    print(f"patched {n} occurrence(s) in {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
