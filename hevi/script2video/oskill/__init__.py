"""oskill:每个技能组合 ≥2 个 oprim 原语。不得 import omodul。"""

from __future__ import annotations

from hevi.script2video.oskill.autocameo import integrate_cameos, process_cameo_photos
from hevi.script2video.oskill.camera_tree import construct_camera_tree
from hevi.script2video.oskill.idea_screenwrite import plan_idea_screenplay
from hevi.script2video.oskill.novel_adapt import plan_novel_adaptation
from hevi.script2video.oskill.portrait_triptych import (
    generate_all_portraits,
    generate_portrait_triptych,
)
from hevi.script2video.oskill.reference_select import (
    generate_and_select,
    select_best_image,
    select_reference_images_and_prompt,
)
from hevi.script2video.oskill.shot_decompose import decompose_all_shots, decompose_shot_visual
from hevi.script2video.oskill.transition_video import (
    generate_all_transitions,
    generate_transition_video,
)

__all__ = [
    "construct_camera_tree",
    "decompose_all_shots",
    "decompose_shot_visual",
    "generate_all_portraits",
    "generate_all_transitions",
    "generate_and_select",
    "generate_portrait_triptych",
    "generate_transition_video",
    "integrate_cameos",
    "plan_idea_screenplay",
    "plan_novel_adaptation",
    "process_cameo_photos",
    "select_best_image",
    "select_reference_images_and_prompt",
]
