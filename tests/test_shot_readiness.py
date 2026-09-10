from __future__ import annotations

import pytest

from hevi.production_graph import (
    CanonicalShot,
    ReadinessContext,
    ReadinessState,
    ReadinessTransitionError,
    ReferenceRole,
    assert_dispatchable,
    prepare_shot,
    transition_shot,
)


def test_readiness_gate_returns_machine_readable_blockers() -> None:
    shot = CanonicalShot(project_id="p", revision_id="r", scene_id="s")
    prepared, result = prepare_shot(
        shot,
        ReadinessContext(
            assets_ready=False,
            required_reference_roles={ReferenceRole.CHARACTER_IDENTITY},
            available_reference_roles=set(),
            budget_available=False,
        ),
    )
    assert prepared.readiness_state is ReadinessState.ASSETS_PENDING
    assert result.passed is False
    assert {item["code"] for item in result.blockers} >= {"ASSETS_PENDING", "BUDGET_EXCEEDED"}
    assert result.checks["narrative"] is True


def test_ready_is_only_dispatchable_state() -> None:
    shot = CanonicalShot(project_id="p", revision_id="r", scene_id="s")
    with pytest.raises(ReadinessTransitionError, match="requires READY"):
        assert_dispatchable(shot)
    analyzed = transition_shot(shot, ReadinessState.ANALYZED)
    ready = transition_shot(analyzed, ReadinessState.READY)
    assert_dispatchable(ready)
    assert transition_shot(ready, ReadinessState.QUEUED).readiness_state is ReadinessState.QUEUED


def test_illegal_readiness_transitions_and_locked_shots_are_rejected() -> None:
    shot = CanonicalShot(project_id="p", revision_id="r", scene_id="s")
    with pytest.raises(ReadinessTransitionError, match="illegal"):
        transition_shot(shot, ReadinessState.GENERATING)
    locked = shot.model_copy(update={"readiness_state": ReadinessState.LOCKED})
    with pytest.raises(ReadinessTransitionError, match="illegal"):
        transition_shot(locked, ReadinessState.DRAFT)
