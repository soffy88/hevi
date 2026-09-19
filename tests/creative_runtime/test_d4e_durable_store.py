"""D4-E: durable-store crash safety, schema versioning, backup/restore."""

from __future__ import annotations

import sqlite3

import pytest

from hevi.creative.layer4.character_authority import VoiceIdentity
from hevi.creative.layer4.identity_store import IdentityStore
from hevi.creative.layer4.incident_store import IncidentService, IncidentStore
from hevi.creative.layer4.persistent_identity import PersistentIdentityRegistry


def _identity_row(owner="owner-a"):
    registry = PersistentIdentityRegistry()
    identity = registry.create_identity(
        owner_id=owner, canonical_name="Anna", voice=VoiceIdentity(voice_id="v-anna")
    )
    return identity.model_dump(mode="json")


def test_crash_during_write_leaves_no_partial_state(tmp_path) -> None:
    db = tmp_path / "identities.db"
    store = IdentityStore(db_path=db)
    store.save_identity("owner-a", _identity_row())
    # Simulate a crash mid-transaction: uncommitted insert must vanish.
    conn = sqlite3.connect(str(db), timeout=30.0)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO identities (identity_id, owner_id, updated_at, identity_json)"
            " VALUES ('partial-x', 'owner-a', '', '{}')"
        )
    finally:
        conn.rollback()
        conn.close()
    assert store.load_identities("owner-a") != []
    assert all(row["identity_id"] != "partial-x" for row in store.load_identities("owner-a"))
    # A failed validation never reaches the store: no half-written incident.
    from hevi.creative.layer4.repair_incident import IncidentError

    service = IncidentService(store=IncidentStore(db_path=tmp_path / "incidents.db"))
    with pytest.raises(IncidentError):
        service.open_or_get(production_run_id="", node_key="", failure="")
    assert service.list_incidents() == []


def test_schema_versioning_fail_safe(tmp_path) -> None:
    from hevi.creative.layer4 import identity_store as identity_mod
    from hevi.creative.layer4 import incident_store as incident_mod

    assert identity_mod._SCHEMA_VERSION == 1
    assert incident_mod._SCHEMA_VERSION == 1
    identity_db = tmp_path / "identities.db"
    incident_db = tmp_path / "incidents.db"
    IdentityStore(db_path=identity_db)
    IncidentStore(db_path=incident_db)
    with sqlite3.connect(str(identity_db)) as conn:
        assert conn.execute(
            "SELECT version FROM schema_version WHERE store='identities'").fetchone()[0] == 1
    with sqlite3.connect(str(incident_db)) as conn:
        assert conn.execute(
            "SELECT version FROM schema_version WHERE store='incidents'").fetchone()[0] == 1
    # A future (newer) schema refuses to open instead of rebuilding.
    with sqlite3.connect(str(identity_db)) as conn:
        conn.execute("UPDATE schema_version SET version=99 WHERE store='identities'")
        conn.commit()
    with pytest.raises(ValueError, match="IDENTITY_STORE_SCHEMA_TOO_NEW"):
        IdentityStore(db_path=identity_db)
    with sqlite3.connect(str(incident_db)) as conn:
        conn.execute("UPDATE schema_version SET version=99 WHERE store='incidents'")
        conn.commit()
    with pytest.raises(ValueError, match="INCIDENT_STORE_SCHEMA_TOO_NEW"):
        IncidentStore(db_path=incident_db)


def test_backup_restore_consistent(tmp_path) -> None:
    identity_db = tmp_path / "identities.db"
    incident_db = tmp_path / "incidents.db"
    identity_store = IdentityStore(db_path=identity_db)
    identity_store.save_identity("owner-a", _identity_row())
    from hevi.creative.layer4.persistent_identity import ContinuityFactRecord

    identity_id = identity_store.load_identities("owner-a")[0]["identity_id"]
    identity_store.save_fact("owner-a", ContinuityFactRecord(
        fact_id="fact-1", identity_id=identity_id,
        category="location", statement="harbor city", provenance="canon",
    ).model_dump(mode="json"))
    service = IncidentService(store=IncidentStore(db_path=incident_db))
    incident = service.open_or_get(
        production_run_id="run-bak", node_key="task.run", failure="PROVIDER_FAILURE",
        evidence={"signature": "provider temporarily unavailable", "transient": True},
    )
    service.authorize(incident.incident_id, incident.candidate_actions[0], confirmed=True)
    service.record_execution(incident.incident_id)

    # Backup both stores with the SQLite online-backup API, then restore.
    backup_identity = tmp_path / "backup-identities.db"
    backup_incident = tmp_path / "backup-incidents.db"
    for source, target in ((identity_db, backup_identity), (incident_db, backup_incident)):
        with sqlite3.connect(str(source)) as src, sqlite3.connect(str(target)) as dst:
            src.backup(dst)

    restored_service = IncidentService(store=IncidentStore(db_path=backup_incident))
    recovered = restored_service.get(incident.incident_id)
    assert recovered.attempts == 1
    assert recovered.status.value == "repair_executing"
    restored_identities = IdentityStore(db_path=backup_identity).load_identities("owner-a")
    assert [row["identity_id"] for row in restored_identities] == [identity_id]
    assert IdentityStore(db_path=backup_identity).load_facts("owner-a", identity_id)[0]["statement"] == "harbor city"
    # Restart on the restored copy resumes without duplicate side effects.
    from hevi.creative.layer4.repair_incident import IncidentError

    with pytest.raises(IncidentError, match="REPAIR_DUPLICATE_EXECUTION_REFUSED"):
        restored_service.record_execution(incident.incident_id)
