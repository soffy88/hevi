"""oprim:Script2Video 无状态原子。不得 import oskill / omodul。"""

from __future__ import annotations

from hevi.script2video.oprim.camera_graph import (
    assign_cam_indices,
    children_of,
    compute_missing_info,
    generation_order,
    get_priority_shots,
    group_shots_into_cameras,
    validate_camera_tree,
)
from hevi.script2video.oprim.image_score import (
    score_image_basic,
    score_image_dimensions,
    score_image_file_size,
)
from hevi.script2video.oprim.portrait_prompt import build_portrait_prompt
from hevi.script2video.oprim.reference_pick import (
    compose_image_prefix_prompt,
    pick_portrait_view,
    select_pairs_by_indices,
)
from hevi.script2video.oprim.transition_prompt import build_transition_prompt
from hevi.script2video.oprim.variation import classify_variation, needs_last_frame

__all__ = [
    "assign_cam_indices",
    "build_portrait_prompt",
    "build_transition_prompt",
    "children_of",
    "classify_variation",
    "compose_image_prefix_prompt",
    "compute_missing_info",
    "generation_order",
    "get_priority_shots",
    "group_shots_into_cameras",
    "needs_last_frame",
    "pick_portrait_view",
    "score_image_basic",
    "score_image_dimensions",
    "score_image_file_size",
    "select_pairs_by_indices",
    "validate_camera_tree",
]
