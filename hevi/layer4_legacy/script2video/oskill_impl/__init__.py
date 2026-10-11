"""oskill:每个技能组合 ≥2 个 oprim 原语。不得 import omodul。"""

from __future__ import annotations

from hevi.layer4_legacy.script2video.oskill_impl.autocameo import (
    integrate_cameos,
    process_cameo_photos,
)
from hevi.layer4_legacy.script2video.oskill_impl.camera_tree import construct_camera_tree
from hevi.layer4_legacy.script2video.oskill_impl.idea_screenwrite import plan_idea_screenplay
from hevi.layer4_legacy.script2video.oskill_impl.novel_adapt import plan_novel_adaptation
from hevi.layer4_legacy.script2video.oskill_impl.portrait_triptych import (
    generate_all_portraits,
    generate_portrait_triptych,
)
from hevi.layer4_legacy.script2video.oskill_impl.reference_select import (
    generate_and_select,
    select_best_image,
    select_reference_images_and_prompt,
)
from hevi.layer4_legacy.script2video.oskill_impl.shot_decompose import (
    decompose_all_shots,
    decompose_shot_visual,
)
from hevi.layer4_legacy.script2video.oskill_impl.shot_budget import (
    expected_chapters_for_duration,
    fit_shot_plans_to_budget,
    merge_shot_plans,
    shot_budget_for_duration,
    shot_budget_per_chapter,
)
from hevi.layer4_legacy.script2video.oskill_impl.transition_video import (
    generate_all_transitions,
    generate_transition_video,
)

__all__ = [
    "construct_camera_tree",
    "decompose_all_shots",
    "decompose_shot_visual",
    "expected_chapters_for_duration",
    "fit_shot_plans_to_budget",
    "merge_shot_plans",
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
    "shot_budget_for_duration",
    "shot_budget_per_chapter",
]
