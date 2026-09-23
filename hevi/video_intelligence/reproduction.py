"""Case reproduction contracts over HEVI's existing provider/verdict ports.

This module deliberately has no HTTP client, renderer, or custom scorer.  The
caller supplies the already-configured HEVI generation and verdict callables.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from enum import StrEnum
from typing import Any, Protocol

from pydantic import Field

from .case_analysis import CaseAnalysis, ReferenceBinding
from .case_models import VideoCase
from .models import StrictModel


class ReproductionMode(StrEnum):
    EXACT_STRUCTURE = "exact_structure"
    STYLE_ONLY = "style_only"
    MOTION_ONLY = "motion_only"
    CAMERA_ONLY = "camera_only"
    IDENTITY_LOCKED = "identity_locked"
    CROSS_MODEL = "cross_model"


class ReproductionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


class GenerationPort(Protocol):
    async def __call__(self, request: dict[str, Any]) -> dict[str, Any]: ...


class VerdictPort(Protocol):
    async def __call__(self, artifact: dict[str, Any], *, case: VideoCase) -> dict[str, Any]: ...


class ReproductionPlan(StrictModel):
    case_id: str
    mode: ReproductionMode = ReproductionMode.EXACT_STRUCTURE
    compiled_prompt: str
    reference_bindings: list[ReferenceBinding] = Field(default_factory=list)
    generation_parameters: dict[str, Any] = Field(default_factory=dict)
    provider: str
    model: str
    model_version: str | None = None


class CaseReproduction(StrictModel):
    id: str
    case_id: str
    provider: str
    model: str
    model_version: str | None = None
    generation_mode: ReproductionMode
    compiled_prompt: str
    reference_bindings: list[ReferenceBinding] = Field(default_factory=list)
    generation_parameters: dict[str, Any] = Field(default_factory=dict)
    output_asset_id: str | None = None
    cost: float | None = Field(default=None, ge=0)
    latency_ms: float | None = Field(default=None, ge=0)
    status: ReproductionStatus = ReproductionStatus.PENDING
    verdict_id: str | None = None
    verdict: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str


def reproduction_idempotency_key(plan: ReproductionPlan) -> str:
    payload = plan.model_dump(mode="json")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_reproduction_plan(
    case: VideoCase,
    analysis: CaseAnalysis,
    *,
    provider: str,
    model: str,
    mode: ReproductionMode = ReproductionMode.EXACT_STRUCTURE,
    generation_parameters: dict[str, Any] | None = None,
) -> ReproductionPlan:
    prompt = case.original_prompt or ""
    if mode == ReproductionMode.EXACT_STRUCTURE:
        prompt = f"{prompt}\nStructural constraints: {analysis.temporal_structure.model_dump(mode='json')}"
    return ReproductionPlan(
        case_id=case.id,
        mode=mode,
        compiled_prompt=prompt,
        reference_bindings=analysis.reference_bindings,
        generation_parameters=generation_parameters or {},
        provider=provider,
        model=model,
    )


async def reproduce_case(
    plan: ReproductionPlan,
    *,
    generate: GenerationPort,
    verdict: VerdictPort,
    case: VideoCase,
) -> CaseReproduction:
    """Run one reproduction through injected canonical HEVI boundaries."""

    key = reproduction_idempotency_key(plan)
    record = CaseReproduction(
        id=f"reproduction:{uuid.uuid4().hex}",
        case_id=plan.case_id,
        provider=plan.provider,
        model=plan.model,
        model_version=plan.model_version,
        generation_mode=plan.mode,
        compiled_prompt=plan.compiled_prompt,
        reference_bindings=plan.reference_bindings,
        generation_parameters=plan.generation_parameters,
        idempotency_key=key,
        status=ReproductionStatus.RUNNING,
    )
    artifact = await generate({
        "case_id": plan.case_id,
        "prompt": plan.compiled_prompt,
        "reference_bindings": [item.model_dump(mode="json") for item in plan.reference_bindings],
        "provider": plan.provider,
        "model": plan.model,
        "parameters": plan.generation_parameters,
    })
    if not artifact.get("asset_id"):
        record.status = ReproductionStatus.FAILED
        record.verdict = {"status": "FAILED", "reason": "GENERATION_ASSET_MISSING"}
        return record
    result = await verdict(artifact, case=case)
    record.output_asset_id = str(artifact["asset_id"])
    record.cost = float(artifact["cost"]) if artifact.get("cost") is not None else None
    record.latency_ms = float(artifact["latency_ms"]) if artifact.get("latency_ms") is not None else None
    record.verdict = result
    record.verdict_id = str(result.get("verdict_id")) if result.get("verdict_id") else None
    record.status = ReproductionStatus.COMPLETED if result.get("status") not in {"FAILED", "BLOCKED"} else ReproductionStatus.FAILED
    return record


__all__ = [
    "CaseReproduction", "GenerationPort", "ReproductionMode", "ReproductionPlan",
    "ReproductionStatus", "VerdictPort", "build_reproduction_plan",
    "reproduce_case", "reproduction_idempotency_key",
]
