"""omodul:内核文本规划。正式三件套签名在 hevi/production/script2video_kernel_workflow.py。"""

from __future__ import annotations

from hevi.layer4_legacy.script2video.omodul_impl.cameo_plan import plan_autocameo
from hevi.layer4_legacy.script2video.omodul_impl.fuse import FusedProduction, fuse_production
from hevi.layer4_legacy.script2video.omodul_impl.idea_plan import plan_idea2video
from hevi.layer4_legacy.script2video.omodul_impl.kernel_plan import (
    characters_from_payload,
    plan_kernel_artifacts,
    shots_from_payload,
)
from hevi.layer4_legacy.script2video.omodul_impl.novel_plan import plan_novel2video

__all__ = [
    "FusedProduction",
    "characters_from_payload",
    "fuse_production",
    "plan_autocameo",
    "plan_idea2video",
    "plan_kernel_artifacts",
    "plan_novel2video",
    "shots_from_payload",
]
