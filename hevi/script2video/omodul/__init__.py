"""omodul:内核文本规划。正式三件套签名在 hevi/production/script2video_kernel_workflow.py。"""

from __future__ import annotations

from hevi.script2video.omodul.cameo_plan import plan_autocameo
from hevi.script2video.omodul.fuse import FusedProduction, fuse_production
from hevi.script2video.omodul.idea_plan import plan_idea2video
from hevi.script2video.omodul.kernel_plan import (
    characters_from_payload,
    plan_kernel_artifacts,
    shots_from_payload,
)
from hevi.script2video.omodul.novel_plan import plan_novel2video

__all__ = [
    "characters_from_payload",
    "FusedProduction",
    "fuse_production",
    "plan_autocameo",
    "plan_idea2video",
    "plan_kernel_artifacts",
    "plan_novel2video",
    "shots_from_payload",
]
