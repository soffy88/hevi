"""D4-C: self-healing soak/chaos — incidents stay controlled under fire."""

from __future__ import annotations

import pytest

from hevi.creative.layer4.incident_store import IncidentService, IncidentStore
from hevi.creative.layer4.plan_projection import RepairKind
from hevi.creative.layer4.repair_incident import (
    IncidentError,
    IncidentStatus,
    ProjectRepairPolicy,
    RepairActionProposal,
    RepairLoopGuard,
    RepairPolicy,
)


def _service(tmp_path, name="incidents.db", **kwargs) -> IncidentService:
    kwargs.setdefault("loop_guard", RepairLoopGuard(cooldown_seconds=0.0))
    return IncidentService(store=IncidentStore(db_path=tmp_path / name), **kwargs)


def _transient_evidence() -> dict:
    return {"signature": "provider temporarily unavailable", "transient": True}


def test_incident_storm_dedupes_to_one(tmp_path) -> None:
    service = _service(tmp_path)
    ids = {
        service.open_or_get(
            production_run_id="run-storm", node_key="task.run",
            failure="PROVIDER_FAILURE", evidence=_transient_evidence(),
        ).incident_id
        for _ in range(20)
    }
    assert ids and len(ids) == 1
    open_incidents = service.list_incidents(production_run_id="run-storm")
    assert len(open_incidents) == 1


def test_mixed_failures_link_by_run(tmp_path) -> None:
    service = _service(tmp_path)
    cases = [
        ("rate limit hit", {"signature": "rate limit exceeded"}),
        ("download broke", {"signature": "download interrupted at 62%"}),
        ("stale", {"stale_dependency_revision": True}),
        ("no ref", {"missing_reference": "anna/stage"}),
        ("provider down", {"signature": "provider temporarily unavailable", "transient": True}),
        ("worker died", {"worker_restart": True}),
        ("bad artifact", {"invalid_artifact": True}),
    ]
    ids = [
        service.open_or_get(
            production_run_id="run-mixed", node_key=f"node-{i}",
            failure=failure, evidence=evidence,
        ).incident_id
        for i, (failure, evidence) in enumerate(cases)
    ]
    assert len(set(ids)) == len(cases)  # distinct causes stay distinct
    assert len(service.list_incidents(production_run_id="run-mixed")) == len(cases)
    assert service.list_incidents(production_run_id="other-run") == []


def test_restart_at_every_lifecycle_stage(tmp_path) -> None:
    db = tmp_path / "incidents.db"

    def fresh() -> IncidentService:
        return IncidentService(
            store=IncidentStore(db_path=db),
            loop_guard=RepairLoopGuard(cooldown_seconds=0.0),
        )

    # Stage 1: created.
    incident = fresh().open_or_get(
        production_run_id="run-stages", node_key="task.run",
        failure="PROVIDER_FAILURE", evidence=_transient_evidence(),
    )
    incident_id = incident.incident_id
    assert fresh().get(incident_id).status is IncidentStatus.OPEN

    # Stage 2: planned (CONFIRM_REQUIRED paid action, unconfirmed).
    service = fresh()
    paid = service.open_or_get(
        production_run_id="run-stages-paid", node_key="shot.regenerate",
        failure="DELIVERY_INTEGRITY",
        evidence={"signature": "artifact stale, paid regeneration requested",
                  "may_incur_cost": True, "estimated_cost_usd": 2.0},
    )
    paid_action = paid.candidate_actions[0]
    approved, _ = service.authorize(paid.incident_id, paid_action, confirmed=False)
    assert approved is False
    assert fresh().get(paid.incident_id).status is IncidentStatus.REPAIR_PLANNED

    # Stage 3: running (authorized + recorded).
    service = fresh()
    incident = service.get(incident_id)
    action = incident.candidate_actions[0]
    approved, _ = service.authorize(incident_id, action, confirmed=True)
    assert approved is True
    service.record_execution(incident_id)
    resumed = fresh().get(incident_id)
    assert resumed.status is IncidentStatus.REPAIR_EXECUTING
    assert resumed.attempts == 1

    # Stage 4: verification evidence split across restart.
    fresh().verify(incident_id, {"task_ok": True, "artifact_ok": False,
                                 "currency_ok": True, "presentation_ok": True})
    assert fresh().get(incident_id).status is IncidentStatus.REPAIR_FAILED

    # Stage 5: resolved persists.
    service = fresh()
    approved, _ = service.authorize(incident_id, action, confirmed=True)
    assert approved is True
    service.record_execution(incident_id)
    service.verify(incident_id, {"task_ok": True, "artifact_ok": True,
                                 "currency_ok": True, "presentation_ok": True})
    assert fresh().get(incident_id).status is IncidentStatus.RESOLVED


def test_repair_exhaustion_stops(tmp_path) -> None:
    service = _service(
        tmp_path, loop_guard=RepairLoopGuard(max_attempts=2, cooldown_seconds=0.0)
    )
    incident = service.open_or_get(
        production_run_id="run-doomed", node_key="task.run",
        failure="PROVIDER_FAILURE", evidence=_transient_evidence(),
    )
    action = incident.candidate_actions[0]
    for _ in range(2):
        approved, _ = service.authorize(incident.incident_id, action, confirmed=True)
        assert approved is True
        service.record_execution(incident.incident_id)
        failed = service.verify(incident.incident_id, {"task_ok": False, "artifact_ok": False,
                                                       "currency_ok": False, "presentation_ok": False})
        assert failed.status is IncidentStatus.REPAIR_FAILED
    approved, reason = service.authorize(incident.incident_id, action, confirmed=True)
    assert approved is False
    assert reason == "max_repair_attempts_reached"
    # Terminal: nothing auto-retries; record/verify without authorization refuse.
    with pytest.raises(IncidentError):
        service.record_execution(incident.incident_id)


def test_cost_ceiling(tmp_path) -> None:
    service = _service(tmp_path)
    incident = service.open_or_get(
        production_run_id="run-cost", node_key="shot.regenerate",
        failure="DELIVERY_INTEGRITY",
        evidence={"signature": "artifact stale, paid regeneration requested",
                  "may_incur_cost": True, "estimated_cost_usd": 2.0},
    )
    action = incident.candidate_actions[0]
    assert action.policy is RepairPolicy.CONFIRM_REQUIRED
    # AUTO_SAFE zero-cost path executes free.
    free = service.open_or_get(
        production_run_id="run-cost", node_key="task.run",
        failure="PROVIDER_FAILURE", evidence=_transient_evidence(),
    )
    free_action = free.candidate_actions[0]
    assert free_action.policy is RepairPolicy.AUTO_SAFE
    assert free_action.estimated_cost_usd == 0.0
    approved, _ = service.authorize(free.incident_id, free_action, confirmed=True)
    assert approved is True
    # Paid path without confirmation never authorizes: billed 0.
    approved, reason = service.authorize(incident.incident_id, action, confirmed=False)
    assert approved is False and reason == "confirmation_required"
    # Budget-bound policy: within budget executes, above budget blocks.
    budgeted = _service(
        tmp_path, name="budgeted.db",
        project_policy=ProjectRepairPolicy(
            allow_budget_bound_auto_repair=True, auto_budget_usd=5.0),
    )
    cheap = RepairActionProposal(kind=RepairKind.RETRY_TARGET, policy=RepairPolicy.AUTO_SAFE,
                                 estimated_cost_usd=1.0)
    pricey = RepairActionProposal(kind=RepairKind.RETRY_TARGET, policy=RepairPolicy.AUTO_SAFE,
                                  estimated_cost_usd=50.0)
    incident2 = budgeted.open_or_get(
        production_run_id="run-budget", node_key="task.run",
        failure="PROVIDER_FAILURE", evidence=_transient_evidence(),
    )
    assert budgeted.authorize(incident2.incident_id, cheap, confirmed=True)[0] is True
    incident3 = budgeted.open_or_get(
        production_run_id="run-budget-2", node_key="task.run",
        failure="PROVIDER_FAILURE", evidence=_transient_evidence(),
    )
    approved, _ = budgeted.authorize(incident3.incident_id, pricey, confirmed=False)
    assert approved is False
