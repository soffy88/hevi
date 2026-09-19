"""D2-C gates: incident, deterministic-first, policy, cost, verify, loops."""

from __future__ import annotations

import pytest

from hevi.creative.layer4.currency import (
    ArtifactBasis,
    ArtifactCurrency,
    assert_no_usable_loss,
    evaluate_currency,
)
from hevi.creative.layer4.plan_projection import RepairKind
from hevi.creative.layer4.repair_incident import (
    IncidentError,
    IncidentStatus,
    ProjectRepairPolicy,
    RepairActionProposal,
    RepairLoopGuard,
    RepairPolicy,
    RootCauseCategory,
    SelfHealingCoordinator,
    classify_deterministic,
)

FULL_EVIDENCE = {
    "task_ok": True,
    "artifact_ok": True,
    "currency_ok": True,
    "presentation_ok": True,
}


def _coordinator(**kwargs) -> SelfHealingCoordinator:
    guard = RepairLoopGuard(
        max_attempts=int(kwargs.pop("max_attempts", 3)),
        cooldown_seconds=float(kwargs.pop("cooldown_seconds", 0.0)),
    )
    return SelfHealingCoordinator(project_policy=kwargs.pop("policy", None), loop_guard=guard)


def _cycle(coordinator: SelfHealingCoordinator, incident_id: str, **verify_kwargs):
    incident = coordinator.get(incident_id)
    assert incident.candidate_actions, "deterministic case must propose an action"
    action = incident.candidate_actions[0]
    ok, reason = coordinator.authorize(incident_id, action, **verify_kwargs.pop("auth", {}))
    assert ok, reason
    coordinator.record_execution(incident_id)
    return coordinator.verify(
        incident_id, verify_kwargs.pop("verification", FULL_EVIDENCE), **verify_kwargs
    )


def test_provider_temporary_failure_auto_safe_resolved() -> None:
    coordinator = _coordinator()
    incident = coordinator.open_incident(
        production_run_id="run-1",
        node_key="shot.render",
        failure="PROVIDER_FAILURE",
        evidence={"signature": "provider temporarily unavailable, timeout", "transient": True},
    )
    assert incident.root_cause is RootCauseCategory.PROVIDER_TEMP_UNAVAILABLE
    assert not incident.needs_agent
    assert incident.candidate_actions[0].policy is RepairPolicy.AUTO_SAFE
    resolved = _cycle(coordinator, incident.incident_id)
    assert resolved.status is IncidentStatus.RESOLVED
    assert resolved.attempts == 1


def test_download_interruption_resume_resolved() -> None:
    coordinator = _coordinator()
    incident = coordinator.open_incident(
        production_run_id="run-1",
        node_key="artifact.download",
        failure="DELIVERY_INTEGRITY",
        evidence={"signature": "download interrupted at 62%"},
    )
    assert incident.root_cause is RootCauseCategory.EXPIRED_DOWNLOAD_URL
    resolved = _cycle(coordinator, incident.incident_id)
    assert resolved.status is IncidentStatus.RESOLVED


def test_stale_artifact_local_regen_preserves_previous() -> None:
    coordinator = _coordinator()
    incident = coordinator.open_incident(
        production_run_id="run-2",
        node_key="scene.compose",
        failure="SCENE_CONTINUITY",
        artifact_id="artifact-stale-1",
        evidence={"signature": "artifact stale due dependency revision"},
    )
    assert incident.root_cause is RootCauseCategory.STALE_DEPENDENCY_REVISION
    resolved = _cycle(
        coordinator,
        incident.incident_id,
        preserved_artifact_ids=("artifact-good-1", "artifact-good-2"),
        preserved_intact=True,
    )
    assert resolved.status is IncidentStatus.RESOLVED


def test_unsupported_provider_param_adjust_resolved() -> None:
    coordinator = _coordinator()
    incident = coordinator.open_incident(
        production_run_id="run-3",
        node_key="provider.render",
        failure="PROVIDER_FAILURE",
        evidence={"unsupported_param": "lip_sync_strength"},
    )
    assert incident.root_cause is RootCauseCategory.UNSUPPORTED_PROVIDER_PARAM
    resolved = _cycle(coordinator, incident.incident_id)
    assert resolved.status is IncidentStatus.RESOLVED


def test_missing_reference_manual_only_no_auto_execution() -> None:
    coordinator = _coordinator()
    incident = coordinator.open_incident(
        production_run_id="run-4",
        node_key="scene.cast",
        failure="IDENTITY_MISMATCH",
        evidence={"missing_reference": "anna/stage-outfit"},
    )
    assert incident.root_cause is RootCauseCategory.MISSING_REFERENCE
    action = incident.candidate_actions[0]
    assert action.policy is RepairPolicy.MANUAL_ONLY
    ok, reason = coordinator.authorize(incident.incident_id, action)
    assert not ok
    assert reason == "manual_only_escalated"
    assert coordinator.get(incident.incident_id).status is IncidentStatus.ESCALATED_MANUAL
    with pytest.raises(IncidentError, match="REPAIR_EXECUTION_NOT_AUTHORIZED"):
        coordinator.record_execution(incident.incident_id)


def test_paid_regeneration_requires_confirmation() -> None:
    coordinator = _coordinator()
    incident = coordinator.open_incident(
        production_run_id="run-5",
        node_key="shot.render",
        failure="DELIVERY_INTEGRITY",
        evidence={
            "signature": "artifact stale due dependency revision",
            "may_incur_cost": True,
            "estimated_cost_usd": 1.5,
        },
    )
    assert incident.root_cause is RootCauseCategory.PAID_REGENERATION_NEEDED
    action = incident.candidate_actions[0]
    assert action.policy is RepairPolicy.CONFIRM_REQUIRED
    # Hidden rebilling guard: unconfirmed paid work never executes.
    ok, reason = coordinator.authorize(incident.incident_id, action, confirmed=False)
    assert not ok
    assert reason == "confirmation_required"
    with pytest.raises(IncidentError, match="REPAIR_EXECUTION_NOT_AUTHORIZED"):
        coordinator.record_execution(incident.incident_id)
    # Explicit confirmation: executes, then verifies.
    resolved = _cycle(
        coordinator, incident.incident_id, auth={"confirmed": True}
    )
    assert resolved.status is IncidentStatus.RESOLVED


def test_costly_action_cannot_ride_auto_path() -> None:
    coordinator = _coordinator()
    incident = coordinator.open_incident(
        production_run_id="run-6",
        node_key="shot.render",
        failure="PROVIDER_FAILURE",
        evidence={"signature": "provider temporarily unavailable", "transient": True},
    )
    sneaky = RepairActionProposal(
        kind=RepairKind.RETRY_TARGET,
        detail="retry with paid upscale attached",
        policy=RepairPolicy.AUTO_SAFE,
        estimated_cost_usd=2.0,
    )
    ok, reason = coordinator.authorize(incident.incident_id, sneaky, confirmed=False)
    assert not ok
    assert reason == "confirmation_required"


def test_budget_bound_auto_repair_allowed_by_project_policy() -> None:
    policy = ProjectRepairPolicy(allow_budget_bound_auto_repair=True, auto_budget_usd=5.0)
    coordinator = _coordinator(policy=policy)
    incident = coordinator.open_incident(
        production_run_id="run-7",
        node_key="shot.render",
        failure="PROVIDER_FAILURE",
        evidence={"signature": "provider temporarily unavailable", "transient": True},
    )
    cheap = RepairActionProposal(
        kind=RepairKind.RETRY_TARGET,
        detail="retry within approved auto budget",
        policy=RepairPolicy.AUTO_SAFE,
        estimated_cost_usd=1.0,
    )
    ok, reason = coordinator.authorize(incident.incident_id, cheap)
    assert ok, reason


def test_failed_repair_requires_full_evidence() -> None:
    coordinator = _coordinator()
    incident = coordinator.open_incident(
        production_run_id="run-8",
        node_key="shot.render",
        failure="PROVIDER_FAILURE",
        evidence={"signature": "provider temporarily unavailable", "transient": True},
    )
    failed = _cycle(
        coordinator,
        incident.incident_id,
        verification={"task_ok": True, "artifact_ok": False, "currency_ok": True,
                      "presentation_ok": True},
    )
    assert failed.status is IncidentStatus.REPAIR_FAILED
    assert failed.verification_result["artifact_ok"] is False


def test_lost_preserved_artifact_blocks_resolved() -> None:
    coordinator = _coordinator()
    incident = coordinator.open_incident(
        production_run_id="run-9",
        node_key="scene.compose",
        failure="SCENE_CONTINUITY",
        evidence={"signature": "artifact stale due dependency revision"},
    )
    result = _cycle(
        coordinator,
        incident.incident_id,
        preserved_artifact_ids=("artifact-good-1",),
        preserved_intact=False,
    )
    assert result.status is IncidentStatus.REPAIR_FAILED


def test_duplicate_execution_refused_no_side_effects() -> None:
    coordinator = _coordinator()
    incident = coordinator.open_incident(
        production_run_id="run-10",
        node_key="shot.render",
        failure="PROVIDER_FAILURE",
        evidence={"signature": "provider temporarily unavailable", "transient": True},
    )
    action = incident.candidate_actions[0]
    ok, _ = coordinator.authorize(incident.incident_id, action)
    assert ok
    coordinator.record_execution(incident.incident_id)
    # Second record without a new authorization cycle = double apply: refused.
    with pytest.raises(IncidentError, match="REPAIR_DUPLICATE_EXECUTION_REFUSED"):
        coordinator.record_execution(incident.incident_id)
    assert coordinator.get(incident.incident_id).attempts == 1


def test_max_attempts_stop_infinite_loops() -> None:
    coordinator = _coordinator(max_attempts=2)
    incident = coordinator.open_incident(
        production_run_id="run-11",
        node_key="shot.render",
        failure="PROVIDER_FAILURE",
        evidence={"signature": "provider temporarily unavailable", "transient": True},
    )
    action = incident.candidate_actions[0]
    for _ in range(2):
        ok, reason = coordinator.authorize(incident.incident_id, action)
        assert ok, reason
        coordinator.record_execution(incident.incident_id)
        failed = coordinator.verify(
            incident.incident_id,
            {"task_ok": False, "artifact_ok": False, "currency_ok": False,
             "presentation_ok": False},
        )
        assert failed.status is IncidentStatus.REPAIR_FAILED
    ok, reason = coordinator.authorize(incident.incident_id, action)
    assert not ok
    assert reason == "max_repair_attempts_reached"


def test_cooldown_blocks_immediate_retry() -> None:
    guard = RepairLoopGuard(max_attempts=3, cooldown_seconds=60.0, now=1000.0)
    coordinator = SelfHealingCoordinator(loop_guard=guard)
    incident = coordinator.open_incident(
        production_run_id="run-12",
        node_key="shot.render",
        failure="PROVIDER_FAILURE",
        evidence={"signature": "provider temporarily unavailable", "transient": True},
    )
    action = incident.candidate_actions[0]
    ok, _ = coordinator.authorize(incident.incident_id, action)
    assert ok
    coordinator.record_execution(incident.incident_id)
    coordinator.verify(
        incident.incident_id,
        {"task_ok": False, "artifact_ok": False, "currency_ok": False,
         "presentation_ok": False},
    )
    ok, reason = coordinator.authorize(incident.incident_id, action)
    assert not ok
    assert reason == "repair_cooldown_active"


def test_unknown_failure_needs_agent_proposal_only() -> None:
    coordinator = _coordinator()
    incident = coordinator.open_incident(
        production_run_id="run-13",
        node_key="scene.direct",
        failure="STYLE_DRIFT",
        evidence={"signature": "mysterious new aesthetic drift, needs creative call"},
    )
    assert incident.root_cause is RootCauseCategory.UNKNOWN_NEEDS_AGENT
    assert incident.needs_agent
    assert incident.candidate_actions == ()
    # Agent proposes into the graph; coordinator still never executes.
    proposal = RepairActionProposal(
        kind=RepairKind.REPLAN,
        target_id="scene.direct",
        detail="agent: restyle scene per director note",
        policy=RepairPolicy.CONFIRM_REQUIRED,
    )
    planned = coordinator.propose_agent_action(incident.incident_id, proposal)
    assert planned.status is IncidentStatus.REPAIR_PLANNED
    # Agent-proposed paid work is forced through confirmation.
    paid = RepairActionProposal(
        kind=RepairKind.SWITCH_PROVIDER,
        detail="agent: switch to premium provider",
        policy=RepairPolicy.AUTO_SAFE,
        estimated_cost_usd=3.0,
    )
    planned2 = coordinator.propose_agent_action(incident.incident_id, paid)
    assert planned2.candidate_actions[-1].policy is RepairPolicy.CONFIRM_REQUIRED


def test_e2e_diff3_failure_to_verified_presentation_current() -> None:
    """E2E-DIFF-3: real currency detect -> incident -> repair -> real re-verify.

    Verification evidence is derived from REAL ``evaluate_currency`` runs
    before/after the repair, not canned booleans. ``assert_no_usable_loss``
    proves the previous valid artifact survived the repair.
    """
    coordinator = _coordinator()
    deps = {"graph": "8", "prompt": "2"}

    before = evaluate_currency(
        ArtifactBasis(
            artifact_id="artifact-scene-1",
            role="scene_video",
            exists=True,
            integrity_ok=True,
            dependency_revision="graph@7+prompt@2",
        ),
        deps,
    )
    assert before.currency is ArtifactCurrency.STALE

    incident = coordinator.open_incident(
        production_run_id="run-e2e-3",
        node_key="scene.compose",
        failure="SCENE_CONTINUITY",
        artifact_id="artifact-scene-1",
        evidence={"signature": "artifact stale due dependency revision"},
    )
    action = incident.candidate_actions[0]
    ok, reason = coordinator.authorize(incident.incident_id, action)
    assert ok, reason
    coordinator.record_execution(incident.incident_id)

    # The existing runtime regenerates; the artifact now matches deps.
    after = evaluate_currency(
        ArtifactBasis(
            artifact_id="artifact-scene-1",
            role="scene_video",
            exists=True,
            integrity_ok=True,
            dependency_revision="graph@8+prompt@2",
        ),
        deps,
    )
    assert after.currency is ArtifactCurrency.CURRENT
    assert_no_usable_loss((before,), (after,), ("scene_video",))

    resolved = coordinator.verify(
        incident.incident_id,
        {
            "task_ok": True,
            "artifact_ok": after.currency is ArtifactCurrency.CURRENT,
            "currency_ok": after.usable,
            "presentation_ok": True,
        },
        preserved_artifact_ids=("artifact-scene-1",),
        preserved_intact=True,
    )
    assert resolved.status is IncidentStatus.RESOLVED


def test_deterministic_first_no_agent_for_known_signatures() -> None:
    cases = [
        ("X", {"download_url_expired": True}, RootCauseCategory.EXPIRED_DOWNLOAD_URL),
        ("PROVIDER_FAILURE", {"transient": True, "signature": "timeout"}, RootCauseCategory.PROVIDER_TEMP_UNAVAILABLE),
        ("X", {"stale_dependency_revision": True}, RootCauseCategory.STALE_DEPENDENCY_REVISION),
        ("X", {"signature": "unsupported resolution 8k"}, RootCauseCategory.UNSUPPORTED_RESOLUTION),
        ("X", {"worker_restart": True}, RootCauseCategory.WORKER_RESTART),
        ("X", {"signature": "credential expired"}, RootCauseCategory.CREDENTIAL_MISSING),
    ]
    for failure, evidence, expected in cases:
        cause, proposal, needs_agent = classify_deterministic(failure, evidence)
        assert cause is expected, failure
        assert proposal is not None
        assert needs_agent is False
