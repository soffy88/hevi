"""Quota accounting for the Blender sub-line.

A 3D shot occupies two ordinary slots: it blocks the single serial Blender
queue for much longer than a 2D render and it is the scarce CPU resource.
"""

from __future__ import annotations

QUOTA_UNITS = 2


def quota_units(kind: str = "scene3d_blender") -> int:
    """Return the credit/quota units this task class occupies."""
    if kind in {"scene3d_blender", "blender", "scene3d"}:
        return QUOTA_UNITS
    return 1
