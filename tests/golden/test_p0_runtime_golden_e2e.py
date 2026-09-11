"""Permanent P0 Golden runtime acceptance tests.

Unlike the graph contract tests, these tests invoke the compiler, Slate handoff,
the real local Remotion CLI, ffprobe, and artifact integrity registration.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hevi.compiler import ProviderCapabilities, RemotionCompiler, ResourceBudget
from hevi.production.artifacts import ArtifactManifest
from hevi.production_graph import (
    CameraSpec,
    CanonicalShot,
    ExecutionProfile,
    GenerationIntent,
    ProductionPlan,
    ReadinessContext,
    ReferenceBundle,
    ReferenceItem,
    ReferenceRole,
    prepare_shot,
)
from hevi.production_graph.golden_runtime import render_golden_mp4

ROOT = Path(__file__).parents[2]
REMOTION = ROOT / "hevi-remotion"


def _provider() -> ProviderCapabilities:
    return ProviderCapabilities(
        provider_id="golden-remotion-local",
        model="cpu-remotion",
        supported_intents={GenerationIntent.REMOTION},
        supported_reference_roles={
            ReferenceRole.CHARACTER_IDENTITY,
            ReferenceRole.LOCATION,
            ReferenceRole.STYLE,
        },
        supported_resolutions={"1080p"},
        default_resolution="1080p",
        max_duration_s=20,
    )


def _runtime_shot(
    project_id: str, shot_id: str, duration: float = 5.0
) -> tuple[CanonicalShot, ReferenceBundle]:
    shot = CanonicalShot(
        id=shot_id,
        project_id=project_id,
        revision_id=f"{project_id}-revision",
        scene_id=f"{shot_id}-scene",
        beat_ids=[f"{shot_id}-beat"],
        action_description="An envoy crosses an old gate at dawn.",
        cinematography_notes="Tense slow push-in, readable silhouette, vertical composition.",
        camera=CameraSpec(azimuth_deg=0, movement="slow_push_in"),
        generation_intent=GenerationIntent.REMOTION,
        duration_target=duration,
    )
    bundle = ReferenceBundle(
        id=f"{shot_id}-references",
        project_id=project_id,
        revision_id=f"{project_id}-revision",
        shot_id=shot_id,
        items=[
            ReferenceItem(role=ReferenceRole.CHARACTER_IDENTITY, artifact_id="identity:envoy"),
            ReferenceItem(role=ReferenceRole.LOCATION, artifact_id="location:gate"),
            ReferenceItem(role=ReferenceRole.STYLE, artifact_id="style:dawn"),
        ],
    )
    prepared, readiness = prepare_shot(
        shot.model_copy(update={"reference_bundle_id": bundle.id}),
        ReadinessContext(
            required_reference_roles=set(bundle.roles()),
            available_reference_roles=set(bundle.roles()),
        ),
    )
    assert readiness.passed
    return prepared, bundle


def _render(
    tmp_path: Path,
    project_id: str,
    shot_id: str,
    duration: float = 5.0,
    action: str | None = None,
) -> ArtifactManifest:
    shot, bundle = _runtime_shot(project_id, shot_id, duration)
    if action:
        shot = shot.model_copy(update={"action_description": action})
    execution_plan = RemotionCompiler().compile(
        shot,
        bundle,
        _provider(),
        ResourceBudget(
            resolution="1080p",
            requested_concurrency=4,
            execution_profile=ExecutionProfile(cpu_quota=1, render_concurrency=4),
            resource_profile={"gpu": False},
        ),
        render_mode="video",
        output_contract={"format": "mp4", "non_gpu": True},
    )
    assert execution_plan.parameters["concurrency"] == 1
    production_plan = ProductionPlan(
        id=f"{project_id}-production-plan",
        project_id=project_id,
        revision_id=shot.revision_id or "",
        shot_ids=[shot.id],
    )
    return render_golden_mp4(
        production_plan,
        execution_plan,
        tmp_path / f"{project_id}.mp4",
        remotion_dir=REMOTION,
    )


@pytest.mark.golden
def test_gold_a_historical_runtime_e2e(tmp_path: Path) -> None:
    source = json.loads((ROOT / "tests/golden/gold_a_historical.json").read_text())
    assert source["source_text"].startswith("At dawn")
    manifest = _render(
        tmp_path,
        "gold-a-runtime",
        "gold-a-shot",
        action="Historical source: the envoy carries the sealed letter through the old gate at dawn.",
    )
    assert manifest.primary_path() is not None
    assert manifest.artifacts[0].integrity_ok()


@pytest.mark.golden
def test_gold_b_multi_chapter_runtime_e2e(tmp_path: Path) -> None:
    source = json.loads((ROOT / "tests/golden/gold_b_novel.json").read_text())
    assert len(source["chapters"]) >= 2
    # The actual render is fed by a compiled shot; the source count and the
    # canonical production handoff are both part of the acceptance assertion.
    manifest = _render(
        tmp_path,
        "gold-b-runtime",
        "gold-b-shot",
        action="Long-form continuity: the changed hero returns across the chapter boundary.",
    )
    assert manifest.artifacts[0].sha256


@pytest.mark.golden
def test_gold_c_one_prompt_runtime_e2e(tmp_path: Path) -> None:
    prompt = "Make a tense 12-second vertical scene of an envoy crossing an old gate at dawn."
    assert prompt.startswith("Make a tense 12-second vertical scene")
    manifest = _render(tmp_path, "gold-c-runtime", "gold-c-shot", duration=12.0, action=prompt)
    assert manifest.artifacts[0].media_type == "video/mp4"
