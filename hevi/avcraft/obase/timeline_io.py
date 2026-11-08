"""Timeline persistence (obase: file IO lives here, not in oskill).

Moved from ``oskill/timeline.py`` at avcraft admission (2026-11-04):
oskill is the stateless-algorithm layer and must not own persistence.
``oskill/timeline.py`` re-exports these two names so the established
import path keeps working; the implementation lives here.
"""

from __future__ import annotations

import json
from pathlib import Path

SCHEMA = "avcraft.timeline/v1"


def save_timeline(tl: dict, path: str | Path) -> Path:
    p = Path(path)
    p.write_text(json.dumps(tl, ensure_ascii=False, indent=1))
    return p


def load_timeline(path: str | Path) -> dict:
    tl = json.loads(Path(path).read_text())
    if tl.get("schema") != SCHEMA:
        raise ValueError(f"unexpected schema {tl.get('schema')}")
    return tl
