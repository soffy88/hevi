"""Canonical Remotion provider compiler.

This module implements a provider-specific compiler that targets the Remotion
runtime. It converts CanonicalShot semantics into a Remotion execution plan
without allowing Remotion-specific parameters to leak back into canonical
shapes.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from hevi.compiler import CompilationError, ProviderCapabilities, ResourceBudget
from hevi.production_graph.domain import (
    CanonicalShot,
    ExecutionPlan,
    ReferenceBundle,
    ReferenceItem,
)


class RemotionCompiler:
    """Produce immutable ExecutionPlan targeting Remotion runtime.

    This compiler consumes CanonicalShot semantics plus production plan context
    and produces an ExecutionPlan that the canonical Slate/Runtime can dispatch
    to a Remotion renderer. All Remotion-specific parameters are captured in
    the ExecutionPlan, never leaking back into CanonicalShot.
    """

    def __init__(self, *, allow_gpu: bool = False) -> None:
        self.allow_gpu = allow_gpu

    def compile(
        self,
        shot: CanonicalShot,
        references: ReferenceBundle,
        provider: ProviderCapabilities,
        resource_budget: ResourceBudget,
        render_mode: str = "video",
        output_format: str = "mp4",
        fps: int | None = None,
        timeline_inputs: dict[str, object] | None = None,
        audio_references: list[ReferenceItem] | None = None,
        subtitle_references: list[ReferenceItem] | None = None,
        output_contract: dict[str, object] | None = None,
        render_profile: dict[str, object] | None = None,
    ) -> ExecutionPlan:
        """Compile a canonical shot into a Remotion execution plan.

        The output is an immutable ExecutionPlan that includes everything needed
        for the canonical Slate/Runtime to invoke the Remotion renderer.
        """

        if shot.readiness_state.value != "READY":
            raise CompilationError("SHOT_NOT_READY", "generation dispatch requires a READY shot")
        if references.shot_id != shot.id:
            raise CompilationError(
                "REFERENCE_SHOT_MISMATCH",
                "reference bundle belongs to another shot",
            )

        self._validate_provider_capabilities(provider, shot)
        self._validate_resource_budget(provider, resource_budget, shot)
        selected_refs = self._select_references(references, provider)

        plan = self._build_execution_plan(
            shot,
            references,
            provider,
            resource_budget,
            selected_refs,
            render_mode,
            output_format,
            fps,
            timeline_inputs,
            audio_references,
            subtitle_references,
            output_contract,
            render_profile,
        )
        plan.validate_dag()
        return plan

    def compile_with_fallback(
        self,
        shot: CanonicalShot,
        references: ReferenceBundle,
        providers: Sequence[ProviderCapabilities],
        resource_budget: ResourceBudget,
        **kwargs: object,
    ) -> ExecutionPlan:
        """Attempt compilation with multiple providers, returning the first success."""

        failures: list[str] = []
        for provider in providers:
            try:
                return self.compile(
                    shot,
                    references,
                    provider,
                    resource_budget,
                    **kwargs,
                )
            except CompilationError as error:
                failures.append(str(error))
        raise CompilationError(
            "NO_RENDERING_PROVIDER",
            "; ".join(failures) or "no rendering providers supplied",
        )

    def _validate_provider_capabilities(
        self, provider: ProviderCapabilities, shot: CanonicalShot
    ) -> None:
        if not provider.supports_intent(shot.generation_intent):
            raise CompilationError(
                "INTENT_NOT_SUPPORTED",
                f"{provider.provider_id} does not support {shot.generation_intent.value}",
            )

        # Reference roles are validated against the concrete ReferenceBundle
        # in ``_select_references``; CanonicalShot only carries its identity.

    def _validate_resource_budget(
        self,
        provider: ProviderCapabilities,
        resource_budget: ResourceBudget,
        shot: CanonicalShot,
    ) -> None:
        if not resource_budget.resources_available:
            raise CompilationError("RESOURCE_UNAVAILABLE", "resource budget is not available")

        if (
            shot.duration_target < provider.min_duration_s
            or shot.duration_target > provider.max_duration_s
        ):
            raise CompilationError(
                "DURATION_LIMIT",
                f"duration {shot.duration_target} is outside [{provider.min_duration_s}, {provider.max_duration_s}]",
            )

        if (
            resource_budget.resolution
            and resource_budget.resolution not in provider.supported_resolutions
        ):
            raise CompilationError(
                "RESOLUTION_NOT_SUPPORTED",
                f"resolution {resource_budget.resolution} is unsupported",
            )

        if shot.audio_intent and not provider.supports_audio:
            raise CompilationError(
                "AUDIO_NOT_SUPPORTED",
                "shot requests audio but provider has no audio capability",
            )

        cost = shot.duration_target * provider.cost_per_second_usd
        if resource_budget.max_cost_usd is not None and cost > resource_budget.max_cost_usd:
            raise CompilationError(
                "BUDGET_EXCEEDED",
                f"estimated cost {cost:.4f} exceeds compile budget",
            )

    def _select_references(
        self, bundle: ReferenceBundle, provider: ProviderCapabilities
    ) -> list[ReferenceItem]:
        unsupported = [
            item.role.value
            for item in bundle.items
            if item.role not in provider.supported_reference_roles
        ]
        if unsupported:
            raise CompilationError(
                "UNSUPPORTED_REFERENCE_ROLES",
                f"{provider.provider_id} does not support reference roles {sorted(set(unsupported))}",
            )

        selected = sorted(bundle.items, key=lambda item: (-item.priority, item.id))
        if len(selected) > provider.max_reference_items:
            raise CompilationError(
                "TOO_MANY_REFERENCES",
                f"{provider.provider_id} accepts {provider.max_reference_items} references, got {len(selected)}",
            )

        return selected

    def _build_execution_plan(
        self,
        shot: CanonicalShot,
        references: ReferenceBundle,
        provider: ProviderCapabilities,
        resource_budget: ResourceBudget,
        selected_refs: list[ReferenceItem],
        render_mode: str,
        output_format: str,
        fps: int | None,
        timeline_inputs: dict[str, object] | None,
        audio_references: list[ReferenceItem] | None,
        subtitle_references: list[ReferenceItem] | None,
        output_contract: dict[str, object] | None,
        render_profile: dict[str, object] | None,
    ) -> ExecutionPlan:
        effective_concurrency = self._calculate_effective_concurrency(
            provider, resource_budget, shot
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
            prompt=self._build_remotion_prompt(shot),
            negative_prompt="",
            selected_references=selected_refs,
            parameters={
                "shot_size": shot.camera.shot_size.value,
                "movement": shot.camera.movement,
                "concurrency": effective_concurrency,
                "render_mode": render_mode,
                "output_format": output_format,
                "fps": fps or 24,
                "timeline_inputs": timeline_inputs or {},
                "output_contract": output_contract or {},
            },
            resolution=resource_budget.resolution or provider.default_resolution,
            fps=fps or 24,
            duration=shot.duration_target,
            estimated_cost=shot.duration_target * provider.cost_per_second_usd,
            estimated_latency_s=provider.estimated_latency_s,
            resource_profile={
                **provider.resource_profile,
                **resource_budget.resource_profile,
                "render_profile": render_profile or {},
            },
            idempotency_key=self._build_idempotency_key(
                shot,
                references,
                provider,
                shot.duration_target,
                resource_budget.resolution or provider.default_resolution,
                effective_concurrency,
            ),
        )

        self._add_remotion_artifacts(
            plan,
            audio_references,
            subtitle_references,
            output_contract,
            render_profile,
        )

        return plan

    def _calculate_effective_concurrency(
        self,
        provider: ProviderCapabilities,
        resource_budget: ResourceBudget,
        shot: CanonicalShot,
    ) -> int:
        if resource_budget.execution_profile is not None:
            try:
                resource_budget.execution_profile.require(
                    gpu_count=resource_budget.required_gpu_count,
                    gpu_vram_mb=resource_budget.required_gpu_vram_mb,
                    memory_mb=resource_budget.required_memory_mb,
                )
                from hevi.production_graph.resources import assert_concurrency

                return assert_concurrency(
                    resource_budget.execution_profile,
                    resource_budget.requested_concurrency,
                    "render",
                )
            except (ValueError, RuntimeError) as exc:
                raise CompilationError("RESOURCE_CONSTRAINT_VIOLATION", str(exc)) from exc

        return resource_budget.requested_concurrency

    def _build_remotion_prompt(self, shot: CanonicalShot) -> str:
        prompt_parts = [
            shot.action_description,
            shot.cinematography_notes,
            shot.camera.framing,
            shot.camera.composition,
            shot.audio_intent if shot.audio_intent else "",
            " ".join(shot.dialogue),
        ]
        return ". ".join(part.strip() for part in prompt_parts if part and part.strip())

    def _build_idempotency_key(
        self,
        shot: CanonicalShot,
        references: ReferenceBundle,
        provider: ProviderCapabilities,
        duration: float,
        resolution: str,
        effective_concurrency: int,
    ) -> str:
        value = {
            "project": shot.project_id,
            "revision": shot.revision_id,
            "shot": shot.id,
            "intent": shot.generation_intent.value,
            "bundle_revision": references.revision_id,
            "provider": provider.provider_id,
            "model": provider.model,
            "duration": duration,
            "resolution": resolution,
            "concurrency": effective_concurrency,
            "references": [
                {
                    "role": item.role.value,
                    "artifact_id": item.artifact_id,
                    "production_entity_id": item.production_entity_id,
                    "subject_id": item.subject_id,
                }
                for item in references.items
            ],
        }
        digest = hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
        return f"hevi:remotion:{shot.id}:{digest}"

    def _add_remotion_artifacts(
        self,
        plan: ExecutionPlan,
        audio_references: list[ReferenceItem] | None,
        subtitle_references: list[ReferenceItem] | None,
        output_contract: dict[str, object] | None,
        render_profile: dict[str, object] | None,
    ) -> None:
        plan.resource_profile.update(
            {
                "audio_artifacts": [ref.artifact_id for ref in (audio_references or [])],
                "subtitle_artifacts": [ref.artifact_id for ref in (subtitle_references or [])],
                "output_contract": output_contract or {},
                "render_profile": render_profile or {},
            }
        )

        plan.parameters.update(
            {
                "audio_artifacts": [ref.artifact_id for ref in (audio_references or [])],
                "subtitle_artifacts": [ref.artifact_id for ref in (subtitle_references or [])],
            }
        )

    def get_render_spec(self, plan: ExecutionPlan) -> dict[str, object]:
        """Extract Remotion-specific configuration from an execution plan.

        This method provides a canonical view of all Remotion parameters.
        """
        return {
            "render_mode": plan.parameters.get("render_mode"),
            "composition_id": plan.parameters.get("composition_id"),
            "output_path": plan.parameters.get("output_path"),
            "output_format": plan.parameters.get("output_format"),
            "fps": plan.fps,
            "timeline_inputs": plan.parameters.get("timeline_inputs"),
            "audio_artifacts": plan.parameters.get("audio_artifacts"),
            "subtitle_artifacts": plan.parameters.get("subtitle_artifacts"),
            "resource_profile": plan.resource_profile,
            "effective_concurrency": plan.parameters.get("concurrency"),
            "output_contract": plan.parameters.get("output_contract"),
        }


__all__ = ["RemotionCompiler"]
