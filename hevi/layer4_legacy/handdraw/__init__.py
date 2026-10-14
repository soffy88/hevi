"""Hevi Handdraw Line: internalised sweety-handdraw-video rendering engine.

Vendored from upstream sweety-handdraw-video (v1.2.3, MIT License).
Preserves full path-based stroke reveal, paint motion, typeset captioning,
and continuous audio-driven timeline rendering.
"""

from __future__ import annotations

import sys
from pathlib import Path

HANDDRAW_ROOT = Path(__file__).resolve().parent
SCRIPTS_DIR = HANDDRAW_ROOT / "scripts"

# Ensure vendored scripts directory is accessible
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

__all__ = ["HANDDRAW_ROOT", "SCRIPTS_DIR"]
