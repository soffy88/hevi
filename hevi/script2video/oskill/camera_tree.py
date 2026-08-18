"""构建并校验机位树。

组合: cam 归一 + 分组 + missing_info + 校验。
3O 归属(待上游): `oskill.camera_tree`。
"""

from __future__ import annotations

from hevi.script2video.oprim.camera_graph import (
    assign_cam_indices,
    compute_missing_info,
    generation_order,
    get_priority_shots,
    group_shots_into_cameras,
    validate_camera_tree,
)
from hevi.script2video.schemas import CameraTree, KernelShot


def construct_camera_tree(shots: list[KernelShot]) -> CameraTree:
    """归一 cam_idx → 分组 → missing_info → 校验。不合法则 raise。"""
    assign_cam_indices(shots)
    tree = group_shots_into_cameras(shots)
    compute_missing_info(tree, shots)
    problems = validate_camera_tree(tree)
    if problems:
        raise ValueError("; ".join(problems))
    # 触碰拓扑序,确保可调度
    generation_order(tree)
    get_priority_shots(tree)
    return tree
