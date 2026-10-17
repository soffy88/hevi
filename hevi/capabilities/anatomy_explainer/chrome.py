"""Locate a working headless Chromium for the Anatomy kit scripts.

The vendored kit scripts (``third_party/anatomy/scripts/*.mjs``) take a
``CHROME_PATH`` environment variable and fall back to a list of well-known
binaries.  On this host the distro binary is a snap that cannot start without
its private ``/tmp`` mount, so "the first file that exists" is not enough: we
*probe* every candidate with a real headless launch and only hand a binary to
the kit that actually answered.  CPU only: the probe and every later launch use
``--enable-unsafe-swiftshader`` (no GPU required).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from hevi.capabilities.errors import CapabilityError

__all__ = ["chrome_candidates", "resolve_chrome", "chrome_env", "ChromeUnavailable"]

#: Flags every kit script uses.  ``--enable-unsafe-swiftshader`` keeps WebGL on
#: a CPU-only box; ``--no-sandbox`` is required in containers.
SWIFTSHADER_FLAGS = ("--enable-unsafe-swiftshader", "--no-sandbox", "--disable-gpu")


class ChromeUnavailable(CapabilityError):
    """No headless Chromium could be started on this host."""


def chrome_candidates() -> list[Path]:
    """Ordered candidates: explicit env var, then local installs."""
    out: list[Path] = []
    for name in ("CHROME_PATH", "HEVI_CHROME_PATH", "PUPPETEER_EXECUTABLE_PATH"):
        value = os.environ.get(name)
        if value:
            out.append(Path(value))
    out += [
        Path("/usr/bin/chromium"),
        Path("/usr/bin/chromium-browser"),
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/google-chrome-stable"),
        Path("/snap/bin/chromium"),
    ]
    # Playwright's own Chromium is the binary the kit's own candidate list
    # looks for; it is the one that works on this host.
    for root in (Path.home() / ".cache/ms-playwright", Path.home() / "Library/Caches/ms-playwright"):
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir(), reverse=True):
            if not entry.is_dir():
                continue
            for sub in ("chrome-linux64/chrome", "chrome-linux/chrome", "chrome-win/chrome.exe"):
                out.append(entry / sub)
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in out:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def _probe(binary: Path, *, timeout: float = 60.0) -> str | None:
    """Launch ``binary`` headless once.  Returns an error string or ``None``."""
    try:
        res = subprocess.run(
            [str(binary), "--headless=new", *SWIFTSHADER_FLAGS, "--dump-dom", "about:blank"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover - host specific
        return f"{type(exc).__name__}: {exc}"
    if res.returncode != 0:
        detail = (res.stderr or res.stdout or "").strip().splitlines()
        return f"exit {res.returncode}: {detail[0] if detail else 'no output'}"
    if "html" not in res.stdout.lower():
        return "no DOM returned"
    return None


@lru_cache(maxsize=1)
def _resolve() -> tuple[Path, list[tuple[Path, str]]]:
    tried: list[tuple[Path, str]] = []
    for candidate in chrome_candidates():
        if not candidate.exists() or not os.access(candidate, os.X_OK):
            continue
        problem = _probe(candidate)
        if problem is None:
            return candidate, tried
        tried.append((candidate, problem))
    raise ChromeUnavailable(
        "No usable headless Chromium for the Anatomy kit. Tried: "
        + ("; ".join(f"{path} ({why})" for path, why in tried) if tried else "no candidate existed")
        + ". Set CHROME_PATH to a Chromium/Chrome binary that can start with --headless=new."
    )


def resolve_chrome() -> Path:
    """Return a Chromium binary that has just answered a real headless launch."""
    return _resolve()[0]


def chrome_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """``os.environ`` plus ``CHROME_PATH``, for every kit script."""
    env = {**os.environ, "CHROME_PATH": str(resolve_chrome())}
    if extra:
        env.update(extra)
    return env


def chrome_version() -> str:
    """``Chromium 141.0.7390.54`` style string, for the report."""
    binary = resolve_chrome()
    try:
        res = subprocess.run([str(binary), "--version"], capture_output=True, text=True, timeout=30)
        return (res.stdout or res.stderr).strip() or "unknown"
    except (OSError, subprocess.TimeoutExpired):  # pragma: no cover
        return shutil.which(str(binary)) or "unknown"
