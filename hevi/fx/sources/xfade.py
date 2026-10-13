"""Parse ffmpeg xfade transitions to extract FX template entries.

Attempts to import from hevi.assembly.xfade_transitions first (T2 module,
may not exist in this branch). Falls back to dynamic enumeration via
`ffmpeg -h filter=xfade` if the import fails.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from hevi.fx.registry import FXTemplate, Category, Source

# Attempt to import from hevi.assembly (T2 may provide this)
_xfade_names_from_assembly: list[str] | None = None

try:
    from hevi.assembly.xfade_transitions import XFADE_TRANSITIONS  # type: ignore[import-untyped]

    _xfade_names_from_assembly = [
        name for _, name in XFADE_TRANSITIONS
    ]
except ImportError:
    _xfade_names_from_assembly = None

_FFMPEG_PATH = "/home/soffy/.local/bin/ffmpeg"


def _parse_ffmpeg_xfade_help() -> list[str]:
    """Parse `ffmpeg -h filter=xfade` output to extract transition names."""
    result = subprocess.run(
        [_FFMPEG_PATH, "-hide_banner", "-h", "filter=xfade"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg xfade help failed: {result.stderr}")

    # Parse lines like: "     fade            0            ..FV....... fade transition"
    # Capture the transition name and require a non-negative integer id, which
    # excludes "custom -1" and the duration/offset/expr option rows.
    names = []
    for line in result.stdout.splitlines():
        match = re.match(r'^\s{5,}([a-z0-9]+)\s+(\d+)\s+\S+\s+', line)
        if match:
            names.append(match.group(1))

    return names


def load_xfade() -> list[FXTemplate]:
    """Load all xfade transitions.

    Uses hevi.assembly.xfade_transitions if available, otherwise
    enumerates from ffmpeg help output.

    Returns:
        List of FXTemplate entries for all xfade transitions.
    """
    names = _xfade_names_from_assembly

    if names is None:
        names = _parse_ffmpeg_xfade_help()

    templates = []
    for name in names:
        template_id = f"xfade:{name}"
        templates.append(FXTemplate(
            id=template_id,
            name_zh=f"xfade {name} 转场",
            category=Category.TRANSITION,
            source=Source.XFADE,
            source_ref=name,
            tags=[name, "xfade", "transition"],
            duration_hint=1.0,  # xfade default duration is 1s
        ))

    return templates