#!/usr/bin/env python3
"""Fail a release if its macOS updater archive is unsafe for Tauri extraction."""

from __future__ import annotations

import sys
import tarfile
from pathlib import PurePosixPath


def verify(archive_path: str, expected_root: str) -> int:
    entries = 0
    has_info_plist = False
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive:
            parts = PurePosixPath(member.name).parts
            if not parts or parts[0] != expected_root:
                raise ValueError(f"unexpected updater archive root: {member.name}")
            if any(part.startswith("._") for part in parts):
                raise ValueError(f"AppleDouble metadata is not updater-safe: {member.name}")
            stripped = parts[1:]
            if not stripped and not member.isdir():
                raise ValueError(f"entry becomes an empty Tauri extraction path: {member.name}")
            if stripped == ("Contents", "Info.plist"):
                has_info_plist = True
            entries += 1
    if not entries or not has_info_plist:
        raise ValueError("archive is missing XmanBrowser.app/Contents/Info.plist")
    print(f"updater archive valid: {entries} entries, no AppleDouble metadata")
    return entries


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: verify_updater_archive.py ARCHIVE EXPECTED_ROOT")
    try:
        verify(sys.argv[1], sys.argv[2])
    except (OSError, tarfile.TarError, ValueError) as error:
        raise SystemExit(f"invalid updater archive: {error}") from error
