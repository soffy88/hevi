"""D5-B/C: durability topology, split-brain refusal, integrity, backup."""

from __future__ import annotations

import sqlite3

import pytest

from hevi.creative.layer4.character_authority import VoiceIdentity
from hevi.creative.layer4.continuity_gate import FactSource, record_production_fact
from hevi.creative.layer4.identity_store import IdentityStore
from hevi.creative.layer4.incident_store import IncidentService, IncidentStore
from hevi.creative.layer4.persistent_identity import (
    ContinuityCategory,
    PersistentIdentityRegistry,
)
from hevi.creative.layer4.store_backup import (
    BackupError,
    backup_stores,
    boundary_token,
    restore_stores,
    verify_backup,
)
from hevi.creative.layer4.store_topology import (
    TOPOLOGY,
    SplitBrainAuthorityError,
    claim_authority,
    current_claim,
)


def _identity(registry, owner="creator", name="Mara"):
    return registry.create_identity(
        owner_id=owner, canonical_name=name, voice=VoiceIdentity(voice_id="v-mara")
    )


def test_topology_is_single_host_durable() -> None:
    assert TOPOLOGY == "single_host_durable"


def test_split_brain_refused_for_second_host(tmp_path) -> None:
    db = tmp_path / "identities.db"
    IdentityStore(db_path=db, authority_host_id="host-a")
    with pytest.raises(SplitBrainAuthorityError, match="AUTHORITY_HOST_CONFLICT"):
        IdentityStore(db_path=db, authority_host_id="host-b")


def test_same_host_reopen_allowed(tmp_path) -> None:
    db = tmp_path / "identities.db"
    IdentityStore(db_path=db, authority_host_id="host-a")
    # Same host reopens freely (restart, extra worker on the same host).
    IdentityStore(db_path=db, authority_host_id="host-a")


def test_stale_claim_taken_over(tmp_path) -> None:
    db = tmp_path / "incidents.db"
    with sqlite3.connect(str(db)) as conn:
        claim_authority(conn, store="incidents", host_id="dead-host", now=1000.0)
        conn.commit()
    # A fresh open from another host succeeds once the claim is stale.
    IncidentStore(db_path=db, authority_host_id="host-b")
    with sqlite3.connect(str(db)) as conn:
        assert current_claim(conn, "incidents")["host_id"] == "host-b"


def test_referential_integrity_clean_and_dangling(tmp_path) -> None:
    db = tmp_path / "identities.db"
    store = IdentityStore(db_path=db, authority_host_id="host-a")
    registry = PersistentIdentityRegistry()
    identity = _identity(registry)
    store.save_identity("creator", identity.model_dump(mode="json"))
    binding = registry.bind(project_id="proj-a", identity_id=identity.identity_id, owner_id="creator")
    store.save_binding("creator", binding.model_dump(mode="json"))
    record_production_fact(
        store=store, registry=registry, owner_id="creator", identity_id=identity.identity_id,
        category=ContinuityCategory.LOCATION, statement="harbor city", source=FactSource.CANON,
    )
    assert store.integrity_report("creator") == {}

    # Inject a dangling binding (identity_id has no identity row).
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "INSERT INTO bindings (binding_id, owner_id, project_id, identity_id,"
            " updated_at, binding_json) VALUES (?, ?, ?, ?, '', '{}')",
            ("dangling", "creator", "proj-x", "identity-missing"),
        )
        conn.commit()
    report = store.integrity_report("creator")
    assert report.get("binding_identity") == ["dangling"]


def test_incident_integrity_report_clean(tmp_path) -> None:
    store = IncidentStore(db_path=tmp_path / "incidents.db", authority_host_id="host-a")
    service = IncidentService(store=store)
    service.open_or_get(
        production_run_id="run-1", node_key="task.run", failure="PROVIDER_FAILURE",
        evidence={"signature": "provider temporarily unavailable", "transient": True},
        owner_id="creator",
    )
    assert store.integrity_report() == {}


def test_consistent_backup_boundary_and_restore(tmp_path) -> None:
    identity_db = tmp_path / "identities.db"
    incident_db = tmp_path / "incidents.db"
    store = IdentityStore(db_path=identity_db, authority_host_id="host-a")
    registry = PersistentIdentityRegistry()
    identity = _identity(registry)
    store.save_identity("creator", identity.model_dump(mode="json"))
    service = IncidentService(
        store=IncidentStore(db_path=incident_db, authority_host_id="host-a")
    )
    incident = service.open_or_get(
        production_run_id="run-1", node_key="task.run", failure="PROVIDER_FAILURE",
        evidence={"signature": "provider temporarily unavailable", "transient": True},
        owner_id="creator",
    )

    backup_dir = tmp_path / "backup"
    manifest = backup_stores(
        {"identities": identity_db, "incidents": incident_db}, backup_dir
    )
    assert manifest["topology"] == "single_host_durable"
    assert {m["name"] for m in manifest["members"]} == {"identities", "incidents"}
    assert all(verify_backup(backup_dir / "manifest.json").values())
    assert boundary_token(backup_dir / "manifest.json").startswith("boundary-")

    restored = restore_stores(backup_dir / "manifest.json", tmp_path / "restored")
    assert set(restored) == {"identities", "incidents"}
    restored_identity = IdentityStore(
        db_path=tmp_path / "restored" / "identities.db", authority_host_id="host-a"
    )
    assert restored_identity.integrity_report("creator") == {}
    restored_incident = IncidentStore(
        db_path=tmp_path / "restored" / "incidents.db", authority_host_id="host-a"
    )
    assert restored_incident.load_incident(incident.incident_id) is not None


def test_inconsistent_backup_refused(tmp_path) -> None:
    identity_db = tmp_path / "identities.db"
    IdentityStore(db_path=identity_db, authority_host_id="host-a")
    backup_dir = tmp_path / "backup"
    backup_stores({"identities": identity_db}, backup_dir)
    # Corrupt one member; the boundary is no longer valid.
    member = next((backup_dir).glob("identities.db"))
    member.write_bytes(b"not-a-sqlite-database")
    assert verify_backup(backup_dir / "manifest.json") == {"identities": False}
    with pytest.raises(BackupError, match="BACKUP_INCONSISTENT"):
        restore_stores(backup_dir / "manifest.json", tmp_path / "restored")


def test_unknown_schema_fail_closed(tmp_path) -> None:
    db = tmp_path / "identities.db"
    IdentityStore(db_path=db, authority_host_id="host-a")
    with sqlite3.connect(str(db)) as conn:
        conn.execute("UPDATE schema_version SET version=999 WHERE store='identities'")
        conn.commit()
    with pytest.raises(ValueError, match="IDENTITY_STORE_SCHEMA_TOO_NEW"):
        IdentityStore(db_path=db, authority_host_id="host-a")
