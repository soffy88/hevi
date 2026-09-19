"""D5-F release E2Es: cross-tenant, backup boundary, split-brain."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hevi.api.main import app
from hevi.auth.dependencies import get_current_user
from hevi.creative.layer4.character_authority import VoiceIdentity
from hevi.creative.layer4.continuity_gate import FactSource, record_production_fact
from hevi.creative.layer4.identity_store import IdentityStore, load_owner_registry
from hevi.creative.layer4.incident_store import IncidentService, IncidentStore
from hevi.creative.layer4.persistent_identity import (
    ContinuityCategory,
    IdentityError,
    PersistentIdentityRegistry,
)
from hevi.creative.layer4.store_backup import backup_stores, restore_stores
from hevi.creative.layer4.store_topology import SplitBrainAuthorityError

OWNER_A = {"id": "d5-owner-a"}
OWNER_B = {"id": "d5-owner-b"}


def test_e2e_d5_1_owner_b_cannot_reach_owner_a(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HEVI_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("HEVI_IDENTITY_DB", str(tmp_path / "identities.db"))
    monkeypatch.setenv("HEVI_INCIDENT_DB", str(tmp_path / "incidents.db"))
    app.dependency_overrides[get_current_user] = lambda: OWNER_A
    client = TestClient(app)
    try:
        # Owner A: identity + memory + continuity.
        identity = client.post(
            "/api/identities",
            json={"canonical_name": "Aria", "voice_id": "v-aria"},
        ).json()
        assert client.put(
            "/api/authorities/memory",
            json={"scope": "user", "key": "style", "content": "cinematic"},
        ).status_code == 200
        binding = client.post(
            "/api/identities/projects/proj-a/bindings",
            json={"identity_id": identity["identity_id"]},
        ).json()
        assert client.post(
            "/api/continuity/facts",
            json={"identity_id": identity["identity_id"], "category": "location",
                  "statement": "harbor city", "source": "canon"},
        ).status_code == 201

        # Owner B: every attempted reach is refused / empty.
        app.dependency_overrides[get_current_user] = lambda: OWNER_B
        assert client.get("/api/identities").json() == []
        assert client.get(f"/api/identities/{identity['identity_id']}").status_code == 404
        assert client.get("/api/authorities/memory").json()["entries"] == []
        assert client.get(
            f"/api/continuity/identities/{identity['identity_id']}/facts"
        ).status_code == 404
        assert client.post(
            "/api/continuity/facts",
            json={"identity_id": identity["identity_id"], "category": "location",
                  "statement": "desert", "source": "canon"},
        ).status_code == 404
        assert client.get(
            "/api/continuity/decisions", params={"binding_id": binding["binding_id"]}
        ).json()["decisions"] == []
    finally:
        app.dependency_overrides.clear()


def test_e2e_d5_2_backup_boundary_mutual_consistency(tmp_path) -> None:
    identity_db = tmp_path / "identities.db"
    incident_db = tmp_path / "incidents.db"
    store = IdentityStore(db_path=identity_db, authority_host_id="host-a")
    registry = PersistentIdentityRegistry()
    identity = registry.create_identity(
        owner_id="creator", canonical_name="Mara", voice=VoiceIdentity(voice_id="v-mara")
    )
    store.save_identity("creator", identity.model_dump(mode="json"))
    registry.add_appearance(
        identity.identity_id, owner_id="creator", appearance_id="coat",
        kind="outfit", reference_asset_ids=("coat-v1",),
    )
    store.save_identity("creator", registry.get_identity(identity.identity_id, owner_id="creator").model_dump(mode="json"))
    binding = registry.bind(project_id="proj-a", identity_id=identity.identity_id, owner_id="creator")
    store.save_binding("creator", binding.model_dump(mode="json"))
    record_production_fact(
        store=store, registry=registry, owner_id="creator", identity_id=identity.identity_id,
        category=ContinuityCategory.LOCATION, statement="harbor city", source=FactSource.CANON,
        revision="rev-1",
    )
    service = IncidentService(
        store=IncidentStore(db_path=incident_db, authority_host_id="host-a")
    )
    incident = service.open_or_get(
        production_run_id="run-1", node_key="task.run", failure="PROVIDER_FAILURE",
        evidence={"signature": "provider temporarily unavailable", "transient": True},
        owner_id="creator",
    )

    # Snapshot boundary.
    backup_dir = tmp_path / "backup"
    backup_stores({"identities": identity_db, "incidents": incident_db}, backup_dir)

    # More revisions after the snapshot.
    registry.update_appearance_assets(
        identity.identity_id, "coat", owner_id="creator", reference_asset_ids=("coat-v2",)
    )
    store.save_identity("creator", registry.get_identity(identity.identity_id, owner_id="creator").model_dump(mode="json"))
    record_production_fact(
        store=store, registry=registry, owner_id="creator", identity_id=identity.identity_id,
        category=ContinuityCategory.LOCATION, statement="desert outpost", source=FactSource.CANON,
        revision="rev-2",
    )

    # Restore the boundary and prove mutual consistency.
    restore_stores(backup_dir / "manifest.json", tmp_path / "restored")
    restored = IdentityStore(
        db_path=tmp_path / "restored" / "identities.db", authority_host_id="host-a"
    )
    assert restored.integrity_report("creator") == {}
    # Restored registry pins v1 coat (pre-snapshot), not v2, and only rev-1 facts.
    fresh = load_owner_registry(restored, "creator")
    pinned = fresh.bindings_for_project("proj-a", owner_id="creator")[0]
    assert fresh.resolve_pinned_appearance(pinned, "coat").reference_asset_ids == ("coat-v1",)
    facts = {f.revision for f in fresh.ledger.facts_for_identity(identity.identity_id)}
    assert facts == {"rev-1"}
    restored_incidents = IncidentStore(
        db_path=tmp_path / "restored" / "incidents.db", authority_host_id="host-a"
    )
    assert restored_incidents.load_incident(incident.incident_id) is not None
    assert restored_incidents.integrity_report() == {}


def test_e2e_d5_3_split_brain_fails_closed(tmp_path) -> None:
    identity_db = tmp_path / "identities.db"
    incident_db = tmp_path / "incidents.db"
    IdentityStore(db_path=identity_db, authority_host_id="host-a")
    IncidentStore(db_path=incident_db, authority_host_id="host-a")
    # A second authority host pointed at the same stores must refuse startup.
    with pytest.raises(SplitBrainAuthorityError):
        IdentityStore(db_path=identity_db, authority_host_id="host-b")
    with pytest.raises(SplitBrainAuthorityError):
        IncidentStore(db_path=incident_db, authority_host_id="host-b")


def test_e2e_d5_cross_owner_registry_refusal(tmp_path) -> None:
    store = IdentityStore(db_path=tmp_path / "identities.db", authority_host_id="host-a")
    registry = PersistentIdentityRegistry()
    identity = registry.create_identity(
        owner_id="owner-a", canonical_name="Aria", voice=VoiceIdentity(voice_id="v")
    )
    store.save_identity("owner-a", identity.model_dump(mode="json"))
    with pytest.raises(IdentityError):
        registry.get_identity(identity.identity_id, owner_id="owner-b")
