"""Camera Tree — 镜头空间连续性管理（对标 ViMax interfaces/camera.py）。

ViMax 的 Camera 概念：
  - 把多个 shot 分组到同一个 camera（共享空间/视角的镜头集合）
  - camera 之间有父子关系（parent_cam_idx）
  - 子 camera 的首帧依赖父 camera 的末帧（需要过渡视频桥接）
  - 优先级生成：父 camera 必须先于子 camera 生成

Hevi 已有丰富的 camera 系统（CameraSetup/CameraPersona/CameraCurve/scene_stage），
本模块补充的是 **跨镜头视觉连续性** 这一层：管理 shot 生成依赖顺序和过渡桥接。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── 数据模型 ──────────────────────────────────────────────────────────


@dataclass
class CameraNode:
    """Camera 树节点：一组空间相关的 shot。"""

    cam_idx: int
    shot_idxs: list[int] = field(default_factory=list)
    parent_cam_idx: int | None = None
    parent_shot_idx: int | None = None  # 依赖的父镜头索引
    reason: str = ""  # 为什么选这个 parent
    is_parent_fully_covers_child: bool | None = None
    missing_info: str = ""  # parent 不完全覆盖 child 时，缺少什么

    @property
    def is_root(self) -> bool:
        return self.parent_cam_idx is None

    @property
    def has_parent(self) -> bool:
        return self.parent_cam_idx is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "cam_idx": self.cam_idx,
            "shot_idxs": list(self.shot_idxs),
            "parent_cam_idx": self.parent_cam_idx,
            "parent_shot_idx": self.parent_shot_idx,
            "reason": self.reason,
            "is_parent_fully_covers_child": self.is_parent_fully_covers_child,
            "missing_info": self.missing_info,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CameraNode:
        return cls(
            cam_idx=int(data["cam_idx"]),
            shot_idxs=[int(i) for i in data.get("shot_idxs", [])],
            parent_cam_idx=data.get("parent_cam_idx"),
            parent_shot_idx=data.get("parent_shot_idx"),
            reason=str(data.get("reason", "")),
            is_parent_fully_covers_child=data.get("is_parent_fully_covers_child"),
            missing_info=str(data.get("missing_info", "")),
        )


@dataclass
class CameraTree:
    """Camera 树：管理所有 CameraNode 的父子关系和生成顺序。"""

    cameras: dict[int, CameraNode] = field(default_factory=dict)

    def add(self, node: CameraNode) -> None:
        self.cameras[node.cam_idx] = node

    def get(self, cam_idx: int) -> CameraNode | None:
        return self.cameras.get(cam_idx)

    @property
    def roots(self) -> list[CameraNode]:
        """获取所有根 camera（无 parent）。"""
        return [c for c in self.cameras.values() if c.is_root]

    @property
    def all_cameras(self) -> list[CameraNode]:
        return list(self.cameras.values())

    def children_of(self, cam_idx: int) -> list[CameraNode]:
        """获取某 camera 的所有子 camera。"""
        return [
            c for c in self.cameras.values()
            if c.parent_cam_idx == cam_idx
        ]

    def generation_order(self) -> list[int]:
        """拓扑排序：返回 camera 的生成顺序（父先于子）。

        Returns:
            [cam_idx, ...] — 按依赖顺序排列
        """
        visited: set[int] = set()
        order: list[int] = []

        def _visit(idx: int):
            if idx in visited:
                return
            visited.add(idx)
            node = self.cameras.get(idx)
            if node and node.parent_cam_idx is not None:
                _visit(node.parent_cam_idx)
            order.append(idx)

        for cam_idx in self.cameras:
            _visit(cam_idx)

        return order

    def get_priority_shots(self) -> list[int]:
        """获取"优先 shot"：被其他 camera 依赖的 shot 索引。

        这些 shot 应该先生成，因为其他 camera 的过渡视频依赖它们。
        """
        priority: set[int] = set()
        for cam in self.cameras.values():
            if cam.parent_shot_idx is not None:
                priority.add(cam.parent_shot_idx)
        return sorted(priority)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cameras": {
                str(idx): node.to_dict()
                for idx, node in self.cameras.items()
            },
            "generation_order": self.generation_order(),
            "priority_shots": self.get_priority_shots(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CameraTree:
        tree = cls()
        for _idx, node_data in data.get("cameras", {}).items():
            tree.add(CameraNode.from_dict(node_data))
        return tree

    def validate(self) -> list[str]:
        """验证树的完整性（检查悬挂引用、循环依赖等）。"""
        issues: list[str] = []

        for cam in self.cameras.values():
            if cam.parent_cam_idx is not None:
                if cam.parent_cam_idx not in self.cameras:
                    issues.append(
                        f"camera {cam.cam_idx} references non-existent parent {cam.parent_cam_idx}"
                    )

        # 检测循环
        for cam in self.cameras.values():
            visited: set[int] = set()
            current: int | None = cam.cam_idx
            while current is not None:
                if current in visited:
                    issues.append(f"cycle detected involving camera {cam.cam_idx}")
                    break
                visited.add(current)
                node = self.cameras.get(current)
                current = node.parent_cam_idx if node else None

        return issues


# ── 构建 Camera Tree ──────────────────────────────────────────────────


def construct_camera_tree(
    shots: list[dict[str, Any]],
    *,
    spatial_grouping: bool = True,
) -> CameraTree:
    """从 shot 列表构建 Camera Tree。

    Args:
        shots: [{"idx": 0, "cam_idx": 0, "environment": "...", ...}, ...]
        spatial_grouping: 是否按空间分组（相同环境的 shot 归同一 camera）

    Returns:
        CameraTree
    """
    tree = CameraTree()

    if not shots:
        return tree

    if spatial_grouping:
        # 按 environment 分组
        env_groups: dict[str, list[int]] = {}
        for shot in shots:
            env = shot.get("environment", "default")
            cam_idx = shot.get("cam_idx", 0)
            env_groups.setdefault(env, [])
            if cam_idx not in env_groups[env]:
                env_groups[env].append(cam_idx)

        # 为每个环境创建一个主 camera + 子 camera
        cam_counter = 0
        cam_idx_map: dict[int, int] = {}  # original cam_idx → tree cam_idx

        for env, cam_idxs in env_groups.items():
            root_idx = cam_counter
            root_node = CameraNode(
                cam_idx=root_idx,
                shot_idxs=[
                    s["idx"] for s in shots
                    if s.get("cam_idx", 0) == cam_idxs[0]
                ],
                reason=f"root camera for environment: {env}",
            )
            tree.add(root_node)
            cam_idx_map[cam_idxs[0]] = root_idx
            cam_counter += 1

            for i, orig_idx in enumerate(cam_idxs[1:], 1):
                child_idx = cam_counter
                child_node = CameraNode(
                    cam_idx=child_idx,
                    shot_idxs=[
                        s["idx"] for s in shots
                        if s.get("cam_idx", 0) == orig_idx
                    ],
                    parent_cam_idx=root_idx,
                    parent_shot_idx=shots[0]["idx"] if shots else None,
                    reason=f"child camera within environment: {env}",
                )
                tree.add(child_node)
                cam_idx_map[orig_idx] = child_idx
                cam_counter += 1
    else:
        # 简单模式：每个 shot 一个 camera
        for i, shot in enumerate(shots):
            node = CameraNode(
                cam_idx=i,
                shot_idxs=[shot.get("idx", i)],
                parent_cam_idx=i - 1 if i > 0 else None,
                parent_shot_idx=shots[i - 1].get("idx", i - 1) if i > 0 else None,
            )
            tree.add(node)

    return tree


def compute_missing_info(
    tree: CameraTree,
    shot_descriptions: dict[int, dict[str, Any]],
) -> CameraTree:
    """计算每个子 camera 相对于父 camera 的 missing_info。

    Args:
        tree: Camera Tree
        shot_descriptions: {shot_idx: {"visible_chars": [...], "environment": "..."}}

    Returns:
        更新后的 CameraTree
    """
    for cam in tree.cameras.values():
        if not cam.has_parent or cam.parent_shot_idx is None:
            continue

        parent_desc = shot_descriptions.get(cam.parent_shot_idx, {})
        first_child_shot = cam.shot_idxs[0] if cam.shot_idxs else None
        child_desc = shot_descriptions.get(first_child_shot, {}) if first_child_shot is not None else {}

        parent_chars = set(parent_desc.get("visible_chars", []))
        child_chars = set(child_desc.get("visible_chars", []))
        new_chars = child_chars - parent_chars
        missing_chars = parent_chars - child_chars

        parts: list[str] = []
        if new_chars:
            parts.append(f"new characters: {', '.join(sorted(new_chars))}")
        if missing_chars:
            parts.append(f"missing characters: {', '.join(sorted(missing_chars))}")
        if parent_desc.get("environment") != child_desc.get("environment"):
            parts.append("environment change")

        cam.missing_info = "; ".join(parts) if parts else ""
        cam.is_parent_fully_covers_child = len(parts) == 0

    return tree
