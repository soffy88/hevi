"""Tests for the canonical Remotion provider compiler."""

from __future__ import annotations

import pytest

from hevi.compiler import (
    CompilationError,
    RemotionCompiler,
    ResourceBudget,
)
from hevi.compiler.capabilities import ProviderCapabilities
from hevi.production_graph import (
    CanonicalShot,
    ExecutionProfile,
    GenerationIntent,
    ReferenceBundle,
    ReferenceItem,
    ReferenceRole,
    ResourceUnavailableError,
)
from hevi.production_graph.domain import ShotSize


def _provider() -> ProviderCapabilities:
    return ProviderCapabilities(
        provider_id="remotion-cpu",
        model="hevi-remotion",
        supported_intents={GenerationIntent.IMAGE_TO_VIDEO, GenerationIntent.REMOTION},
        supported_reference_roles={
            ReferenceRole.CHARACTER_IDENTITY,
            ReferenceRole.CHARACTER_LOOK,
            ReferenceRole.LOCATION,
            ReferenceRole.PROP,
            ReferenceRole.AUDIO,
        },
        max_reference_items=8,
        max_duration_s=30,
        min_duration_s=1,
        max_prompt_length=4000,
        supported_resolutions={"720p", "1080p"},
        default_resolution="720p",
        supports_audio=True,
        cost_per_second_usd=0.0,
        estimated_latency_s=2.0,
        resource_profile={"runtime": "non-gpu"},
    )


def _shot(**updates: object) -> CanonicalShot:
    values: dict[str, object] = {
        "id": "shot-remotion",
        "project_id": "proj-remotion",
        "revision_id": "rev-remotion",
        "scene_id": "scene-remotion",
        "action_description": "envoy crosses the gate",
        "cinematography_notes": "slow push in, dawn lighting",
        "generation_intent": GenerationIntent.IMAGE_TO_VIDEO,
    }
    values.update(updates)
    return CanonicalShot(**values)


def _bundle(shot_id: str = "shot-remotion") -> ReferenceBundle:
    return ReferenceBundle(
        id="bundle-remotion",
        project_id="proj-remotion",
        revision_id="refs-rev",
        shot_id=shot_id,
        items=[
            ReferenceItem(
                role=ReferenceRole.CHARACTER_IDENTITY,
                artifact_id="identity-artifact",
                priority=10,
            ),
            ReferenceItem(
                role=ReferenceRole.LOCATION,
                artifact_id="location-artifact",
                priority=8,
            ),
        ],
    )


def _ready_shot(**updates: object) -> CanonicalShot:
    from hevi.production_graph import ReadinessState

    return _shot(readiness_state=ReadinessState.READY, **updates)


def test_remotion_compiler_emits_immutable_plan() -> None:
    compiler = RemotionCompiler()
    plan = compiler.compile(
        _ready_shot(), _bundle(), _provider(), ResourceBudget()
    )
    assert plan.immutable is True
    assert plan.idempotency_key.startswith("hevi:remotion:")


def test_remotion_compiler_determinism() -> None:
    compiler = RemotionCompiler()
    plan_a = compiler.compile(_ready_shot(), _bundle(), _provider(), ResourceBudget())
    plan_b = compiler.compile(_ready_shot(), _bundle(), _provider(), ResourceBudget())
    assert plan_a.idempotency_key == plan_b.idempotency_key


def test_remotion_compiler_includes_remotion_parameters() -> None:
    compiler = RemotionCompiler()
    plan = compiler.compile(
        _ready_shot(), _bundle(), _provider(), ResourceBudget()
    )
    params = plan.parameters
    assert params["render_mode"] == "video"
    assert params["output_format"] == "mp4"
    assert params["fps"] == 24
    assert "shot_size" in params
    assert "movement" in params
    assert "concurrency" in params


def test_remotion_compiler_resolution_and_fps() -> None:
    compiler = RemotionCompiler()
    plan = compiler.compile(
        _ready_shot(), _bundle(), _provider(),
        ResourceBudget(resolution="1080p"),
    )
    assert plan.resolution == "1080p"
    assert plan.fps == 24
    assert plan.duration == _ready_shot().duration_target


def test_remotion_compiler_audio_subtitle_references() -> None:
    audio_ref = ReferenceItem(role=ReferenceRole.AUDIO, artifact_id="audio-track")
    subtitle_ref = ReferenceItem(role=ReferenceRole.LOCATION, artifact_id="subtitle-track")
    compiler = RemotionCompiler()
    plan = compiler.compile(
        _ready_shot(), _bundle(), _provider(), ResourceBudget(),
        render_mode="video",
        fps=30,
        output_format="mp4",
        audio_references=[audio_ref],
        subtitle_references=[subtitle_ref],
    )
    assert plan.fps == 30
    assert "audio-track" in str(plan.parameters.get("audio_artifacts"))
    assert "subtitle-track" in str(plan.parameters.get("subtitle_artifacts"))


def test_remotion_compiler_effective_concurrency_from_profile() -> None:
    profile = ExecutionProfile(cpu_quota=2.0, render_concurrency=4)
    compiler = RemotionCompiler()
    plan = compiler.compile(
        _ready_shot(), _bundle(), _provider(),
        ResourceBudget(
            execution_profile=profile,
            requested_concurrency=4,
        ),
    )
    concurrency = plan.parameters["concurrency"]
    assert concurrency == 2


def test_remotion_compiler_caps_within_cpu_quota() -> None:
    """Verify that effective_concurrency never exceeds the allocated CPU capacity.

    Per spec: effective = max(1, min(configured, detected_runtime_cpu_capacity))
    Test case: cpu_quota=1.5, configured=4 => effective=1
    """
    profile = ExecutionProfile(cpu_quota=1.5, render_concurrency=4)
    compiler = RemotionCompiler()
    plan = compiler.compile(
        _ready_shot(), _bundle(), _provider(),
        ResourceBudget(
            execution_profile=profile,
            requested_concurrency=4,
        ),
    )
    concurrency = plan.parameters["concurrency"]
    assert concurrency == 1, f"expected effective_concurrency=1 for cpu_quota=1.5, got {concurrency}"


def test_remotion_compiler_capped_by_configured_when_higher_than_quota() -> None:
    """Configured=4, CPU=8 => effective=4 (configured less than quota)."""
    profile = ExecutionProfile(cpu_quota=8.0, render_concurrency=4)
    compiler = RemotionCompiler()
    plan = compiler.compile(
        _ready_shot(), _bundle(), _provider(),
        ResourceBudget(
            execution_profile=profile,
            requested_concurrency=4,
        ),
    )
    concurrency = plan.parameters["concurrency"]
    assert concurrency == 4


def test_remotion_compiler_capped_by_quota_when_lower() -> None:
    """Configured=4, CPU=2 => effective=2 (quota less than configured)."""
    profile = ExecutionProfile(cpu_quota=2.0, render_concurrency=4)
    compiler = RemotionCompiler()
    plan = compiler.compile(
        _ready_shot(), _bundle(), _provider(),
        ResourceBudget(
            execution_profile=profile,
            requested_concurrency=4,
        ),
    )
    concurrency = plan.parameters["concurrency"]
    assert concurrency == 2


def test_remotion_compiler_unconfigured_capped_to_minimum() -> None:
    """Configured=1 regardless of CPU => effective=1."""
    profile = ExecutionProfile(cpu_quota=8.0, render_concurrency=1)
    compiler = RemotionCompiler()
    plan = compiler.compile(
        _ready_shot(), _bundle(), _provider(),
        ResourceBudget(
            execution_profile=profile,
            requested_concurrency=1,
        ),
    )
    concurrency = plan.parameters["concurrency"]
    assert concurrency == 1


def test_remotion_compiler_resolution_and_fps() -> None:
    compiler = RemotionCompiler()
    plan = compiler.compile(
        _ready_shot(), _bundle(), _provider(),
        ResourceBudget(resolution="1080p"),
    )
    assert plan.resolution == "1080p"
    assert plan.fps == 24
    assert plan.duration == _ready_shot().duration_target


def test_remotion_compiler_audio_subtitle_references() -> None:
    audio_ref = ReferenceItem(role=ReferenceRole.AUDIO, artifact_id="audio-track")
    subtitle_ref = ReferenceItem(role=ReferenceRole.LOCATION, artifact_id="subtitle-track")
    compiler = RemotionCompiler()
    plan = compiler.compile(
        _ready_shot(), _bundle(), _provider(), ResourceBudget(),
        render_mode="video",
        fps=30,
        output_format="mp4",
        audio_references=[audio_ref],
        subtitle_references=[subtitle_ref],
    )
    assert plan.fps == 30
    assert "audio-track" in str(plan.parameters.get("audio_artifacts"))
    assert "subtitle-track" in str(plan.parameters.get("subtitle_artifacts"))


def test_remotion_compiler_output_contract_and_render_profile() -> None:
    contract = {"container": "mp4", "codec": "h264"}
    render_profile = {"quality": "baseline"}
    compiler = RemotionCompiler()
    plan = compiler.compile(
        _ready_shot(), _bundle(), _provider(), ResourceBudget(),
        output_contract=contract,
        render_profile=render_profile,
    )
    assert plan.resource_profile["output_contract"] == contract
    assert plan.resource_profile["render_profile"] == render_profile


def test_remotion_compiler_rejects_unready_shot() -> None:
    from hevi.production_graph import ReadinessState

    compiler = RemotionCompiler()
    shot = _shot(readiness_state=ReadinessState.ANALYZED)
    with pytest.raises(CompilationError, match="SHOT_NOT_READY"):
        compiler.compile(shot, _bundle(), _provider(), ResourceBudget())


def test_remotion_compiler_rejects_reference_mismatch() -> None:
    compiler = RemotionCompiler()
    with pytest.raises(CompilationError, match="REFERENCE_SHOT_MISMATCH"):
        compiler.compile(
            _ready_shot(), _bundle(shot_id="other-shot"), _provider(), ResourceBudget()
        )


def test_remotion_compiler_rejects_unsupported_intent() -> None:
    from hevi.production_graph import ReadinessState

    provider = _provider()
    provider.supported_intents = {GenerationIntent.TEXT_TO_VIDEO}
    compiler = RemotionCompiler()
    with pytest.raises(CompilationError, match="INTENT_NOT_SUPPORTED"):
        compiler.compile(
            _ready_shot(), _bundle(), provider, ResourceBudget()
        )


def test_remotion_compiler_rejects_duration_limit() -> None:
    compiler = RemotionCompiler()
    shot = _ready_shot(duration_target=100.0)
    with pytest.raises(CompilationError, match="DURATION_LIMIT"):
        compiler.compile(shot, _bundle(), _provider(), ResourceBudget())


def test_remotion_compiler_rejects_unsupported_resolution() -> None:
    compiler = RemotionCompiler()
    with pytest.raises(CompilationError, match="RESOLUTION_NOT_SUPPORTED"):
        compiler.compile(
            _ready_shot(), _bundle(), _provider(),
            ResourceBudget(resolution="4k"),
        )


def test_remotion_compiler_fallback() -> None:
    bad_provider = ProviderCapabilities(
        provider_id="bad",
        model="bad-model",
        supported_intents={GenerationIntent.IMAGE_TO_VIDEO},
        supported_reference_roles=set(),
        max_reference_items=8,
        max_duration_s=1.0,
        min_duration_s=1,
        max_prompt_length=4000,
        supported_resolutions={"720p"},
        default_resolution="720p",
        supports_audio=False,
        cost_per_second_usd=0.0,
        estimated_latency_s=2.0,
        resource_profile={"runtime": "non-gpu"},
    )
    good_provider = _provider()
    compiler = RemotionCompiler()
    plan = compiler.compile_with_fallback(
        _ready_shot(), _bundle(), [bad_provider, good_provider], ResourceBudget()
    )
    assert plan.provider == "remotion-cpu"


def test_remotion_compiler_does_not_leak_parameters_to_canonical() -> None:
    from hevi.production_graph.domain import CanonicalShot as Shot

    compiler = RemotionCompiler()
    shot = _ready_shot()
    before = dict(shot.model_dump())
    compiler.compile(shot, _bundle(), _provider(), ResourceBudget())
    after = dict(shot.model_dump())
    assert before == after


def test_remotion_compiler_get_render_spec() -> None:
    compiler = RemotionCompiler()
    plan = compiler.compile(_ready_shot(), _bundle(), _provider(), ResourceBudget())
    spec = compiler.get_render_spec(plan)
    assert spec["fps"] == 24
    assert spec["render_mode"] == "video"
    assert "resource_profile" in spec


__all__ = ["test_remotion_compiler_emits_immutable_plan"]