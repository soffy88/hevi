#!/usr/bin/env python3
"""Fail when generated line catalog is not reproducible from line YAML."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "docs/generated/line_catalog.md"


def main() -> int:
    before = CATALOG.read_text(encoding="utf-8") if CATALOG.exists() else None
    subprocess.run([sys.executable, str(ROOT / "scripts/generate_line_catalog.py")], cwd=ROOT, check=True)
    after = CATALOG.read_text(encoding="utf-8")
    if before != after:
        if before is not None:
            CATALOG.write_text(before, encoding="utf-8")
        print("line catalog drift: run scripts/generate_line_catalog.py and commit the result", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
