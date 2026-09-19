"""D4-D: multi-user concurrency — isolation + atomic transitions."""

from __future__ import annotations

import sqlite3
import threading

import pytest

from hevi.creative.layer4.character_authority import VoiceIdentity
from hevi.creative.layer4.continuity_gate import FactSource, record_production_fact
from hevi.creative.layer4.identity_store import IdentityStore, load_owner_registry
from hevi.creative.layer4.incident_store import IncidentService, IncidentStore
from hevi.creative.layer4.persistent_identity import (
    ContinuityCategory,
    IdentityError,
    PersistentIdentityRegistry,
)
from hevi.creative.layer4.repair_incident import IncidentError, IncidentStatus


def _identity(registry, owner, name="Anna"):
    return registry.create_identity(
        owner_id=owner, canonical_name=name, voice=VoiceIdentity(voice_id="v-anna")
    )


def test_three_owner_identity_isolation(tmp_path) -> None:
    store = IdentityStore(db_path=tmp_path / "identities.db")
    owners = ("owner-a", "owner-b", "owner-c")
    ids = {}
    for owner in owners:
        registry = load_owner_registry(store, owner)
        created = _identity(registry, owner, name=f"Anna-{owner}")
        store.save_identity(owner, created.model_dump(mode="json"))
        ids[owner] = created.identity_id
        binding = registry.bind(
            project_id=f"proj-{owner}", identity_id=created.identity_id, owner_id=owner
        )
        store.save_binding(owner, binding.model_dump(mode="json"))

    for owner in owners:
        registry = load_owner_registry(store, owner)
        assert [i.identity_id for i in registry.identities] == [ids[owner]]
        # Cross-owner inspect/bind/upgrade refused.
        other = owners[(owners.index(owner) + 1) % 3]
        with pytest.raises(IdentityError):
            registry.get_identity(ids[other], owner_id=owner)
        with pytest.raises(IdentityError):
            registry.bind(project_id="proj-x", identity_id=ids[other], owner_id=owner)
        other_binding = load_owner_registry(store, other).bindings_for_project(
            f"proj-{other}", owner_id=other
        )[0]
        with pytest.raises(IdentityError):
            registry.upgrade_binding(other_binding.binding_id, owner_id=owner)


def test_continuity_cross_owner_refused(tmp_path) -> None:
    store = IdentityStore(db_path=tmp_path / "identities.db")
    registry = load_owner_registry(store, "owner-a")
    identity = _identity(registry, "owner-a")
    store.save_identity("owner-a", identity.model_dump(mode="json"))
    record_production_fact(
        store=store, registry=registry, owner_id="owner-a",
        identity_id=identity.identity_id, category=ContinuityCategory.LOCATION,
        statement="harbor city", source=FactSource.CANON,
    )
    # Owner B sees nothing and cannot write to A's identity.
    assert store.load_facts("owner-b", identity.identity_id) == []
    other_registry = load_owner_registry(store, "owner-b")
    with pytest.raises(IdentityError):
        record_production_fact(
            store=store, registry=other_registry, owner_id="owner-b",
            identity_id=identity.identity_id, category=ContinuityCategory.LOCATION,
            statement="desert", source=FactSource.CANON,
        )
    assert len(store.load_facts("owner-a", identity.identity_id)) == 1


def test_repair_cross_owner_refused(tmp_path) -> None:
    service = IncidentService(store=IncidentStore(db_path=tmp_path / "incidents.db"))
    incident = service.open_or_get(
        production_run_id="run-a", node_key="task.run", failure="PROVIDER_FAILURE",
        evidence={"signature": "provider temporarily unavailable", "transient": True},
        owner_id="owner-a",
    )
    iid = incident.incident_id
    assert service.list_incidents(owner_id="owner-a") != []
    assert service.list_incidents(owner_id="owner-b") == []
    with pytest.raises(IncidentError, match="REPAIR_OWNER_MISMATCH"):
        service.get(iid, owner_id="owner-b")
    action = incident.candidate_actions[0]
    with pytest.raises(IncidentError, match="REPAIR_OWNER_MISMATCH"):
        service.authorize(iid, action, confirmed=True, owner_id="owner-b")
    with pytest.raises(IncidentError, match="REPAIR_OWNER_MISMATCH"):
        service.record_execution(iid, owner_id="owner-b")
    with pytest.raises(IncidentError, match="REPAIR_OWNER_MISMATCH"):
        service.verify(iid, {"task_ok": True, "artifact_ok": True,
                             "currency_ok": True, "presentation_ok": True},
                       owner_id="owner-b")
    with pytest.raises(IncidentError, match="REPAIR_OWNER_MISMATCH"):
        service.decline(iid, owner_id="owner-b")
    # Owner A unaffected: full lifecycle still works.
    assert service.authorize(iid, action, confirmed=True, owner_id="owner-a")[0] is True
    service.record_execution(iid, owner_id="owner-a")
    resolved = service.verify(
        iid, {"task_ok": True, "artifact_ok": True, "currency_ok": True,
              "presentation_ok": True}, owner_id="owner-a")
    assert resolved.status is IncidentStatus.RESOLVED


def test_concurrent_distinct_writes_all_land(tmp_path) -> None:
    store = IdentityStore(db_path=tmp_path / "identities.db")
    registry = PersistentIdentityRegistry()
    identity = _identity(registry, "owner-a")
    store.save_identity("owner-a", identity.model_dump(mode="json"))
    errors: list[Exception] = []

    def write_fact(idx: int) -> None:
        try:
            from hevi.creative.layer4.persistent_identity import ContinuityFactRecord

            store.save_fact("owner-a", ContinuityFactRecord(
                fact_id=f"fact-{idx}", identity_id=identity.identity_id,
                category=ContinuityCategory.PROP, statement=f"prop-{idx}",
                provenance="canon",
            ).model_dump(mode="json"))
        except Exception as exc:  # pragma: no cover - must not happen
            errors.append(exc)

    threads = [threading.Thread(target=write_fact, args=(i,)) for i in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert len(store.load_facts("owner-a", identity.identity_id)) == 10


def test_concurrent_authorize_stays_consistent(tmp_path) -> None:
    service = IncidentService(store=IncidentStore(db_path=tmp_path / "incidents.db"))
    incident = service.open_or_get(
        production_run_id="run-race", node_key="task.run", failure="PROVIDER_FAILURE",
        evidence={"signature": "provider temporarily unavailable", "transient": True},
    )
    action = incident.candidate_actions[0]
    outcomes: list[bool] = []

    def authorize_once() -> None:
        approved, _ = service.authorize(incident.incident_id, action, confirmed=True)
        outcomes.append(approved)

    threads = [threading.Thread(target=authorize_once) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    # No lost updates, no corruption, no exception: every authorization either
    # reserved a real attempt slot or was refused by the loop guard.
    final = IncidentStore(db_path=tmp_path / "incidents.db").load_incident(incident.incident_id)
    assert final is not None
    guard_total = [
        entry
        for entries in service.coordinator.loop_guard.export_history().values()
        for entry in entries
    ]
    assert len(guard_total) == sum(outcomes)
    assert service.get(incident.incident_id).attempts <= len(guard_total)


def test_sqlite_wal_and_timeout(tmp_path) -> None:
    db = tmp_path / "identities.db"
    store = IdentityStore(db_path=db)
    registry = PersistentIdentityRegistry()
    store.save_identity("o", _identity(registry, "o").model_dump(mode="json"))
    with sqlite3.connect(str(db), timeout=30.0) as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
