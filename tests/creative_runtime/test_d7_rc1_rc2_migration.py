"""D7-F: RC1 -> RC2 durable-store upgrade preserves data and is idempotent.

RC2 added `archived` on identities and `owner_id`/event tables on incidents.
Old (RC1-shaped) stores must open, upgrade forward, and never lose or drift
authoritative state. Re-opening must be a no-op (idempotent).
"""

from __future__ import annotations

import json
import sqlite3

from hevi.creative.layer4.identity_store import IdentityStore, load_owner_registry
from hevi.creative.layer4.incident_store import IncidentService, IncidentStore


def _rc1_identity_json(identity_id: str = "identity-rc1") -> dict:
    # RC1 GlobalCreativeIdentity had no `archived` / history fields.
    return {
        "identity_id": identity_id,
        "owner_id": "creator",
        "kind": "character",
        "canonical_name": "Legacy",
        "aliases": [],
        "appearance_library": [
            {
                "appearance_id": "default",
                "character_id": identity_id,
                "kind": "default",
                "label": "default",
                "version": 1,
                "visual_asset_ids": [],
                "reference_asset_ids": ["ref-1"],
                "voice_override": None,
                "revision": f"{identity_id}@default#1",
                "superseded_by_version": None,
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        ],
        "voice": {"voice_id": "v-legacy", "binding": "prompt", "description": "", "reference_audio_ref": None},
        "reference_asset_ids": ["ref-1"],
        "canon_constraints": [],
        "identity_version": 1,
        "revision": f"{identity_id}#1",
        "created_at": "2026-01-01T00:00:00+00:00",
    }


def test_rc1_identity_store_upgrades_without_drift(tmp_path) -> None:
    db = tmp_path / "identities.db"
    # Build an RC1-shaped identities table (no schema_version, no archived).
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "CREATE TABLE identities (identity_id TEXT PRIMARY KEY, owner_id TEXT,"
            " updated_at TEXT, identity_json TEXT)"
        )
        conn.execute(
            "CREATE TABLE bindings (binding_id TEXT PRIMARY KEY, owner_id TEXT,"
            " project_id TEXT, identity_id TEXT, updated_at TEXT, binding_json TEXT)"
        )
        conn.execute(
            "INSERT INTO identities VALUES (?, ?, ?, ?)",
            ("identity-rc1", "creator", "2026-01-01", json.dumps(_rc1_identity_json())),
        )
        binding = {
            "binding_id": "binding-rc1",
            "project_id": "proj-legacy",
            "identity_id": "identity-rc1",
            "owner_id": "creator",
            "pinned_identity_version": 1,
            "pinned_appearance_versions": {"default": 1},
            "overrides": {},
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        conn.execute(
            "INSERT INTO bindings VALUES (?, ?, ?, ?, ?, ?)",
            ("binding-rc1", "creator", "proj-legacy", "identity-rc1", "2026-01-01", json.dumps(binding)),
        )
        conn.commit()

    store = IdentityStore(db_path=db)  # RC2 opens + forward-migrates
    registry = load_owner_registry(store, "creator")
    identity = registry.get_identity("identity-rc1", owner_id="creator")
    assert identity.canonical_name == "Legacy"
    assert identity.identity_version == 1
    assert identity.archived is False  # defaulted forward
    assert registry.resolve_pinned_appearance(
        registry.bindings_for_project("proj-legacy", owner_id="creator")[0], "default"
    ).reference_asset_ids == ("ref-1",)

    # Idempotent: reopening does not duplicate or mutate.
    store2 = IdentityStore(db_path=db)
    assert len(store2.load_identities("creator")) == 1
    assert len(store2.load_bindings("creator")) == 1


def test_rc1_incident_store_adds_owner_and_events(tmp_path) -> None:
    db = tmp_path / "incidents.db"
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "CREATE TABLE incidents (incident_id TEXT PRIMARY KEY,"
            " production_run_id TEXT, node_key TEXT, status TEXT,"
            " updated_at TEXT, incident_json TEXT)"
        )
        incident = {
            "incident_id": "incident-rc1",
            "production_run_id": "run-1",
            "node_key": "task.run",
            "artifact_id": "",
            "root_cause": "provider_temp_unavailable",
            "failure_code": "PROVIDER_FAILURE",
            "evidence": {},
            "diagnosis": "legacy",
            "candidate_actions": [],
            "selected_action": None,
            "needs_agent": False,
            "status": "open",
            "attempts": 0,
            "verification_result": {},
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        conn.execute(
            "INSERT INTO incidents VALUES (?, ?, ?, ?, ?, ?)",
            (
                "incident-rc1", "run-1", "task.run", "open", "2026-01-01",
                json.dumps(incident),
            ),
        )
        conn.commit()

    store = IncidentStore(db_path=db)  # RC2 forward-migrates (owner_id + event tables)
    with sqlite3.connect(str(db)) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(incidents)")}
        assert "owner_id" in cols
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "incident_events" in tables and "schema_version" in tables
    assert store.load_incident("incident-rc1") is not None

    # Idempotent reopen; legacy ownerless incident is quarantined from owner lists.
    store2 = IncidentStore(db_path=db)
    assert store2.load_incident("incident-rc1") is not None
    service = IncidentService(store=store2)
    assert service.list_incidents(owner_id="creator") == []
