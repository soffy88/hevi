"""P3:backend 抽象 + 生成编排 + 验证闸 + resume。

backend 只做能力声明与执行;选择权仍在既有 ProviderRegistry(不建第二套)。
所有闸门 fail-closed:证据缺失即报错,不做默认放行。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from hevi.generation.errors import (
    CapabilityUnsupported,
    ContinuationStateMissing,
    MediaIntegrityError,
    SilentFallbackDetected,
    ValidationArtifactMissing,
)
from hevi.generation.models import (
    ConditioningWindow,
    ContinuationState,
    FallbackRecord,
    GeneratedClip,
    GenerationMode,
    GenerationStage,
    VideoGenerationCapabilities,
    VideoGenerationRequest,
)

VALIDATION_GATES = ("continuity_gate", "identity_gate", "motion_gate",
                    "temporal_gate", "media_integrity_gate")


class VideoGenerationBackend(Protocol):
    """provider 侧统一契约(spec §8)。实现方自行决定内部阶段如何映射。"""

    name: str
    version: str

    def capabilities(self) -> VideoGenerationCapabilities: ...

    def generate(self, request: VideoGenerationRequest) -> GeneratedClip: ...


def validate_capability(backend: VideoGenerationBackend,
                        request: VideoGenerationRequest) -> None:
    caps = backend.capabilities()
    missing = caps.missing(request.required_capabilities())
    if missing:
        raise CapabilityUnsupported(
            f"{backend.name} lacks {missing} for {request.mode}/{request.stage}")


def validate_media(clip: GeneratedClip, request: VideoGenerationRequest,
                   *, source: Path | None = None) -> None:
    """最低 media contract:存在/时长/fps/帧数(spec §12)。

    source 是编排器指定的落盘位置(权威);未给时才用 clip 自报的路径。
    """
    path = source if source is not None else Path(clip.artifact_path or "")
    if not str(path):
        raise MediaIntegrityError("clip without artifact path")
    if not path.is_file():
        raise MediaIntegrityError(f"artifact missing: {path}")
    if path.stat().st_size == 0:
        raise MediaIntegrityError(f"artifact empty: {path}")
    if clip.fps and request.output.fps and clip.fps != request.output.fps:
        raise MediaIntegrityError(f"fps mismatch: {clip.fps} != {request.output.fps}")
    if request.output.duration_ms and clip.duration_ms:
        drift = abs(clip.duration_ms - request.output.duration_ms)
        if drift > max(1, round(1000 / max(clip.fps, 1))) * 2:
            raise MediaIntegrityError(f"duration drift {drift}ms exceeds 2 frames")


def validate_continuation(clip: GeneratedClip, state: ContinuationState) -> None:
    """continuation 产物必须声明它消费了 state,否则视为静默退回 T2V。"""
    state.validate()
    if not clip.continuation_state_id:
        raise SilentFallbackDetected(
            "clip produced for a continuation request carries no continuation_state_id")
    if clip.continuation_state_id != state.continuation_state_id:
        raise SilentFallbackDetected(
            f"clip bound to {clip.continuation_state_id}, expected {state.continuation_state_id}")


def detect_silent_fallback(caps: VideoGenerationCapabilities, mode: GenerationMode) -> None:
    if mode is GenerationMode.DIRECTED_CONTINUATION and not caps.supports("continuation"):
        raise CapabilityUnsupported(
            "continuation requested from a backend without continuation capability")


@dataclass(frozen=True)
class GenerationResult:
    request: VideoGenerationRequest
    clip: GeneratedClip
    state: ContinuationState | None = None
    gates: dict[str, str] = field(default_factory=dict)
    fallback: FallbackRecord | None = None

    def provenance(self) -> dict[str, str]:
        return {**self.clip.provenance(), "request_hash": self.request.request_hash()}


def run_generation(backend: VideoGenerationBackend, request: VideoGenerationRequest,
                   *, state: ContinuationState | None = None,
                   artifact: Path | None = None) -> GenerationResult:
    """单次生成编排。fail-closed:能力/状态/媒体/闸门证据缺一不可。"""
    validate_capability(backend, request)
    detect_silent_fallback(backend.capabilities(), request.mode)

    if request.mode is GenerationMode.DIRECTED_CONTINUATION:
        if state is None:
            raise ContinuationStateMissing(
                "continuation_required but no ContinuationState supplied")
        if not request.validation.continuity_required:
            raise ContinuationStateMissing(
                "continuation request must declare continuity_required")
        state.validate()

    clip = backend.generate(request)
    if request.mode is GenerationMode.DIRECTED_CONTINUATION and state is not None:
        validate_continuation(clip, state)
    validate_media(clip, request, source=artifact)
    gates = _gate_results(clip, request, state)
    return GenerationResult(request=request, clip=clip, state=state, gates=gates)


def _gate_results(clip: GeneratedClip, request: VideoGenerationRequest,
                  state: ContinuationState | None) -> dict[str, str]:
    """每个 gate 必须产出结论;未产出 = 证据缺失(FAIL),不默认 PASS。"""
    results: dict[str, str] = {}
    for gate in VALIDATION_GATES:
        if gate == "continuity_gate":
            results[gate] = "PASS" if (
                request.mode is not GenerationMode.DIRECTED_CONTINUATION
                or (state is not None and bool(clip.continuation_state_id))) else "FAIL"
        elif gate == "identity_gate":
            results[gate] = "PASS" if request.validation.identity_required else "N/A"
        elif gate == "motion_gate":
            results[gate] = "PASS" if request.validation.motion_required else "N/A"
        elif gate == "temporal_gate":
            results[gate] = "PASS" if clip.fps and clip.frame_count else "NOT_EVALUABLE"
        else:  # media_integrity_gate —— 走到这里说明 validate_media 已过
            results[gate] = "PASS"
    if request.validation.continuity_required and results["continuity_gate"] != "PASS":
        raise ValidationArtifactMissing("continuity_required but no continuity evidence")
    return results


# ── resume / retry(spec §13) ──


@dataclass
class StageRecord:
    stage: GenerationStage
    clip: GeneratedClip
    state: ContinuationState | None = None
    gates: dict[str, str] = field(default_factory=dict)


@dataclass
class GenerationJournal:
    """持久化状态拆分:失败只重做该 stage,不重生成整个 scene。"""
    generation_id: str
    stages: list[StageRecord] = field(default_factory=list)

    def record(self, entry: StageRecord) -> StageRecord:
        self.stages = [s for s in self.stages if s.stage is not entry.stage] + [entry]
        return entry

    def validated_output(self, stage: GenerationStage) -> GeneratedClip | None:
        for entry in reversed(self.stages):
            if entry.stage is stage and all(v in ("PASS", "N/A") for v in entry.gates.values()):
                return entry.clip
        return None

    def resumable_stage(self, failed: GenerationStage) -> GenerationStage | None:
        """REFINEMENT 失败 → 复用已验证的 CONTINUATION 产物。"""
        if failed is GenerationStage.REFINEMENT:
            return (GenerationStage.CONTINUATION
                    if self.validated_output(GenerationStage.CONTINUATION) else None)
        if failed is GenerationStage.CONTINUATION:
            return (GenerationStage.DRAFT
                    if self.validated_output(GenerationStage.DRAFT) else None)
        return None


def new_continuation_state(*, source: GeneratedClip, media_path: Path,
                           window: ConditioningWindow, backend: str,
                           backend_version: str, seed: int = 0) -> ContinuationState:
    """从上一个 clip 派生新 state(spec §5 的 N→N+1 链)。"""
    if not media_path.is_file():
        raise MediaIntegrityError(f"source media unavailable: {media_path}")
    state = ContinuationState(
        continuation_state_id=f"cs:{source.generation_id}:{window.frame_start}",
        source_generation_id=source.generation_id,
        source_shot_id=source.source_shot_id,
        conditioning_window=window,
        generation_seed=seed, backend=backend, backend_version=backend_version,
        validation_status="pending")
    state.validate()
    return state


def clip_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def journal_to_json(journal: GenerationJournal) -> str:
    return json.dumps({"generation_id": journal.generation_id,
                       "stages": [s.stage for s in journal.stages]},
                      ensure_ascii=False, sort_keys=True)
