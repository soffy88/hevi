"""D7-E/F/G/H/L: fresh deployment, backup/restore, host migration, crash recovery."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from hevi.api.main import app
from hevi.auth.dependencies import get_current_user
from hevi.creative.layer4.character_authority import VoiceIdentity
from hevi.creative.layer4.identity_store import IdentityStore, load_owner_registry
from hevi.creative.layer4.incident_store import IncidentService, IncidentStore
from hevi.creative.layer4.persistent_identity import PersistentIdentityRegistry
from hevi.creative.layer4.store_backup import backup_stores, restore_stores, verify_backup
from hevi.creative.layer4.store_topology import (
    SplitBrainAuthorityError,
    claim_authority,
)

OWNER = {"id": "ops-owner"}


def test_e2e_fresh_deployment_full_product_flow(tmp_path, monkeypatch) -> None:
    """Empty data dir -> first user -> project -> character -> continuity ->
    production issue -> metrics (no prior data reused)."""
    monkeypatch.setenv("HEVI_IDENTITY_DB", str(tmp_path / "identities.db"))
    monkeypatch.setenv("HEVI_INCIDENT_DB", str(tmp_path / "incidents.db"))
    monkeypatch.setenv("HEVI_MEMORY_DB", str(tmp_path / "memory.db"))
    assert not (tmp_path / "identities.db").exists()
    app.dependency_overrides[get_current_user] = lambda: OWNER
    client = TestClient(app)
    try:
        # Quick Start equivalent: create first character.
        identity = client.post(
            "/api/identities", json={"canonical_name": "First", "voice_id": "v-first"}
        )
        assert identity.status_code == 201
        identity_id = identity.json()["identity_id"]

        # First project binding.
        binding = client.post(
            "/api/identities/projects/first-project/bindings",
            json={"identity_id": identity_id},
        ).json()

        # Continuity fact + summary.
        assert client.post(
            "/api/continuity/facts",
            json={"identity_id": identity_id, "category": "location",
                  "statement": "harbor city", "source": "canon"},
        ).status_code == 201
        summary = client.get("/api/continuity/projects/first-project/summary").json()
        assert summary["binding_count"] == 1

        # First production issue.
        issue = client.post(
            "/api/incidents/open",
            json={"production_run_id": "first-run", "node_key": "task.run",
                  "failure": "PROVIDER_FAILURE",
                  "evidence": {"signature": "provider temporarily unavailable", "transient": True}},
        ).json()
        assert issue["status"] == "open"

        # Health + metrics read the fresh stores.
        health = client.get("/api/products/projects/first-run/health").json()
        assert health["status"] in ("READY", "NEEDS_ATTENTION")
        metrics = client.get("/api/products/metrics").json()["metrics"]
        assert metrics["IDENTITY_REUSE_RATE"] == 1.0
        assert binding["project_id"] == "first-project"
    finally:
        app.dependency_overrides.clear()


def test_backup_restore_round_trip_references_valid(tmp_path) -> None:
    identity_db = tmp_path / "identities.db"
    incident_db = tmp_path / "incidents.db"
    store = IdentityStore(db_path=identity_db)
    registry = PersistentIdentityRegistry()
    identity = registry.create_identity(
        owner_id="creator", canonical_name="Mara", voice=VoiceIdentity(voice_id="v-mara")
    )
    store.save_identity("creator", identity.model_dump(mode="json"))
    binding = registry.bind(project_id="proj-x", identity_id=identity.identity_id, owner_id="creator")
    store.save_binding("creator", binding.model_dump(mode="json"))
    service = IncidentService(store=IncidentStore(db_path=incident_db))
    incident = service.open_or_get(
        production_run_id="run-1", node_key="task.run", failure="PROVIDER_FAILURE",
        evidence={"signature": "provider temporarily unavailable", "transient": True},
        owner_id="creator",
    )

    backup_dir = tmp_path / "backup"
    backup_stores({"identities": identity_db, "incidents": incident_db}, backup_dir)
    assert all(verify_backup(backup_dir / "manifest.json").values())

    target = tmp_path / "restore"
    restore_stores(backup_dir / "manifest.json", target)
    restored = IdentityStore(db_path=target / "identities.db")
    fresh = load_owner_registry(restored, "creator")
    reloaded_binding = fresh.bindings_for_project("proj-x", owner_id="creator")[0]
    assert reloaded_binding.binding_id == binding.binding_id
    assert restored.integrity_report("creator") == {}
    restored_incidents = IncidentStore(db_path=target / "incidents.db")
    assert restored_incidents.load_incident(incident.incident_id) is not None


def test_host_migration_and_dual_authority_refusal(tmp_path) -> None:
    db = tmp_path / "identities.db"
    # Host A is authoritative.
    IdentityStore(db_path=db, authority_host_id="host-a")
    # Host B pointed at the same store must fail closed.
    with pytest.raises(SplitBrainAuthorityError):
        IdentityStore(db_path=db, authority_host_id="host-b")

    # Operator migrates: release A (simulate a stale heartbeat), then B takes over.
    with sqlite3.connect(str(db)) as conn:
        conn.row_factory = sqlite3.Row
        claim_authority(conn, store="identities", host_id="host-a", now=1000.0)
        conn.commit()
    IdentityStore(db_path=db, authority_host_id="host-b")  # stale -> takeover allowed
    with sqlite3.connect(str(db)) as conn:
        conn.row_factory = sqlite3.Row
        assert conn.execute(
            "SELECT host_id FROM authority_claim WHERE store='identities'"
        ).fetchone()["host_id"] == "host-b"
    # A is no longer authority: A returning now conflicts with B's fresh claim.
    with pytest.raises(SplitBrainAuthorityError):
        IdentityStore(db_path=db, authority_host_id="host-a")


def test_hard_crash_recovery_no_duplicate_execution(tmp_path) -> None:
    db = tmp_path / "incidents.db"
    service = IncidentService(store=IncidentStore(db_path=db))
    incident = service.open_or_get(
        production_run_id="crash-run", node_key="task.run", failure="PROVIDER_FAILURE",
        evidence={"signature": "provider temporarily unavailable", "transient": True},
        owner_id="creator",
    )
    service.authorize(incident.incident_id, incident.candidate_actions[0], confirmed=True, owner_id="creator")
    service.record_execution(incident.incident_id, owner_id="creator")

    # Simulated hard kill: fresh process re-reads durable state.
    recovered = IncidentService(store=IncidentStore(db_path=db))
    inc = recovered.get(incident.incident_id, owner_id="creator")
    assert inc.status.value == "repair_executing"
    assert inc.attempts == 1
    # A second execution without a new authorization is refused (no duplicate billing).
    from hevi.creative.layer4.repair_incident import IncidentError

    with pytest.raises(IncidentError, match="REPAIR_DUPLICATE_EXECUTION_REFUSED"):
        recovered.record_execution(incident.incident_id, owner_id="creator")
    assert recovered.store.load_events(incident.incident_id) != []
