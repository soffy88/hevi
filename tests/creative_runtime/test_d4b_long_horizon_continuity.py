"""D4-B: long-horizon continuity — history preserved, validation deterministic."""

from __future__ import annotations

from hevi.creative.layer4.character_authority import VoiceIdentity
from hevi.creative.layer4.continuity_gate import (
    FactSource,
    GateRefusal,
    ProductionStage,
    gate_production_stage,
    record_production_fact,
)
from hevi.creative.layer4.identity_store import IdentityStore
from hevi.creative.layer4.persistent_identity import (
    ContinuityCategory,
    ContinuityFactRecord,
    ContinuitySeverity,
    PersistentIdentityRegistry,
    validate_pre_production,
)


def _setup(tmp_path):
    store = IdentityStore(db_path=tmp_path / "identities.db")
    registry = PersistentIdentityRegistry()
    identity = registry.create_identity(
        owner_id="user-1", canonical_name="Anna", voice=VoiceIdentity(voice_id="v-anna"),
        canon_constraints=("anna never leaves harbor city",),
    )
    return store, registry, identity


def _fact(registry, store, identity_id, category, statement, episode, scene, shot,
          revision, source=FactSource.APPROVED_SHOT_RESULT, provenance_override="",
          supersedes=""):
    fact = ContinuityFactRecord(
        fact_id=f"fact-{episode}-{scene}-{shot}-{category.value}-{revision}",
        identity_id=identity_id,
        category=category,
        statement=statement,
        episode=episode, scene=scene, shot=shot, revision=revision,
        source_artifact_id=f"artifact-{episode}",
        provenance=provenance_override or source.value,
        supersedes=supersedes,
    )
    registry.ledger.record(fact)
    store.save_fact("user-1", fact.model_dump(mode="json"))
    return fact


def test_multi_episode_fact_lifecycle(tmp_path) -> None:
    store, registry, identity = _setup(tmp_path)
    iid = identity.identity_id
    # 3 episodes x 4 scenes x 3 shots = 36 shots of appearance/location facts.
    for ep in ("ep1", "ep2", "ep3"):
        for sc in range(1, 5):
            for sh in range(1, 4):
                _fact(registry, store, iid, ContinuityCategory.APPEARANCE,
                      "red coat", ep, f"sc{sc}", f"sh{sh}", "rev-1")
                _fact(registry, store, iid, ContinuityCategory.LOCATION,
                      "harbor city", ep, f"sc{sc}", f"sh{sh}", "rev-1")
    assert len(registry.ledger.facts_for_identity(iid)) == 72

    # Injury evolves: new fact supersedes the old; history is preserved.
    old = _fact(registry, store, iid, ContinuityCategory.CHARACTER_STATE,
                "healthy", "ep1", "sc1", "sh1", "rev-1")
    new = _fact(registry, store, iid, ContinuityCategory.CHARACTER_STATE,
                "injured left arm", "ep2", "sc1", "sh1", "rev-2", supersedes=old.fact_id)
    active_states = [
        f.statement for f in registry.ledger.active_facts(iid)
        if f.category is ContinuityCategory.CHARACTER_STATE
    ]
    assert active_states == ["injured left arm"]
    # Historical query still sees the superseded revision.
    ep1_states = [
        f.statement for f in registry.ledger.facts_for_scope(iid, episode="ep1")
        if f.category is ContinuityCategory.CHARACTER_STATE
    ]
    assert ep1_states == ["healthy"]
    # Revision pins travel with facts.
    assert new.revision == "rev-2" and new.provenance == "approved-shot-result"

    # Current facts never overwrite past revisions in the durable store.
    fresh = PersistentIdentityRegistry()
    fresh.restore({"identities": [], "bindings": []})
    for row in store.load_facts("user-1", iid):
        fresh.ledger.record(ContinuityFactRecord.model_validate(row))
    assert len(fresh.ledger.facts_for_identity(iid)) == 74
    assert len(fresh.ledger.active_facts(iid)) == 73


def test_contradiction_accumulation_no_random_blocks(tmp_path) -> None:
    store, registry, identity = _setup(tmp_path)
    iid = identity.identity_id
    binding = registry.bind(project_id="proj-a", identity_id=iid, owner_id="user-1")
    # Accumulate many (consistent) facts across rounds.
    for round_ in range(5):
        _fact(registry, store, iid, ContinuityCategory.PROP,
              f"compass-{round_}", "ep1", "sc1", f"sh{round_}", f"rev-{round_}")
    plan = dict(planned_appearance_id="default", planned_voice_id="v-anna",
                planned_location="harbor city")
    first = validate_pre_production(
        registry=registry, binding=binding, owner_id="user-1", **plan)
    # More facts, same plan: verdict stays explainable, never a random BLOCK.
    for round_ in range(5, 10):
        _fact(registry, store, iid, ContinuityCategory.PROP,
              f"compass-{round_}", "ep1", "sc1", f"sh{round_}", f"rev-{round_}")
    second = validate_pre_production(
        registry=registry, binding=binding, owner_id="user-1", **plan)
    assert first.verdict == second.verdict
    assert [f.code for f in first.findings] == [f.code for f in second.findings]


def test_validation_deterministic(tmp_path) -> None:
    store, registry, identity = _setup(tmp_path)
    binding = registry.bind(project_id="proj-a", identity_id=identity.identity_id, owner_id="user-1")
    kwargs = dict(planned_appearance_id="default", planned_voice_id="v-anna",
                  planned_location="harbor city", planned_props=("compass",),
                  planned_statements=("Anna patrols the harbor",))
    left = validate_pre_production(
        registry=registry, binding=binding, owner_id="user-1", **kwargs)
    right = validate_pre_production(
        registry=registry, binding=binding, owner_id="user-1", **kwargs)
    assert left == right

    gate_kwargs = dict(store=store, registry=registry, binding=binding,
                       owner_id="user-1", stage=ProductionStage.VIDEO_GENERATION,
                       overridden_by="user-1")
    decision_a = gate_production_stage(**gate_kwargs)
    decision_b = gate_production_stage(**{**gate_kwargs, "overridden_by": "user-1"})
    assert decision_a.verdict == decision_b.verdict
    assert decision_a.warn_codes == decision_b.warn_codes


def test_inferred_facts_never_hard_block(tmp_path) -> None:
    store, registry, identity = _setup(tmp_path)
    iid = identity.identity_id
    # A pile of inferred facts contradicting the plan: advisory only.
    for _ in range(5):
        record_production_fact(
            store=store, registry=registry, owner_id="user-1", identity_id=iid,
            category=ContinuityCategory.LOCATION, statement="desert outpost",
            source="llm-guess", episode="ep9",
        )
    binding = registry.bind(project_id="proj-a", identity_id=iid, owner_id="user-1")
    verdict = validate_pre_production(
        registry=registry, binding=binding, owner_id="user-1",
        planned_location="desert outpost",
    )
    assert verdict.verdict != ContinuitySeverity.BLOCK

    # Approved hard canon still BLOCKs.
    blocked = validate_pre_production(
        registry=registry, binding=binding, owner_id="user-1",
        planned_statements=["Twist: not anna never leaves harbor city"],
    )
    assert blocked.verdict == ContinuitySeverity.BLOCK
    try:
        gate_production_stage(
            store=store, registry=registry, binding=binding, owner_id="user-1",
            stage=ProductionStage.VIDEO_GENERATION,
            planned_statements=["Twist: not anna never leaves harbor city"],
            overridden_by="user-1",
        )
        raise AssertionError("gate should have refused")
    except GateRefusal:
        pass
