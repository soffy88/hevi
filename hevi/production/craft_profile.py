"""冻结制作 Profile —— 内化 agent-video-pipeline 的 resolved-profile 纪律。

装配前把画布、动效档、安全区、音色、CTA、发布偏好打成一份不可变 JSON + SHA。
下游动效/布局/QC 只认这份 SHA;Profile 变了旧报告作废。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

MOTION_PRESETS: tuple[str, ...] = (
    "basic-stable",
    "clean",
    "premium-balanced",
    "cinematic",
)


def _box(x: float, y: float, w: float, h: float) -> dict[str, float]:
    return {"x": x, "y": y, "w": w, "h": h}


@dataclass
class CraftProfile:
    """工作区级制作规格。to_resolved() 产出冻结包。"""

    profile_id: str = "workspace"
    language: str = "zh"
    aspect_ratio: str = "9:16"
    width: int = 1080
    height: int = 1920
    fps: int = 30
    motion_preset: str = "basic-stable"
    voice_style: str = "formal"
    cta: str = ""
    title_box: dict[str, float] = field(default_factory=lambda: _box(0.06, 0.06, 0.88, 0.14))
    caption_box: dict[str, float] = field(default_factory=lambda: _box(0.08, 0.78, 0.84, 0.16))
    illustration_box: dict[str, float] = field(default_factory=lambda: _box(0.08, 0.22, 0.84, 0.50))
    avatar_box: dict[str, float] = field(default_factory=lambda: _box(0.04, 0.70, 0.28, 0.22))
    avatar_enabled: bool = False
    transition_families: list[str] = field(
        default_factory=lambda: ["push-slide", "crossfade"]
    )
    publish_platforms: list[str] = field(default_factory=lambda: ["generic"])
    illustration_required: bool = False
    stock_sources: list[str] = field(
        default_factory=lambda: ["pexels", "pixabay", "coverr"]
    )
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.motion_preset not in MOTION_PRESETS:
            self.motion_preset = "basic-stable"
        if self.aspect_ratio == "16:9":
            self.width, self.height = 1920, 1080
            self.caption_box = _box(0.10, 0.82, 0.80, 0.12)
            self.illustration_box = _box(0.28, 0.16, 0.64, 0.60)
            self.avatar_box = _box(0.04, 0.62, 0.20, 0.28)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def sha256(self) -> str:
        blob = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def freeze(self) -> dict[str, Any]:
        data = self.to_dict()
        digest = self.sha256()
        return {
            "schema_version": 1,
            "profile_id": self.profile_id,
            "profile_sha256": digest,
            "profile": data,
        }


def profile_from_explainer(
    *,
    aspect_ratio: str = "9:16",
    voice_style: str = "formal",
    avatar_enabled: bool = False,
    cta: str = "",
    motion_preset: str = "basic-stable",
) -> CraftProfile:
    return CraftProfile(
        profile_id="explainer",
        aspect_ratio=aspect_ratio,
        voice_style=voice_style,
        avatar_enabled=avatar_enabled,
        cta=cta,
        motion_preset=motion_preset,
    )


def assert_profile_fresh(resolved: dict[str, Any], expected_sha: str) -> None:
    got = str(resolved.get("profile_sha256") or "")
    if not got or got != expected_sha:
        raise ValueError(f"Profile SHA 过期: got={got[:12]} expected={expected_sha[:12]}")
