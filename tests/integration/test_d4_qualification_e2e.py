"""D4 qualification E2Es (E2E-D4-1..6): long-horizon moat scenarios.

These compose the real durable stores + authorities end-to-end; they are
not mocks of the D4 behavior they qualify.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from hevi.creative.layer4.character_authority import AppearanceKind, VoiceIdentity
from hevi.creative.layer4.continuity_gate import (
    FactSource,
    ProductionStage,
    gate_production_stage,
    record_production_fact,
)
from hevi.creative.layer4.identity_store import IdentityStore, load_owner_registry
from hevi.creative.layer4.incident_store import IncidentService, IncidentStore
from hevi.creative.layer4.persistent_identity import (
    ContinuityCategory,
    PersistentIdentityRegistry,
)
from hevi.creative.layer4.repair_incident import RepairLoopGuard


def _incident_service(db: Path, **kwargs) -> IncidentService:
    kwargs.setdefault("loop_guard", RepairLoopGuard(cooldown_seconds=0.0))
    return IncidentService(store=IncidentStore(db_path=db), **kwargs)


def test_e2e_d4_1_three_projects_version_pinning(tmp_path) -> None:
    store = IdentityStore(db_path=tmp_path / "identities.db")
    registry = load_owner_registry(store, "creator")
    identity = registry.create_identity(
        owner_id="creator", canonical_name="Mara", voice=VoiceIdentity(voice_id="v-mara")
    )
    store.save_identity("creator", identity.model_dump(mode="json"))
    registry.add_appearance(
        identity.identity_id, owner_id="creator", appearance_id="field",
        kind=AppearanceKind.OUTFIT, reference_asset_ids=("field-v1",),
    )
    store.save_identity("creator", registry.get_identity(identity.identity_id, owner_id="creator").model_dump(mode="json"))

    pinned = {}
    for project in ("show-a", "show-b", "show-c"):
        binding = registry.bind(project_id=project, identity_id=identity.identity_id, owner_id="creator")
        store.save_binding("creator", binding.model_dump(mode="json"))
        pinned[project] = binding

    # Global evolution to appearance v2 + voice v2.
    registry.update_appearance_assets(
        identity.identity_id, "field", owner_id="creator", reference_asset_ids=("field-v2",)
    )
    registry.assign_voice(identity.identity_id, VoiceIdentity(voice_id="v-mara-v2"), owner_id="creator")
    store.save_identity("creator", registry.get_identity(identity.identity_id, owner_id="creator").model_dump(mode="json"))

    # Projects A/B stay pinned; C upgrades explicitly.
    assert registry.resolve_pinned_appearance(pinned["show-a"], "field").reference_asset_ids == ("field-v1",)
    assert registry.resolve_pinned_voice(pinned["show-b"]).voice_id == "v-mara"
    upgraded = registry.upgrade_binding(pinned["show-c"].binding_id, owner_id="creator")
    store.save_binding("creator", upgraded.model_dump(mode="json"))
    assert registry.resolve_pinned_appearance(upgraded, "field").reference_asset_ids == ("field-v2",)
    assert registry.resolve_pinned_voice(upgraded).voice_id == "v-mara-v2"
    assert {pinned["show-a"].identity_id, pinned["show-b"].identity_id, upgraded.identity_id} == {
        identity.identity_id
    }


def test_e2e_d4_2_multi_episode_continuity(tmp_path) -> None:
    store = IdentityStore(db_path=tmp_path / "identities.db")
    registry = load_owner_registry(store, "creator")
    identity = registry.create_identity(
        owner_id="creator", canonical_name="Mara", voice=VoiceIdentity(voice_id="v-mara")
    )
    store.save_identity("creator", identity.model_dump(mode="json"))
    binding = registry.bind(project_id="series", identity_id=identity.identity_id, owner_id="creator")
    store.save_binding("creator", binding.model_dump(mode="json"))

    for episode in ("ep1", "ep2", "ep3"):
        for scene in ("sc1", "sc2"):
            record_production_fact(
                store=store, registry=registry, owner_id="creator",
                identity_id=identity.identity_id, category=ContinuityCategory.LOCATION,
                statement="harbor city", source=FactSource.APPROVED_SHOT_RESULT,
                episode=episode, scene=scene, revision=f"rev-{episode}",
            )
    decision = gate_production_stage(
        store=store, registry=registry, binding=binding, owner_id="creator",
        stage=ProductionStage.VIDEO_GENERATION, planned_location="harbor city",
        overridden_by="creator",
    )
    assert decision.verdict.value in ("pass", "warn")
    # Historical query by episode still resolves the original facts.
    ep1 = registry.ledger.facts_for_scope(identity.identity_id, episode="ep1")
    assert len(ep1) == 2
    assert all(f.revision == "rev-ep1" for f in ep1)


def test_e2e_d4_3_incident_storm(tmp_path) -> None:
    service = _incident_service(tmp_path / "incidents.db")
    ids = {
        service.open_or_get(
            production_run_id="storm-run", node_key="task.run",
            failure="PROVIDER_FAILURE",
            evidence={"signature": "provider temporarily unavailable", "transient": True},
            owner_id="creator",
        ).incident_id
        for _ in range(20)
    }
    assert len(ids) == 1
    assert len(service.list_incidents(production_run_id="storm-run", owner_id="creator")) == 1
    assert service.store.load_dedupe_hits() != {}


def test_e2e_d4_4_repair_three_restarts(tmp_path) -> None:
    db = tmp_path / "incidents.db"

    def fresh() -> IncidentService:
        return _incident_service(db)

    incident = fresh().open_or_get(
        production_run_id="restart-run", node_key="task.run", failure="PROVIDER_FAILURE",
        evidence={"signature": "provider temporarily unavailable", "transient": True},
        owner_id="creator",
    )
    iid = incident.incident_id
    action = incident.candidate_actions[0]

    # Restart 1: after open.
    assert fresh().get(iid, owner_id="creator").status.value == "open"
    # Restart 2: after authorize.
    assert fresh().authorize(iid, action, confirmed=True, owner_id="creator")[0] is True
    assert fresh().get(iid, owner_id="creator").status.value == "repair_executing"
    # Restart 3: after record_execution -> verify.
    fresh().record_execution(iid, owner_id="creator")
    assert fresh().get(iid, owner_id="creator").attempts == 1
    resolved = fresh().verify(
        iid,
        {"task_ok": True, "artifact_ok": True, "currency_ok": True, "presentation_ok": True},
        owner_id="creator",
    )
    assert resolved.status.value == "resolved"
    assert resolved.attempts == 1


def test_e2e_d4_5_three_owner_concurrency(tmp_path) -> None:
    identity_store = IdentityStore(db_path=tmp_path / "identities.db")
    incident_db = tmp_path / "incidents.db"
    errors: list[Exception] = []

    def owner_flow(owner: str) -> None:
        try:
            registry = load_owner_registry(identity_store, owner)
            identity = registry.create_identity(
                owner_id=owner, canonical_name=f"Mara-{owner}",
                voice=VoiceIdentity(voice_id=f"v-{owner}"),
            )
            identity_store.save_identity(owner, identity.model_dump(mode="json"))
            binding = registry.bind(
                project_id=f"proj-{owner}", identity_id=identity.identity_id, owner_id=owner
            )
            identity_store.save_binding(owner, binding.model_dump(mode="json"))
            service = _incident_service(incident_db)
            service.open_or_get(
                production_run_id=f"run-{owner}", node_key="task.run",
                failure="PROVIDER_FAILURE",
                evidence={"signature": "provider temporarily unavailable", "transient": True},
                owner_id=owner,
            )
            assert service.list_incidents(owner_id=owner)
            assert service.list_incidents(owner_id=f"not-{owner}") == []
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [
        threading.Thread(target=owner_flow, args=(owner,))
        for owner in ("owner-a", "owner-b", "owner-c")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    for owner in ("owner-a", "owner-b", "owner-c"):
        assert len(identity_store.load_identities(owner)) == 1


def test_e2e_d4_6_durable_store_backup_restore(tmp_path) -> None:
    identity_db = tmp_path / "identities.db"
    incident_db = tmp_path / "incidents.db"
    identity_store = IdentityStore(db_path=identity_db)
    registry = PersistentIdentityRegistry()
    identity = registry.create_identity(
        owner_id="creator", canonical_name="Mara", voice=VoiceIdentity(voice_id="v-mara")
    )
    identity_store.save_identity("creator", identity.model_dump(mode="json"))
    service = _incident_service(incident_db)
    incident = service.open_or_get(
        production_run_id="backup-run", node_key="task.run", failure="PROVIDER_FAILURE",
        evidence={"signature": "provider temporarily unavailable", "transient": True},
        owner_id="creator",
    )
    service.authorize(incident.incident_id, incident.candidate_actions[0], confirmed=True, owner_id="creator")
    service.record_execution(incident.incident_id, owner_id="creator")

    backup_identity = tmp_path / "bak-identities.db"
    backup_incident = tmp_path / "bak-incidents.db"
    for source, target in ((identity_db, backup_identity), (incident_db, backup_incident)):
        with sqlite3.connect(str(source)) as src, sqlite3.connect(str(target)) as dst:
            src.backup(dst)

    assert len(IdentityStore(db_path=backup_identity).load_identities("creator")) == 1
    restored = IncidentService(store=IncidentStore(db_path=backup_incident))
    recovered = restored.get(incident.incident_id, owner_id="creator")
    assert recovered.attempts == 1
