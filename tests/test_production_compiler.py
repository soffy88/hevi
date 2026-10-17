from __future__ import annotations

import pytest

from hevi.compiler import (
    CompilationError,
    ProductionCompiler,
    ProviderCapabilities,
    ResourceBudget,
)
from hevi.production_graph import (
    CanonicalShot,
    GenerationIntent,
    ReadinessState,
    ReferenceBundle,
    ReferenceItem,
    ReferenceRole,
)


def _shot(**updates: object) -> CanonicalShot:
    values: dict[str, object] = {
        "project_id": "p",
        "revision_id": "r",
        "scene_id": "s",
        "action_description": "character opens the gate",
        "cinematography_notes": "slow push in, eye level",
        "readiness_state": ReadinessState.READY,
    }
    values.update(updates)
    return CanonicalShot(**values)


def _provider(**updates: object) -> ProviderCapabilities:
    values: dict[str, object] = {
        "provider_id": "fake-video",
        "model": "fake-1",
        "supported_intents": {GenerationIntent.IMAGE_TO_VIDEO},
        "supported_reference_roles": {ReferenceRole.CHARACTER_IDENTITY},
        "supported_resolutions": {"720p"},
    }
    values.update(updates)
    return ProviderCapabilities(**values)


def _refs(shot_id: str = "shot") -> ReferenceBundle:
    return ReferenceBundle(
        project_id="p",
        revision_id="refs-r",
        shot_id=shot_id,
        items=[
            ReferenceItem(
                role=ReferenceRole.CHARACTER_IDENTITY,
                artifact_id="identity-artifact",
                priority=10,
            )
        ],
    )


def test_compiler_emits_immutable_plan_with_pins_and_deterministic_idempotency() -> None:
    shot = _shot()
    compiler = ProductionCompiler()
    plan = compiler.compile(
        shot, _refs(shot.id), _provider(cost_per_second_usd=0.2), ResourceBudget()
    )
    again = compiler.compile(
        shot, _refs(shot.id), _provider(cost_per_second_usd=0.2), ResourceBudget()
    )
    assert plan.shot_revision_id == "r"
    assert plan.reference_revision_id == "refs-r"
    assert plan.provider == "fake-video"
    assert plan.estimated_cost == pytest.approx(1.0)
    assert plan.idempotency_key == again.idempotency_key
    assert plan.selected_references[0].artifact_id == "identity-artifact"


@pytest.mark.parametrize(
    ("provider_updates", "shot_updates", "budget", "code"),
    [
        (
            {"supported_intents": {GenerationIntent.TEXT_TO_VIDEO}},
            {},
            ResourceBudget(),
            "CAPABILITY_UNSUPPORTED",
        ),
        ({"max_reference_items": 0}, {}, ResourceBudget(), "REFERENCE_LIMIT"),
        ({"max_duration_s": 1.0}, {}, ResourceBudget(), "DURATION_LIMIT"),
        ({"max_prompt_length": 3}, {}, ResourceBudget(), "PROMPT_LIMIT"),
        (
            {"supported_resolutions": {"1080p"}, "default_resolution": "1080p"},
            {},
            ResourceBudget(resolution="720p"),
            "RESOLUTION_UNSUPPORTED",
        ),
        (
            {"supports_audio": False},
            {"audio_intent": "music"},
            ResourceBudget(),
            "AUDIO_UNSUPPORTED",
        ),
        ({"cost_per_second_usd": 10.0}, {}, ResourceBudget(max_cost_usd=1), "BUDGET_EXCEEDED"),
    ],
)
def test_compiler_rejects_unsupported_capabilities_and_limits(
    provider_updates: dict[str, object],
    shot_updates: dict[str, object],
    budget: ResourceBudget,
    code: str,
) -> None:
    with pytest.raises(CompilationError, match=code):
        shot = _shot(**shot_updates)
        ProductionCompiler().compile(shot, _refs(shot.id), _provider(**provider_updates), budget)


def test_compiler_falls_back_to_first_provider_that_can_compile() -> None:
    shot = _shot()
    plan = ProductionCompiler().compile_with_fallback(
        shot,
        _refs(shot.id),
        [_provider(max_duration_s=1), _provider(provider_id="fallback", model="fallback-1")],
        ResourceBudget(),
    )
    assert plan.provider == "fallback"


def test_compiler_rejects_unready_shot_and_unavailable_resources() -> None:
    shot = _shot(readiness_state=ReadinessState.ANALYZED)
    with pytest.raises(CompilationError, match="SHOT_NOT_READY"):
        ProductionCompiler().compile(
            shot,
            _refs(shot.id),
            _provider(),
            ResourceBudget(),
        )
    with pytest.raises(CompilationError, match="RESOURCE_UNAVAILABLE"):
        resource_shot = _shot()
        ProductionCompiler().compile(
            resource_shot,
            _refs(resource_shot.id),
            _provider(),
            ResourceBudget(resources_available=False),
        )
