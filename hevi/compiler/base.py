"""Provider-independent Production Compiler."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from hevi.production_graph.domain import (
    CanonicalShot,
    ExecutionPlan,
    ReferenceBundle,
    ReferenceItem,
)

from .capabilities import ProviderCapabilities, ResourceBudget


class CompilationError(ValueError):
    """A canonical shot cannot be compiled for the requested provider."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _idempotency_key(
    shot: CanonicalShot,
    bundle: ReferenceBundle,
    provider: ProviderCapabilities,
    duration: float,
    resolution: str,
) -> str:
    value = {
        "project": shot.project_id,
        "revision": shot.revision_id,
        "shot": shot.id,
        "intent": shot.generation_intent.value,
        "bundle_revision": bundle.revision_id,
        "provider": provider.provider_id,
        "model": provider.model,
        "duration": duration,
        "resolution": resolution,
        "references": [
            {
                "role": item.role.value,
                "artifact_id": item.artifact_id,
                "production_entity_id": item.production_entity_id,
                "subject_id": item.subject_id,
            }
            for item in bundle.items
        ],
    }
    digest = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    return f"hevi:shot:{shot.id}:{digest}"


def _select_references(
    bundle: ReferenceBundle, provider: ProviderCapabilities
) -> list[ReferenceItem]:
    unsupported = [
        item.role.value
        for item in bundle.items
        if item.role not in provider.supported_reference_roles
    ]
    if unsupported:
        raise CompilationError(
            "REFERENCE_ROLE_UNSUPPORTED",
            f"{provider.provider_id} does not support reference roles {sorted(set(unsupported))}",
        )
    selected = sorted(bundle.items, key=lambda item: (-item.priority, item.id))
    if len(selected) > provider.max_reference_items:
        raise CompilationError(
            "REFERENCE_LIMIT",
            f"{provider.provider_id} accepts {provider.max_reference_items} references, got {len(selected)}",
        )
    return selected


def _prompt(shot: CanonicalShot) -> str:
    parts = [
        shot.action_description,
        shot.cinematography_notes,
        shot.camera.framing,
        shot.camera.composition,
        shot.audio_intent if shot.audio_intent else "",
        " ".join(shot.dialogue),
    ]
    return ". ".join(part.strip() for part in parts if part and part.strip())


class ProductionCompiler:
    """Compile canonical semantics into an immutable provider execution plan."""

    def compile(
        self,
        shot: CanonicalShot,
        references: ReferenceBundle,
        provider: ProviderCapabilities,
        resource_budget: ResourceBudget,
    ) -> ExecutionPlan:
        if shot.readiness_state.value != "READY":
            raise CompilationError("SHOT_NOT_READY", "generation dispatch requires a READY shot")
        if references.shot_id != shot.id:
            raise CompilationError(
                "REFERENCE_SHOT_MISMATCH", "reference bundle belongs to another shot"
            )
        if not provider.supports_intent(shot.generation_intent):
            raise CompilationError(
                "CAPABILITY_UNSUPPORTED",
                f"{provider.provider_id} does not support {shot.generation_intent.value}",
            )
        if not resource_budget.resources_available:
            raise CompilationError("RESOURCE_UNAVAILABLE", "resource budget is not available")
        safe_concurrency = resource_budget.requested_concurrency
        if resource_budget.execution_profile is not None:
            try:
                resource_budget.execution_profile.require(
                    gpu_count=resource_budget.required_gpu_count,
                    gpu_vram_mb=resource_budget.required_gpu_vram_mb,
                    memory_mb=resource_budget.required_memory_mb,
                )
                safe_concurrency = resource_budget.execution_profile.effective_concurrency(
                    safe_concurrency, "provider"
                )
            except (ValueError, RuntimeError) as exc:
                raise CompilationError("RESOURCE_UNAVAILABLE", str(exc)) from exc
        selected = _select_references(references, provider)
        if (
            shot.duration_target < provider.min_duration_s
            or shot.duration_target > provider.max_duration_s
        ):
            raise CompilationError(
                "DURATION_LIMIT",
                f"duration {shot.duration_target} is outside [{provider.min_duration_s}, {provider.max_duration_s}]",
            )
        resolution = resource_budget.resolution or provider.default_resolution
        if resolution not in provider.supported_resolutions:
            raise CompilationError(
                "RESOLUTION_UNSUPPORTED", f"resolution {resolution} is unsupported"
            )
        prompt = _prompt(shot)
        if len(prompt) > provider.max_prompt_length:
            raise CompilationError("PROMPT_LIMIT", "compiled prompt exceeds provider limit")
        if shot.audio_intent and not provider.supports_audio:
            raise CompilationError(
                "AUDIO_UNSUPPORTED", "shot requests audio but provider has no audio capability"
            )
        cost = shot.duration_target * provider.cost_per_second_usd
        if resource_budget.max_cost_usd is not None and cost > resource_budget.max_cost_usd:
            raise CompilationError(
                "BUDGET_EXCEEDED", f"estimated cost {cost:.4f} exceeds compile budget"
            )
        execution_profile = (
            resource_budget.execution_profile.model_dump(mode="json")
            if resource_budget.execution_profile is not None
            else {}
        )
        plan = ExecutionPlan(
            project_id=shot.project_id,
            production_id=shot.project_id,
            revision_id=shot.revision_id or "",
            shot_id=shot.id,
            shot_revision_id=shot.revision_id,
            reference_revision_id=references.revision_id,
            provider=provider.provider_id,
            model=provider.model,
            capability=shot.generation_intent.value,
            prompt=prompt,
            negative_prompt="",
            selected_references=selected,
            parameters={
                "shot_size": shot.camera.shot_size.value,
                "movement": shot.camera.movement,
                "concurrency": safe_concurrency,
            },
            resolution=resolution,
            fps=24,
            duration=shot.duration_target,
            estimated_cost=cost,
            estimated_latency_s=provider.estimated_latency_s,
            resource_profile={
                **provider.resource_profile,
                **resource_budget.resource_profile,
                "execution_profile": execution_profile,
            },
            idempotency_key=_idempotency_key(
                shot, references, provider, shot.duration_target, resolution
            ),
        )
        plan.validate_dag()
        return plan

    def compile_with_fallback(
        self,
        shot: CanonicalShot,
        references: ReferenceBundle,
        providers: Sequence[ProviderCapabilities],
        resource_budget: ResourceBudget,
    ) -> ExecutionPlan:
        failures: list[str] = []
        for provider in providers:
            try:
                return self.compile(shot, references, provider, resource_budget)
            except CompilationError as error:
                failures.append(str(error))
        raise CompilationError(
            "NO_PROVIDER_FALLBACK", "; ".join(failures) or "no providers supplied"
        )


__all__ = ["CompilationError", "ProductionCompiler"]
