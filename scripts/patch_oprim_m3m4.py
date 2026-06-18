"""Patch oprim v3.10.10 M3+M4 fixes into the active venv site-packages.

Run after `uv sync` / `uv pip install` reinstalls oprim v3.10.10 to restore
the M3 (vibevoice) and M4 (duix) fixes until owner tags v3.10.11.

Usage:
    uv run python scripts/patch_oprim_m3m4.py

Tracking: oprim fix branch pushed to
    github.com/helios-plat/oprim  fix/m3-m4-vibevoice-duix-v3.10.11
Owner action: merge + tag v3.10.11, then update hevi pyproject.toml pin.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DIFFS = [
    SCRIPT_DIR / "oprim_m3_fix.diff",
    SCRIPT_DIR / "oprim_m4_duix.diff",
    SCRIPT_DIR / "oprim_m4_avatar.diff",
]


def oprim_dir() -> Path:
    import importlib.util
    spec = importlib.util.find_spec("oprim")
    if spec is None or spec.origin is None:
        raise RuntimeError("oprim not found in current environment")
    return Path(spec.origin).parent


def check_already_patched(oprim: Path) -> bool:
    vibe = (oprim / "_vibevoice_synthesize.py").read_text()
    return "_spk_map" in vibe


def main() -> None:
    oprim = oprim_dir()
    print(f"oprim: {oprim}")

    if check_already_patched(oprim):
        print("Already patched — nothing to do.")
        return

    for diff_file in DIFFS:
        if not diff_file.exists():
            print(f"ERROR: diff not found: {diff_file}", file=sys.stderr)
            sys.exit(1)
        result = subprocess.run(
            ["patch", "-p2", "--directory", str(oprim.parent)],
            input=diff_file.read_bytes(),
            capture_output=True,
        )
        if result.returncode != 0:
            print(f"patch failed for {diff_file.name}:", file=sys.stderr)
            print(result.stdout.decode(), file=sys.stderr)
            print(result.stderr.decode(), file=sys.stderr)
            sys.exit(1)
        print(f"  applied {diff_file.name}")

    print("M3+M4 patches applied successfully.")


if __name__ == "__main__":
    main()
