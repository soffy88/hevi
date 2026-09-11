from __future__ import annotations

import asyncio

import pytest

from hevi.production_graph import (
    CameraSpec,
    CanonicalShot,
    InMemoryDurableExecutionStore,
    ReadinessState,
    ReadinessTransitionError,
    ReferenceItem,
    ReferenceRole,
    TaskEnvelope,
    select_reference_view,
    transition_shot,
)


def _directional_refs() -> list[ReferenceItem]:
    names = [
        ("front", 0),
        ("front_right_34", 45),
        ("right", 90),
        ("back_right_34", 135),
        ("back", 180),
        ("back_left_34", 225),
        ("left", 270),
        ("front_left_34", 315),
    ]
    return [
        ReferenceItem(
            id=f"ref-{name}",
            role=ReferenceRole.CHARACTER_IDENTITY,
            artifact_id=f"artifact-{name}",
            metadata={"view": name, "azimuth_deg": angle},
        )
        for name, angle in names
    ]


@pytest.mark.parametrize(
    ("azimuth", "expected"),
    [
        (0, "front"),
        (45, "front_right_34"),
        (90, "right"),
        (135, "back_right_34"),
        (180, "back"),
        (225, "back_left_34"),
        (270, "left"),
        (315, "front_left_34"),
    ],
)
def test_camera_reference_matrix_selects_identity_pack_view(azimuth: float, expected: str) -> None:
    selection = select_reference_view(
        CameraSpec(azimuth_deg=azimuth), character_facing_deg=0, references=_directional_refs()
    )
    assert selection.view == expected
    assert selection.item is not None
    assert selection.angular_error_deg == 0
    assert selection.fallback is False


def test_camera_reference_boundaries_normalization_and_fallback() -> None:
    refs = _directional_refs()
    assert (
        select_reference_view(
            CameraSpec(azimuth_deg=360), character_facing_deg=0, references=refs
        ).view
        == "front"
    )
    assert (
        select_reference_view(
            CameraSpec(azimuth_deg=-45), character_facing_deg=0, references=refs
        ).view
        == "front_left_34"
    )
    assert select_reference_view(CameraSpec(), character_facing_deg=None, references=refs).fallback
    selection = select_reference_view(
        CameraSpec(azimuth_deg=30), character_facing_deg=0, references=refs[:1]
    )
    assert selection.view == "front"
    assert selection.fallback is True
    assert (
        select_reference_view(
            CameraSpec(azimuth_deg=30), character_facing_deg=0, references=[]
        ).item
        is None
    )


class _NoCallProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def send(self, request, *, idempotency_key):
        del request, idempotency_key
        self.calls += 1
        return "job"

    async def poll(self, provider_job_id):
        del provider_job_id
        return {"status": "completed"}


@pytest.mark.parametrize(
    "state",
    [
        ReadinessState.DRAFT,
        ReadinessState.ANALYZED,
        ReadinessState.ASSETS_PENDING,
        ReadinessState.REFERENCES_PENDING,
        ReadinessState.PREFLIGHT_FAILED,
        ReadinessState.LOCKED,
    ],
)
def test_non_ready_states_are_refused_before_provider_invocation(state: ReadinessState) -> None:
    async def run() -> None:
        from hevi.production_graph import DurableExecutionCoordinator

        provider = _NoCallProvider()
        shot = CanonicalShot(
            project_id="p",
            revision_id="r",
            scene_id="s",
            readiness_state=state,
        )
        envelope = TaskEnvelope(
            project_id="p",
            revision_id="r",
            shot_id=shot.id,
            stage="video_generation",
            execution_plan_id="plan",
            idempotency_key=f"key:{state}",
        )
        with pytest.raises(ReadinessTransitionError):
            await DurableExecutionCoordinator(InMemoryDurableExecutionStore()).execute(
                envelope, provider, {}, shot=shot
            )
        assert provider.calls == 0

    asyncio.run(run())


def test_qa_failed_regeneration_has_explicit_transition_path() -> None:
    shot = CanonicalShot(
        project_id="p", revision_id="r", scene_id="s", readiness_state=ReadinessState.QA_FAILED
    )
    queued = transition_shot(shot, ReadinessState.QUEUED)
    assert queued.readiness_state is ReadinessState.QUEUED
