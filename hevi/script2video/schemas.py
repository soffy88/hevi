"""obase 契约:Script2Video 内核的纯数据结构。

3O 归属(待上游): `obase.script2video_schemas`。不含 provider / 阈值 / Series 字段。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

VariationType = Literal["large", "medium", "small"]
PortraitViewName = Literal["front", "side", "back"]
TransitionStrategyName = Literal["video_gen", "morph", "xfade_fallback"]


@dataclass
class PortraitView:
    """一张角色参考图(某一视角)。"""

    view: PortraitViewName
    path: Path
    description: str = ""
    generation_prompt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "view": self.view,
            "path": str(self.path),
            "description": self.description,
            "generation_prompt": self.generation_prompt,
        }


@dataclass
class CharacterPortrait:
    """一个角色的正/侧/背三联画。"""

    name: str
    identifier: str
    physical_description: str
    front: PortraitView | None = None
    side: PortraitView | None = None
    back: PortraitView | None = None
    style: str = ""

    @property
    def all_views(self) -> list[PortraitView]:
        return [v for v in (self.front, self.side, self.back) if v is not None]

    @property
    def reference_paths(self) -> list[Path]:
        return [v.path for v in self.all_views if v.path.exists()]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "identifier": self.identifier,
            "physical_description": self.physical_description,
            "front": self.front.to_dict() if self.front else None,
            "side": self.side.to_dict() if self.side else None,
            "back": self.back.to_dict() if self.back else None,
            "style": self.style,
            "reference_paths": [str(p) for p in self.reference_paths],
        }


@dataclass
class PortraitRegistry:
    """identifier → 三联画。可落盘 character_portraits_registry.json。"""

    portraits: dict[str, CharacterPortrait] = field(default_factory=dict)

    def register(self, portrait: CharacterPortrait) -> None:
        self.portraits[portrait.identifier] = portrait

    def get(self, identifier: str) -> CharacterPortrait | None:
        return self.portraits.get(identifier)

    def get_reference_paths(self, identifier: str) -> list[Path]:
        portrait = self.get(identifier)
        return list(portrait.reference_paths) if portrait else []

    def to_dict(self) -> dict[str, Any]:
        return {key: value.to_dict() for key, value in self.portraits.items()}


@dataclass
class ShotVisualPlan:
    """一镜拆成静态首帧 / 静态末帧 / 运动 + 变化幅度。"""

    idx: int
    visual_desc: str
    ff_desc: str
    lf_desc: str
    motion_desc: str
    variation_type: VariationType
    variation_reason: str
    ff_vis_char_idxs: list[int] = field(default_factory=list)
    lf_vis_char_idxs: list[int] = field(default_factory=list)
    audio_desc: str = ""
    cam_idx: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "idx": self.idx,
            "visual_desc": self.visual_desc,
            "ff_desc": self.ff_desc,
            "lf_desc": self.lf_desc,
            "motion_desc": self.motion_desc,
            "variation_type": self.variation_type,
            "variation_reason": self.variation_reason,
            "ff_vis_char_idxs": list(self.ff_vis_char_idxs),
            "lf_vis_char_idxs": list(self.lf_vis_char_idxs),
            "audio_desc": self.audio_desc,
            "cam_idx": self.cam_idx,
        }


@dataclass
class CameraNode:
    """一组共享空间/视角的镜头。"""

    cam_idx: int
    shot_idxs: list[int] = field(default_factory=list)
    parent_cam_idx: int | None = None
    parent_shot_idx: int | None = None
    reason: str = ""
    is_parent_fully_covers_child: bool | None = None
    missing_info: str | None = None

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


@dataclass
class CameraTree:
    """机位依赖图。"""

    cameras: dict[int, CameraNode] = field(default_factory=dict)

    def add(self, node: CameraNode) -> None:
        self.cameras[node.cam_idx] = node

    def get(self, cam_idx: int) -> CameraNode | None:
        return self.cameras.get(cam_idx)

    @property
    def roots(self) -> list[CameraNode]:
        return [node for node in self.cameras.values() if node.is_root]

    @property
    def all_cameras(self) -> list[CameraNode]:
        return list(self.cameras.values())

    def to_dict(self) -> dict[str, Any]:
        return {str(idx): node.to_dict() for idx, node in self.cameras.items()}


@dataclass
class TransitionSpec:
    """两帧之间的过渡规格。"""

    source_frame: Path
    target_frame: Path | None
    output_path: Path
    duration_s: float = 2.0
    strategy: TransitionStrategyName = "video_gen"
    prompt: str = ""
    missing_info: str | None = None
    fps: int = 24
    first_shot_visual_desc: str = ""
    second_shot_visual_desc: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_frame": str(self.source_frame),
            "target_frame": str(self.target_frame) if self.target_frame else None,
            "output_path": str(self.output_path),
            "duration_s": self.duration_s,
            "strategy": self.strategy,
            "prompt": self.prompt,
            "missing_info": self.missing_info,
            "fps": self.fps,
        }


@dataclass
class TransitionResult:
    output_path: Path
    strategy_used: TransitionStrategyName
    duration_s: float
    fallback_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_path": str(self.output_path),
            "strategy_used": self.strategy_used,
            "duration_s": self.duration_s,
            "fallback_reason": self.fallback_reason,
        }


@dataclass
class ReferenceCandidate:
    path: Path
    description: str
    kind: str = "portrait"  # portrait | scene_frame | transition_anchor
    view: PortraitViewName | None = None
    character_id: str | None = None

    def as_pair(self) -> tuple[str, str]:
        return str(self.path), self.description


@dataclass
class ReferenceSelection:
    """参考图子集 + 给生图模型的条件 prompt。"""

    pairs: list[tuple[str, str]]
    text_prompt: str
    selected_indices: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_image_path_and_text_pairs": [list(pair) for pair in self.pairs],
            "text_prompt": self.text_prompt,
            "selected_indices": list(self.selected_indices),
        }


@dataclass
class KernelShot:
    """内核归一化镜头(从 ShotList / 自由 dict 投影而来)。"""

    idx: int
    visual_desc: str
    cam_key: str = ""
    cam_idx: int = 0
    environment: str = ""
    visible_chars: list[str] = field(default_factory=list)
    audio_desc: str = ""
    facing_hints: dict[str, str] = field(default_factory=dict)
    azimuth_deg: float | None = None
    action_beats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "idx": self.idx,
            "visual_desc": self.visual_desc,
            "cam_key": self.cam_key,
            "cam_idx": self.cam_idx,
            "environment": self.environment,
            "visible_chars": list(self.visible_chars),
            "audio_desc": self.audio_desc,
            "facing_hints": dict(self.facing_hints),
            "azimuth_deg": self.azimuth_deg,
            "action_beats": list(self.action_beats),
        }


@dataclass
class KernelCharacter:
    name: str
    identifier: str
    description: str
    reference_photo: str | None = None
    is_visible: bool = True


@dataclass
class KernelPlan:
    """文本规划产物:拆镜 + 机位树。不含像素。"""

    shots: list[KernelShot]
    visual_plans: list[ShotVisualPlan]
    camera_tree: CameraTree
    characters: list[KernelCharacter] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "shots": [shot.to_dict() for shot in self.shots],
            "visual_plans": [plan.to_dict() for plan in self.visual_plans],
            "camera_tree": self.camera_tree.to_dict(),
            "characters": [
                {
                    "name": char.name,
                    "identifier": char.identifier,
                    "description": char.description,
                    "reference_photo": char.reference_photo,
                    "is_visible": char.is_visible,
                }
                for char in self.characters
            ],
        }
