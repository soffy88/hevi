"""Optional Blender sub-line for SCENE3D (headless Cycles CPU).

Preview first (720p), then 1080p only after an explicit approval.  The module
also owns the serial render queue, the 20-minute per-task timeout, the 2x quota
unit, and the sozai CC0 asset adapter.
"""

from .pipeline import (
    NeedsApproval,
    SceneCheckFailed,
    build_brief,
    render_shot,
)
from .quota import QUOTA_UNITS, quota_units

__all__ = [
    "NeedsApproval",
    "SceneCheckFailed",
    "build_brief",
    "render_shot",
    "QUOTA_UNITS",
    "quota_units",
]
