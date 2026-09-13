"""Narrative capability flags; all default to off for existing production lines."""

from __future__ import annotations

import os


def enabled(name: str = "NARRATIVE_INTELLIGENCE_ENABLED") -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}
