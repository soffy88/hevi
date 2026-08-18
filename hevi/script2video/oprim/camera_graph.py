"""机位图:分组、拓扑序、环检测、missing_info。

3O 归属(待上游): `oprim.camera_graph`。
"""

from __future__ import annotations

from collections import defaultdict

from hevi.script2video.schemas import CameraNode, CameraTree, KernelShot


def assign_cam_indices(shots: list[KernelShot]) -> list[KernelShot]:
    """按 cam_key 首次出现顺序分配稳定 cam_idx。空 key 各自成机位。"""
    seen: dict[str, int] = {}
    next_idx = 0
    for shot in shots:
        key = (shot.cam_key or "").strip()
        if not key:
            key = f"__anon_{shot.idx}"
            shot.cam_key = key
        if key not in seen:
            seen[key] = next_idx
            next_idx += 1
        shot.cam_idx = seen[key]
    return shots


def group_shots_into_cameras(shots: list[KernelShot]) -> CameraTree:
    """同一 cam_idx 归一台相机;根=最小 cam_idx。"""
    grouped: dict[int, list[int]] = defaultdict(list)
    env_by_cam: dict[int, str] = {}
    for shot in shots:
        grouped[shot.cam_idx].append(shot.idx)
        if shot.cam_idx not in env_by_cam:
            env_by_cam[shot.cam_idx] = shot.environment
    tree = CameraTree()
    root_idx = min(grouped) if grouped else 0
    for cam_idx, shot_idxs in sorted(grouped.items()):
        parent = None if cam_idx == root_idx else root_idx
        parent_shot = None
        reason = f"root camera for environment: {env_by_cam.get(cam_idx, '')}"
        if parent is not None:
            parent_shots = grouped[parent]
            parent_shot = parent_shots[0] if parent_shots else None
            reason = f"child camera within environment: {env_by_cam.get(cam_idx, '')}"
        tree.add(
            CameraNode(
                cam_idx=cam_idx,
                shot_idxs=list(shot_idxs),
                parent_cam_idx=parent,
                parent_shot_idx=parent_shot,
                reason=reason,
            )
        )
    return tree


def children_of(tree: CameraTree, cam_idx: int) -> list[CameraNode]:
    return [node for node in tree.all_cameras if node.parent_cam_idx == cam_idx]


def generation_order(tree: CameraTree) -> list[int]:
    """父先于子。环在 validate 阶段拒绝。"""
    order: list[int] = []
    visiting: set[int] = set()
    seen: set[int] = set()

    def visit(cam_idx: int) -> None:
        if cam_idx in seen:
            return
        if cam_idx in visiting:
            raise ValueError(f"cycle detected involving camera {cam_idx}")
        visiting.add(cam_idx)
        node = tree.get(cam_idx)
        if node is not None and node.parent_cam_idx is not None:
            visit(node.parent_cam_idx)
        visiting.remove(cam_idx)
        seen.add(cam_idx)
        order.append(cam_idx)

    for node in sorted(tree.all_cameras, key=lambda item: item.cam_idx):
        visit(node.cam_idx)
    return order


def get_priority_shots(tree: CameraTree) -> list[int]:
    """被其他相机当父锚的镜头,必须先出首帧。"""
    return sorted(
        {
            node.parent_shot_idx
            for node in tree.all_cameras
            if node.parent_shot_idx is not None
        }
    )


def validate_camera_tree(tree: CameraTree) -> list[str]:
    """返回问题列表;空列表=合法。"""
    problems: list[str] = []
    for node in tree.all_cameras:
        if node.parent_cam_idx is None:
            continue
        if node.parent_cam_idx == node.cam_idx:
            problems.append(f"camera {node.cam_idx} lists itself as its parent")
        elif tree.get(node.parent_cam_idx) is None:
            problems.append(
                f"camera {node.cam_idx} references non-existent parent {node.parent_cam_idx}"
            )
    try:
        generation_order(tree)
    except ValueError as exc:
        problems.append(str(exc))
    roots = tree.roots
    if tree.cameras and not roots:
        problems.append("camera tree has no root")
    return problems


def compute_missing_info(
    tree: CameraTree,
    shots: list[KernelShot],
) -> CameraTree:
    """子机位相对父锚镜头缺哪些可见角色。"""
    by_idx = {shot.idx: shot for shot in shots}
    for node in tree.all_cameras:
        if node.parent_shot_idx is None:
            node.missing_info = None
            node.is_parent_fully_covers_child = None if node.is_root else True
            continue
        parent = by_idx.get(node.parent_shot_idx)
        child_chars: set[str] = set()
        for shot_idx in node.shot_idxs:
            child = by_idx.get(shot_idx)
            if child is not None:
                child_chars.update(child.visible_chars)
        parent_chars = set(parent.visible_chars) if parent is not None else set()
        missing = sorted(child_chars - parent_chars)
        if missing:
            node.missing_info = "missing characters: " + ", ".join(missing)
            node.is_parent_fully_covers_child = False
        else:
            node.missing_info = None
            node.is_parent_fully_covers_child = True
    return tree
