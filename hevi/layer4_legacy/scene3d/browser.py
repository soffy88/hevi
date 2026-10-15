"""Locate a Playwright Chromium bundle for the SCENE3D renderer.

Playwright normally stores its browsers in ``~/.cache/ms-playwright``.  On this
CPU-only host that cache can be missing (it is a disposable download), while a
compatible bundle may already exist elsewhere.  Rather than hard-failing — or
silently skipping the render — we resolve a usable bundle in this order:

1. ``PLAYWRIGHT_BROWSERS_PATH`` if it is already set and contains Chromium.
2. ``SCENE3D_PLAYWRIGHT_BROWSERS`` (an explicit opt-in override).
3. The default ``~/.cache/ms-playwright``.

The resolver only *reads* the filesystem; it never downloads or deletes.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["has_chromium", "resolve_browsers_path", "chromium_available"]

_CANDIDATE_BINARIES = (
    "chrome-linux64/chrome",
    "chrome-linux/chrome",
    "chrome-headless-shell-linux64/chrome-headless-shell",
    "chrome-linux/headless_shell",
)


def _dir_has_chromium(path: Path) -> bool:
    if not path.is_dir():
        return False
    for sub in path.iterdir():
        if not sub.is_dir() or "chromium" not in sub.name:
            continue
        for cand in _CANDIDATE_BINARIES:
            if (sub / cand).is_file():
                return True
    return False


def has_chromium(browsers_path: str | Path | None = None) -> bool:
    """Whether ``browsers_path`` (or the default cache) contains Chromium."""
    if browsers_path is None:
        browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if browsers_path is None:
        browsers_path = Path.home() / ".cache" / "ms-playwright"
    return _dir_has_chromium(Path(browsers_path))


def resolve_browsers_path() -> str | None:
    """Return a usable browsers dir and export it for Playwright, else ``None``.

    The first candidate that actually contains Chromium wins.  The chosen path
    is written back to ``PLAYWRIGHT_BROWSERS_PATH`` so a later
    ``playwright.sync_api`` launch picks it up.
    """
    candidates: list[Path] = []
    for env_key in ("PLAYWRIGHT_BROWSERS_PATH", "SCENE3D_PLAYWRIGHT_BROWSERS"):
        val = os.environ.get(env_key)
        if val:
            candidates.append(Path(val))
    candidates.append(Path.home() / ".cache" / "ms-playwright")
    for cand in candidates:
        if _dir_has_chromium(cand):
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(cand)
            return str(cand)
    return None


def chromium_available() -> bool:
    """Public predicate for tests: is a Chromium bundle resolvable?"""
    return resolve_browsers_path() is not None or Path("/snap/chromium/current/usr/lib/chromium-browser/chrome").is_file()
