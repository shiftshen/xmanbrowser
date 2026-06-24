"""Capture acceptance screenshots from detection sites for a profile.

    python tools/capture_browserleaks.py [profile_name]

Visits a few browserleaks pages headless and saves full-page screenshots under
./acceptance/. Used as M1 evidence (fingerprint present, no automation tells).
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

PAGES = {
    "webgl": "https://browserleaks.com/webgl",
    "canvas": "https://browserleaks.com/canvas",
    "javascript": "https://browserleaks.com/javascript",
    "webrtc": "https://browserleaks.com/webrtc",
}


def main():
    from xman.profile import Profile, create_profile
    from xman.launcher import launch

    name = sys.argv[1] if len(sys.argv) > 1 else None
    if name:
        prof = Profile.load(name)
    else:
        os.environ.setdefault("XMAN_HOME", tempfile.mkdtemp(prefix="xman_cap_"))
        prof = create_profile("capture", os_name="macos", seed=2025)

    outdir = Path("acceptance")
    outdir.mkdir(exist_ok=True)
    print(f"profile: {prof.name} ({prof.fingerprint.os})  proxy={prof.proxy_raw or 'none'}")

    with launch(prof, headless=True) as browser:
        page = browser.new_page()
        page.set_viewport_size({"width": 1280, "height": 1400})
        for key, url in PAGES.items():
            try:
                page.goto(url, wait_until="networkidle", timeout=45000)
                page.wait_for_timeout(2500)  # let JS probes settle
            except Exception as e:
                print(f"  [{key}] load warning: {e}")
            dest = outdir / f"browserleaks_{key}.png"
            page.screenshot(path=str(dest), full_page=True)
            print(f"  saved {dest}")
    print("done")


if __name__ == "__main__":
    main()
