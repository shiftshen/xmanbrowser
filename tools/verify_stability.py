"""M1 acceptance: launch profiles headless and read the *real* in-browser
fingerprint to prove:

  1. same profile, two launches  -> identical fingerprint (stable)
  2. two different profiles       -> different fingerprints
  3. isolation: each profile has its own user-data-dir / storage

Run:
    python tools/verify_stability.py [profile_name]
If no profile is given, two throwaway profiles are created under a temp XMAN_HOME.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile

# Probe executed inside the page; returns the fingerprint surfaces we care about.
PROBE = r"""
() => {
  const gl = document.createElement('canvas').getContext('webgl');
  const dbg = gl && gl.getExtension('WEBGL_debug_renderer_info');
  // canvas 2d hash (text + shapes) — sensitive to canvas noise injection
  const c = document.createElement('canvas'); c.width = 240; c.height = 60;
  const ctx = c.getContext('2d');
  ctx.textBaseline = 'top'; ctx.font = "16px 'Arial'";
  ctx.fillStyle = '#f60'; ctx.fillRect(2, 2, 120, 30);
  ctx.fillStyle = '#069'; ctx.fillText('XMan fingerprint ⚡', 4, 18);
  ctx.strokeStyle = 'rgba(0,80,160,0.7)'; ctx.beginPath();
  ctx.arc(60, 30, 20, 0, Math.PI * 2); ctx.stroke();
  return {
    userAgent: navigator.userAgent,
    platform: navigator.platform,
    hardwareConcurrency: navigator.hardwareConcurrency,
    deviceMemory: navigator.deviceMemory ?? null,
    languages: navigator.languages,
    language: navigator.language,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    screen: [screen.width, screen.height, screen.colorDepth],
    webglVendor: dbg ? gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) : null,
    webglRenderer: dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : null,
    canvasData: c.toDataURL(),
    webdriver: navigator.webdriver,
  };
}
"""


def read_fingerprint(profile, *, url="about:blank"):
    from xman.launcher import launch
    with launch(profile, headless=True) as browser:
        page = browser.new_page()
        if url != "about:blank":
            page.goto(url, wait_until="domcontentloaded")
        data = page.evaluate(PROBE)
    # collapse canvas image to a short hash for readable comparison
    data["canvasHash"] = hashlib.sha256(data.pop("canvasData").encode()).hexdigest()[:16]
    return data


def _diff(a: dict, b: dict):
    return {k: (a.get(k), b.get(k)) for k in set(a) | set(b) if a.get(k) != b.get(k)}


def main():
    from xman.profile import Profile, create_profile

    name = sys.argv[1] if len(sys.argv) > 1 else None
    created_tmp = False
    if name:
        p1 = Profile.load(name)
        p2 = create_profile(f"_verify_other_{os.getpid()}", os_name=p1.fingerprint.os)
        created_tmp = True
    else:
        os.environ.setdefault("XMAN_HOME", tempfile.mkdtemp(prefix="xman_verify_"))
        p1 = create_profile("verify_a", os_name="macos", seed=111)
        p2 = create_profile("verify_b", os_name="macos", seed=222)
        created_tmp = True

    print(f"== launch 1 of '{p1.name}' ==")
    f1 = read_fingerprint(p1)
    print(json.dumps(f1, indent=2, ensure_ascii=False))

    print(f"\n== launch 2 of '{p1.name}' (stability) ==")
    f2 = read_fingerprint(p1)

    print(f"\n== launch of different profile '{p2.name}' ==")
    g = read_fingerprint(p2)

    stable = _diff(f1, f2)
    differ = _diff(f1, g)

    print("\n----- RESULTS -----")
    ok = True
    if stable:
        ok = False
        print(f"[FAIL] same profile changed across launches: {stable}")
    else:
        print("[PASS] same profile -> identical fingerprint across 2 launches")

    # different profiles must differ on identity surfaces (not necessarily tz)
    identity_keys = {"userAgent", "hardwareConcurrency", "screen", "webglRenderer", "canvasHash"}
    differing_identity = identity_keys & set(differ)
    if differing_identity:
        print(f"[PASS] different profiles differ on: {sorted(differing_identity)}")
    else:
        ok = False
        print("[FAIL] two profiles produced the same identity surfaces")

    if f1.get("webdriver"):
        ok = False
        print(f"[FAIL] navigator.webdriver is truthy: {f1['webdriver']}")
    else:
        print("[PASS] navigator.webdriver not exposed")

    print("\nRESULT:", "ALL GREEN ✅" if ok else "ISSUES ❌")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
