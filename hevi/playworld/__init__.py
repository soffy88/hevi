"""Interactive world / open-world play engine state (file-based).

The world is a single JSON document on disk — setting, characters,
items/relationship flags, current location and turn count.  This package is
a clean-room, minimal implementation: no database, no network, no LLM —
creativity is injected by the caller through ``narrator_fn``.
"""

from __future__ import annotations

from hevi.playworld.engine import (
    WORLD_SCHEMA,
    NarratorFn,
    init_world,
    load_world,
    step_world,
)

__all__ = [
    "WORLD_SCHEMA",
    "NarratorFn",
    "init_world",
    "load_world",
    "step_world",
]
