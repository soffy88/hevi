"""D4-F: metrics computed from canonical state, nothing else."""

from __future__ import annotations

from hevi.creative.layer4.character_authority import VoiceIdentity
from hevi.creative.layer4.continuity_gate import (
    GateRefusal,
    ProductionStage,
    gate_production_stage,
)
from hevi.creative.layer4.differentiation_metrics import compute_metrics
from hevi.creative.layer4.identity_store import IdentityStore, load_owner_registry
from hevi.creative.layer4.incident_store import IncidentService, IncidentStore
from hevi.creative.layer4.persistent_identity import PersistentIdentityRegistry
from hevi.creative.layer4.repair_incident import RepairLoopGuard


def test_metrics_from_canonical_state(tmp_path) -> None:
    identity_store = IdentityStore(db_path=tmp_path / "identities.db")
    incident_store = IncidentStore(db_path=tmp_path / "incidents.db")

    registry = PersistentIdentityRegistry()
    identity = registry.create_identity(
        owner_id="user-1", canonical_name="Anna", voice=VoiceIdentity(voice_id="v-anna"),
        canon_constraints=("anna never leaves harbor city",),
    )
    identity_store.save_identity("user-1", identity.model_dump(mode="json"))
    binding_a = registry.bind(project_id="proj-a", identity_id=identity.identity_id, owner_id="user-1")
    binding_b = registry.bind(project_id="proj-b", identity_id=identity.identity_id, owner_id="user-1")
    identity_store.save_binding("user-1", binding_a.model_dump(mode="json"))
    identity_store.save_binding("user-1", binding_b.model_dump(mode="json"))

    loaded = load_owner_registry(identity_store, "user-1")
    bound = loaded.get_binding(binding_a.binding_id, owner_id="user-1")
    try:
        gate_production_stage(
            store=identity_store, registry=loaded, binding=bound, owner_id="user-1",
            stage=ProductionStage.VIDEO_GENERATION,
            planned_statements=["Twist: not anna never leaves harbor city"],
            overridden_by="user-1",
        )
        raise AssertionError("expected GateRefusal")
    except GateRefusal:
        pass
    gate_production_stage(
        store=identity_store, registry=loaded, binding=bound, owner_id="user-1",
        stage=ProductionStage.REFERENCE_PREPARATION, overridden_by="user-1",
    )

    service = IncidentService(
        store=incident_store, loop_guard=RepairLoopGuard(cooldown_seconds=0.0)
    )
    auto = service.open_or_get(
        production_run_id="run-m", node_key="task.run", failure="PROVIDER_FAILURE",
        evidence={"signature": "provider temporarily unavailable", "transient": True},
        owner_id="user-1",
    )
    service.open_or_get(  # dedupe hit, not a new incident
        production_run_id="run-m", node_key="task.run", failure="PROVIDER_FAILURE",
        evidence={"signature": "provider temporarily unavailable", "transient": True},
        owner_id="user-1",
    )
    service.authorize(auto.incident_id, auto.candidate_actions[0], confirmed=True, owner_id="user-1")
    service.record_execution(auto.incident_id, owner_id="user-1")
    service.verify(
        auto.incident_id,
        {"task_ok": True, "artifact_ok": True, "currency_ok": True, "presentation_ok": True},
        preserved_artifact_ids=("artifact-1", "artifact-2"),
        preserved_intact=True, owner_id="user-1",
    )
    paid = service.open_or_get(
        production_run_id="run-p", node_key="shot.regenerate", failure="DELIVERY_INTEGRITY",
        evidence={"signature": "artifact stale, paid regeneration requested",
                  "may_incur_cost": True, "estimated_cost_usd": 2.0},
        owner_id="user-1",
    )
    service.authorize(paid.incident_id, paid.candidate_actions[0], confirmed=True, owner_id="user-1")
    service.record_execution(paid.incident_id, owner_id="user-1")
    service.verify(
        paid.incident_id,
        {"task_ok": True, "artifact_ok": True, "currency_ok": True, "presentation_ok": True},
        owner_id="user-1",
    )
    doomed = service.open_or_get(
        production_run_id="run-f", node_key="task.run", failure="PROVIDER_FAILURE",
        evidence={"signature": "provider temporarily unavailable", "transient": True},
        owner_id="user-1",
    )
    service.authorize(doomed.incident_id, doomed.candidate_actions[0], confirmed=True, owner_id="user-1")
    service.record_execution(doomed.incident_id, owner_id="user-1")
    service.verify(
        doomed.incident_id,
        {"task_ok": False, "artifact_ok": False, "currency_ok": False, "presentation_ok": False},
        owner_id="user-1",
    )

    metrics = compute_metrics(identity_store, incident_store)
    assert metrics["IDENTITY_REUSE_RATE"] == 2.0
    assert metrics["CONTINUITY_BLOCKS_CAUGHT"] == 1
    assert metrics["CONTINUITY_WARNINGS_OVERRIDDEN"] == 0
    assert metrics["AUTO_SAFE_REPAIRS"] == 1
    assert metrics["PAID_REPAIRS_CONFIRMED"] == 1
    assert metrics["FAILED_REPAIRS"] == 1
    assert metrics["REPAIR_MEAN_ATTEMPTS"] == 1.0
    assert metrics["DUPLICATE_BILLING_PREVENTED"] == 1
    assert metrics["ARTIFACTS_PRESERVED_BY_REPAIR"] == 2
