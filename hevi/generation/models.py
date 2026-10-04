"""Canonical video-generation contracts (spec P1/P2). Provider-agnostic by construction.

设计红线(spec §2/§17):
- 本模块不得出现任何 provider 专属字段(架构测试锁死)。
- 不新建 capability/selection authority:capability 只做**声明与校验**,
  选择仍走既有 ProviderRegistry。
- 不新建 generation lifecycle runtime:编排挂在既有 production runtime 之下。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum

from hevi.generation.errors import ConditioningWindowInvalid


class GenerationStage(StrEnum):
    DRAFT = "DRAFT"
    CONTINUATION = "CONTINUATION"
    REFINEMENT = "REFINEMENT"
    FINAL = "FINAL"


class GenerationMode(StrEnum):
    T2V = "T2V"
    I2V = "I2V"
    DIRECTED_CONTINUATION = "DIRECTED_CONTINUATION"


class BudgetLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


CAPABILITY_KEYS = (
    "t2v", "i2v", "continuation", "long_video", "refinement",
    "temporal_refinement", "spatial_refinement", "audio_conditioning",
    "interactive_generation",
)

# 架构红线:provider 专属 flag 一律不得进入 canonical(测试逐个断言缺席)。
FORBIDDEN_CANONICAL_FIELDS = (
    "num_cond_frames", "use_kv_cache", "offload_kv_cache", "enable_bsa",
    "refinement_lora", "context_parallel_size", "use_distill", "enhance_hf",
)


def _digest(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), default=str).encode()).hexdigest()


@dataclass(frozen=True)
class GenerationBudget:
    temporal_budget: BudgetLevel = BudgetLevel.MEDIUM
    spatial_budget: BudgetLevel = BudgetLevel.MEDIUM
    motion_budget: BudgetLevel = BudgetLevel.MEDIUM
    identity_budget: BudgetLevel = BudgetLevel.MEDIUM
    refinement_budget: BudgetLevel = BudgetLevel.LOW


@dataclass(frozen=True)
class VideoGenerationCapabilities:
    """backend 自述能力。缺键 = False(spec §15:Director 按 capability graph 选,不硬编码)。"""
    values: dict[str, bool] = field(default_factory=dict)

    def supports(self, key: str) -> bool:
        return bool(self.values.get(key, False))

    def missing(self, required: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(key for key in required if not self.supports(key))


@dataclass(frozen=True)
class Intent:
    prompt: str
    negative_prompt: str = ""
    action: str = ""
    camera: str = ""
    composition: str = ""


@dataclass(frozen=True)
class Conditioning:
    mode: str = "none"  # none | reference_image | continuation
    reference_image: str = ""
    continuation_state_id: str = ""


@dataclass(frozen=True)
class OutputSpec:
    width: int = 1280
    height: int = 720
    fps: int = 24
    duration_ms: int = 0


@dataclass(frozen=True)
class ValidationSpec:
    continuity_required: bool = False
    identity_required: bool = False
    motion_required: bool = False


@dataclass(frozen=True)
class VideoGenerationRequest:
    """Canonical request。字段集合刻意最小:任何 provider flag 都属 backend。"""
    project_id: str
    scene_id: str
    shot_id: str
    generation_id: str
    mode: GenerationMode = GenerationMode.T2V
    intent: Intent = field(default_factory=lambda: Intent(prompt=""))
    conditioning: Conditioning = field(default_factory=Conditioning)
    output: OutputSpec = field(default_factory=OutputSpec)
    quality: GenerationBudget = field(default_factory=GenerationBudget)
    validation: ValidationSpec = field(default_factory=ValidationSpec)
    stage: GenerationStage = GenerationStage.DRAFT

    def required_capabilities(self) -> tuple[str, ...]:
        if self.mode is GenerationMode.DIRECTED_CONTINUATION:
            return ("continuation",)
        if self.mode is GenerationMode.I2V:
            return ("i2v",)
        return ("t2v",)

    def request_hash(self) -> str:
        return _digest({
            "project_id": self.project_id, "scene_id": self.scene_id,
            "shot_id": self.shot_id, "generation_id": self.generation_id,
            "mode": str(self.mode), "stage": str(self.stage),
            "intent": self.intent, "conditioning": self.conditioning,
            "output": self.output, "quality": self.quality,
            "validation": self.validation,
        })


# ── P2:continuation state ──


@dataclass(frozen=True)
class ConditioningWindow:
    """多帧条件窗口。禁止退化为 last_frame 单文件(spec §4)。"""
    media_ref: str
    frame_start: int
    frame_end: int
    timestamp_start_ms: int
    timestamp_end_ms: int
    fps: int

    @property
    def frame_count(self) -> int:
        return self.frame_end - self.frame_start + 1

    def validate(self) -> None:
        if not self.media_ref:
            raise ConditioningWindowInvalid("window requires immutable media_ref")
        if self.frame_count < 1:
            raise ConditioningWindowInvalid(f"empty window: {self.frame_start}..{self.frame_end}")
        if self.fps <= 0:
            raise ConditioningWindowInvalid(f"invalid fps: {self.fps}")
        span_ms = self.timestamp_end_ms - self.timestamp_start_ms
        expected_ms = round((self.frame_count - 1) * 1000 / self.fps)
        if abs(span_ms - expected_ms) > max(1, round(1000 / self.fps)):
            raise ConditioningWindowInvalid(
                f"timestamp span {span_ms}ms inconsistent with fps/frames (expected ~{expected_ms}ms)")
        if self.timestamp_start_ms < 0:
            raise ConditioningWindowInvalid("negative timestamp")


@dataclass(frozen=True)
class VisualAnchor:
    subject_state: str = ""
    camera_state: str = ""
    scene_state: str = ""
    style_state: str = ""


@dataclass(frozen=True)
class ContinuationState:
    """有时间语义的视觉状态,不是 last_frame 文件(spec §3)。"""
    continuation_state_id: str
    source_generation_id: str
    source_shot_id: str
    conditioning_window: ConditioningWindow
    visual_anchor: VisualAnchor = field(default_factory=VisualAnchor)
    generation_seed: int = 0
    backend: str = ""
    backend_version: str = ""
    created_at: str = ""
    validation_status: str = "pending"

    def validate(self) -> None:
        self.conditioning_window.validate()
        if not self.continuation_state_id or not self.source_generation_id:
            raise ConditioningWindowInvalid("state requires ids")


@dataclass(frozen=True)
class GeneratedClip:
    """生成产物 + canonical stage provenance(spec §10:HyperFrames 必须能回答来源)。"""
    artifact_path: str
    artifact_hash: str
    generation_id: str
    source_shot_id: str
    continuation_state_id: str = ""
    generation_stage: GenerationStage = GenerationStage.DRAFT
    backend: str = ""
    backend_version: str = ""
    width: int = 0
    height: int = 0
    fps: int = 0
    frame_count: int = 0
    duration_ms: int = 0

    def provenance(self) -> dict[str, str]:
        return {
            "generation_id": self.generation_id,
            "source_shot_id": self.source_shot_id,
            "continuation_state_id": self.continuation_state_id,
            "generation_stage": str(self.generation_stage),
            "backend": self.backend,
            "backend_version": self.backend_version,
        }


@dataclass(frozen=True)
class FallbackRecord:
    """显式降级记录(spec §14):不得静默。"""
    fallback_reason: str
    original_backend: str
    fallback_backend: str
    degraded_capability: str = ""
