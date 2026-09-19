"""D3-A/B: durable identity store + continuity gate behavior."""

from __future__ import annotations

import pytest

from hevi.creative.layer4.character_authority import VoiceIdentity
from hevi.creative.layer4.continuity_gate import (
    FactSource,
    GateError,
    GateRefusal,
    ProductionStage,
    gate_production_stage,
    record_production_fact,
)
from hevi.creative.layer4.identity_store import IdentityStore, identity_db_path
from hevi.creative.layer4.persistent_identity import (
    ContinuityCategory,
    ContinuitySeverity,
    PersistentIdentityRegistry,
)


def _store(tmp_path) -> IdentityStore:
    return IdentityStore(db_path=tmp_path / "identities.db")


def _registry() -> PersistentIdentityRegistry:
    return PersistentIdentityRegistry()


def _identity(registry: PersistentIdentityRegistry, owner: str = "user-1"):
    return registry.create_identity(
        owner_id=owner,
        canonical_name="Anna",
        voice=VoiceIdentity(voice_id="v-anna"),
        canon_constraints=("anna never leaves harbor city",),
    )


def test_identity_store_roundtrip_owner_scoped(tmp_path) -> None:
    store = _store(tmp_path)
    registry = _registry()
    identity = _identity(registry)
    binding = registry.bind(
        project_id="proj-a", identity_id=identity.identity_id, owner_id="user-1"
    )
    store.save_identity("user-1", identity.model_dump(mode="json"))
    store.save_binding("user-1", binding.model_dump(mode="json"))

    fresh = PersistentIdentityRegistry()
    snapshot_identities = store.load_identities("user-1")
    assert len(snapshot_identities) == 1
    fresh.restore(
        {
            "identities": snapshot_identities,
            "bindings": store.load_bindings("user-1"),
        }
    )
    assert fresh.get_identity(identity.identity_id, owner_id="user-1").canonical_name == (
        "Anna"
    )
    # Cross-owner reads see nothing.
    assert store.load_identities("user-2") == []
    assert store.load_bindings("user-2") == []


def test_subject_links_owner_scoped(tmp_path) -> None:
    store = _store(tmp_path)
    store.link_subject("user-1", "subject-1", "identity-1")
    assert store.subject_identity("user-1", "subject-1") == "identity-1"
    assert store.subject_identity("user-2", "subject-1") is None
    assert store.linked_subjects("user-1", "identity-1") == ["subject-1"]
    assert store.unlink_subject("user-1", "subject-1") is True
    assert store.subject_identity("user-1", "subject-1") is None
    assert store.unlink_subject("user-2", "subject-1") is False


def test_facts_append_only_history(tmp_path) -> None:
    store = _store(tmp_path)
    fact = {
        "fact_id": "f1",
        "identity_id": "i1",
        "category": "location",
        "statement": "harbor city",
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    store.save_fact("user-1", fact)
    # A rewrite attempt with the same fact_id cannot overwrite history.
    store.save_fact("user-1", {**fact, "statement": "desert outpost"})
    loaded = store.load_facts("user-1", "i1")
    assert len(loaded) == 1
    assert loaded[0]["statement"] == "harbor city"
    assert store.load_facts("user-2", "i1") == []


def test_record_production_fact_forces_inferred(tmp_path) -> None:
    store = _store(tmp_path)
    registry = _registry()
    identity = _identity(registry)
    inferred = record_production_fact(
        store=store,
        registry=registry,
        owner_id="user-1",
        identity_id=identity.identity_id,
        category=ContinuityCategory.LOCATION,
        statement="harbor city",
        source="llm-guess",
    )
    assert inferred.provenance == "inferred"
    approved = record_production_fact(
        store=store,
        registry=registry,
        owner_id="user-1",
        identity_id=identity.identity_id,
        category=ContinuityCategory.PROP,
        statement="holds brass compass",
        source=FactSource.APPROVED_SHOT_RESULT,
        source_artifact_id="artifact-9",
        episode="ep1",
        scene="sc1",
        shot="sh2",
        revision="rev-3",
    )
    assert approved.provenance == "approved-shot-result"
    assert approved.revision == "rev-3"
    # Durable: facts survive a registry restart.
    fresh = PersistentIdentityRegistry()
    fresh.restore({"identities": [], "bindings": []})
    for row in store.load_facts("user-1", identity.identity_id):
        from hevi.creative.layer4.persistent_identity import ContinuityFactRecord

        fresh.ledger.record(ContinuityFactRecord.model_validate(row))
    assert len(fresh.ledger.facts_for_identity(identity.identity_id)) == 2


def test_gate_pass_and_decision_persisted(tmp_path) -> None:
    store = _store(tmp_path)
    registry = _registry()
    identity = _identity(registry)
    binding = registry.bind(
        project_id="proj-a", identity_id=identity.identity_id, owner_id="user-1"
    )
    decision = gate_production_stage(
        store=store,
        registry=registry,
        binding=binding,
        owner_id="user-1",
        stage=ProductionStage.REFERENCE_PREPARATION,
    )
    assert decision.verdict is ContinuitySeverity.PASS
    decisions = store.load_decisions("user-1", binding_id=binding.binding_id)
    assert len(decisions) == 1
    assert decisions[0]["verdict"] == "pass"


def test_gate_block_refuses_paid_generation(tmp_path) -> None:
    store = _store(tmp_path)
    registry = _registry()
    identity = _identity(registry)
    binding = registry.bind(
        project_id="proj-a", identity_id=identity.identity_id, owner_id="user-1"
    )
    with pytest.raises(GateRefusal, match="CONTINUITY_GATE_BLOCKED"):
        gate_production_stage(
            store=store,
            registry=registry,
            binding=binding,
            owner_id="user-1",
            stage=ProductionStage.VIDEO_GENERATION,
            planned_statements=("Plot twist: not anna never leaves harbor city",),
        )
    # BLOCK persists an audited (non-override) decision so metrics can count
    # the refusal; paid generation is still refused.
    decisions = store.load_decisions("user-1", binding_id=binding.binding_id)
    assert decisions and decisions[-1]["verdict"] == "block"
    assert decisions[-1]["overridden_by"] == ""
    with pytest.raises(GateRefusal):
        # No override path can turn a BLOCK into a paid enqueue.
        gate_production_stage(
            store=store,
            registry=registry,
            binding=binding,
            owner_id="user-1",
            stage=ProductionStage.VIDEO_GENERATION,
            planned_statements=("Plot twist: not anna never leaves harbor city",),
            overridden_by="user-1",
        )


def test_gate_warn_needs_audited_override(tmp_path) -> None:
    store = _store(tmp_path)
    registry = _registry()
    identity = _identity(registry)
    record_production_fact(
        store=store,
        registry=registry,
        owner_id="user-1",
        identity_id=identity.identity_id,
        category=ContinuityCategory.LOCATION,
        statement="harbor city",
        source=FactSource.CANON,
    )
    binding = registry.bind(
        project_id="proj-a", identity_id=identity.identity_id, owner_id="user-1"
    )
    with pytest.raises(GateError, match="CONTINUITY_GATE_WARN_NEEDS_OVERRIDE"):
        gate_production_stage(
            store=store,
            registry=registry,
            binding=binding,
            owner_id="user-1",
            stage=ProductionStage.VOICE_GENERATION,
            planned_voice_id="v-wrong",
        )
    decision = gate_production_stage(
        store=store,
        registry=registry,
        binding=binding,
        owner_id="user-1",
        stage=ProductionStage.VOICE_GENERATION,
        planned_voice_id="v-wrong",
        overridden_by="user-1",
    )
    assert decision.verdict is ContinuitySeverity.WARN
    assert "IDENTITY_VOICE_MISMATCH" in decision.warn_codes
    decisions = store.load_decisions("user-1", binding_id=binding.binding_id)
    assert decisions[-1]["overridden_by"] == "user-1"


def test_gate_sparse_data_never_fake_pass(tmp_path) -> None:
    store = _store(tmp_path)
    registry = _registry()
    identity = _identity(registry)
    binding = registry.bind(
        project_id="proj-a", identity_id=identity.identity_id, owner_id="user-1"
    )
    # Empty ledger + location plan: WARN (sparse), not PASS.
    with pytest.raises(GateError, match="CONTINUITY_GATE_WARN_NEEDS_OVERRIDE"):
        gate_production_stage(
            store=store,
            registry=registry,
            binding=binding,
            owner_id="user-1",
            stage=ProductionStage.STORYBOARD_APPROVAL,
            planned_location="harbor city",
        )


def test_identity_db_path_env_override(monkeypatch) -> None:
    monkeypatch.setenv("HEVI_IDENTITY_DB", "/tmp/d3_probe_identity.db")
    assert str(identity_db_path()) == "/tmp/d3_probe_identity.db"
