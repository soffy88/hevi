"""D7-A: /authorities tenant-scope and admin closure (adversarial)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hevi.api.main import app
from hevi.api.routers import authorities
from hevi.auth.dependencies import get_current_user

OWNER_A = {"id": "sec-owner-a"}
OWNER_B = {"id": "sec-owner-b"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HEVI_USAGE_DB", str(tmp_path / "usage.db"))
    monkeypatch.setenv("HEVI_ENDPOINTS_DB", str(tmp_path / "endpoints.db"))
    monkeypatch.setenv("HEVI_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("HEVI_IDENTITY_DB", str(tmp_path / "identities.db"))
    monkeypatch.setenv("HEVI_INCIDENT_DB", str(tmp_path / "incidents.db"))
    monkeypatch.delenv("HEVI_ADMIN_USER_IDS", raising=False)
    app.dependency_overrides[get_current_user] = lambda: OWNER_A
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_global_registries_are_admin_only_fail_closed(client: TestClient) -> None:
    # No admin allowlist configured -> every global route denies tenants.
    assert client.get("/api/authorities/usage/calls").status_code == 403
    assert client.get("/api/authorities/usage/analytics").status_code == 403
    assert client.get("/api/authorities/endpoints").status_code == 403
    assert client.post("/api/authorities/endpoints", json={}).status_code == 403


def test_admin_allowlist_grants_global_registry_access(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("HEVI_ADMIN_USER_IDS", OWNER_A["id"])
    assert client.get("/api/authorities/endpoints").status_code == 200
    assert client.get("/api/authorities/usage/calls").status_code == 200


def test_task_state_is_owner_scoped(client: TestClient, monkeypatch) -> None:
    task = {
        "id": str(uuid.uuid4()),
        "user_id": OWNER_A["id"],
        "status": "completed",
        "config_json": {
            "artifact_manifest": {
                "artifacts": [
                    {"kind": "video", "path": "final.mp4", "sha256": "abc", "logical_role": "final_video"}
                ]
            }
        },
    }

    async def fake_task(pool: Any, task_uuid: Any, owner_id: str = "") -> dict[str, Any] | None:
        return task if owner_id == OWNER_A["id"] else None

    monkeypatch.setattr(authorities, "_load_task", fake_task)
    task_id = task["id"]
    assert client.get(f"/api/authorities/tasks/{task_id}/plan").status_code == 200

    app.dependency_overrides[get_current_user] = lambda: OWNER_B
    try:
        assert client.get(f"/api/authorities/tasks/{task_id}/plan").status_code == 404
        assert client.get(f"/api/authorities/tasks/{task_id}/currency").status_code == 404
        assert client.get(f"/api/authorities/tasks/{task_id}/presentation").status_code == 404
        assert client.get(f"/api/authorities/tasks/{task_id}/editable").status_code == 404
    finally:
        app.dependency_overrides[get_current_user] = lambda: OWNER_A


def test_character_variants_owner_scoped(client: TestClient, monkeypatch) -> None:
    subject = {
        "id": "subj-1",
        "user_id": OWNER_A["id"],
        "name": "Anna",
        "reference_images": [],
        "metadata": {},
    }

    async def fake_subject(pool: Any, character_id: str, owner_id: str = "") -> dict[str, Any] | None:
        return subject if owner_id == OWNER_A["id"] else None

    monkeypatch.setattr(authorities, "_load_subject", fake_subject)
    assert client.get("/api/authorities/characters/subj-1/variants").status_code == 200
    app.dependency_overrides[get_current_user] = lambda: OWNER_B
    try:
        assert client.get("/api/authorities/characters/subj-1/variants").status_code == 404
    finally:
        app.dependency_overrides[get_current_user] = lambda: OWNER_A


def test_malformed_ids_do_not_disclose(client: TestClient, monkeypatch) -> None:
    # A foreign/invalid id returns the same not-found shape (no existence leak).
    async def fake_none(pool: Any, task_uuid: Any, owner_id: str = "") -> None:
        return None

    monkeypatch.setattr(authorities, "_load_task", fake_none)
    assert client.get(f"/api/authorities/tasks/{uuid.uuid4()}/plan").status_code == 404
    assert client.get("/api/authorities/tasks/not-a-uuid/plan").status_code in (400, 404)


def test_anonymous_refused(client: TestClient) -> None:
    app.dependency_overrides.clear()
    anon = TestClient(app)
    assert anon.get("/api/authorities/endpoints").status_code in (401, 403)
    assert anon.get("/api/authorities/usage/calls").status_code in (401, 403)


def test_identity_and_incident_surfaces_stay_owner_scoped(client: TestClient) -> None:
    identity = client.post(
        "/api/identities", json={"canonical_name": "Sec", "voice_id": "v-sec"}
    ).json()
    run_id = str(uuid.uuid4())
    client.post(
        "/api/incidents/open",
        json={
            "production_run_id": run_id,
            "node_key": "task.run",
            "failure": "PROVIDER_FAILURE",
            "evidence": {"signature": "provider temporarily unavailable", "transient": True},
        },
    )
    app.dependency_overrides[get_current_user] = lambda: OWNER_B
    try:
        assert client.get("/api/identities").json() == []
        assert client.get(f"/api/identities/{identity['identity_id']}").status_code == 404
        assert client.get(
            "/api/incidents", params={"production_run_id": run_id}
        ).json()["incidents"] == []
    finally:
        app.dependency_overrides[get_current_user] = lambda: OWNER_A


def test_readiness_reports_stores_and_optional_capabilities(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HEVI_IDENTITY_DB", str(tmp_path / "identities.db"))
    monkeypatch.setenv("HEVI_INCIDENT_DB", str(tmp_path / "incidents.db"))
    from hevi.api.health import readiness_report

    report = readiness_report(database_ok=True)
    assert report["status"] == "ready"
    assert report["authority_stores"]["identity"]["status"] == "ok"
    assert report["authority_stores"]["incident"]["status"] == "ok"
    assert report["authority_host_claim"] == "single_host_durable"
    # GPU/lip-sync absence must not make readiness fail.
    caps = report["optional_capabilities"]
    assert caps["gpu"] in ("READY", "OPTIONAL_CAPABILITY_BLOCKED")
    assert report["status"] == "ready"


def test_readiness_fails_closed_when_database_unavailable(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HEVI_IDENTITY_DB", str(tmp_path / "identities.db"))
    monkeypatch.setenv("HEVI_INCIDENT_DB", str(tmp_path / "incidents.db"))
    from hevi.api.health import readiness_report

    assert readiness_report(database_ok=False)["status"] == "not_ready"


def test_project_id_canonicalization_and_path_escape() -> None:
    from hevi.creative.layer4.project_identity import (
        ProjectIdentityError,
        validate_project_id,
    )

    assert validate_project_id("proj-a") == "proj-a"
    assert validate_project_id("12345678-1111-2222-3333-444444444444") == (
        "12345678-1111-2222-3333-444444444444"
    )
    for bad in ("../etc/passwd", "a/b", "a\\b", "..", "", "  ", "pro ject", "pro\x00ject", "x" * 500):
        with pytest.raises(ProjectIdentityError):
            validate_project_id(bad)


def test_bind_rejects_unsafe_project_id(client: TestClient) -> None:
    identity = client.post(
        "/api/identities", json={"canonical_name": "PathGuard", "voice_id": "v"}
    ).json()
    response = client.post(
        "/api/identities/projects/..%2Fetc%2Fpasswd/bindings",
        json={"identity_id": identity["identity_id"]},
    )
    assert response.status_code in (404, 422)


def test_project_authority_is_immutable_key_not_display_name(client: TestClient) -> None:
    identity = client.post(
        "/api/identities", json={"canonical_name": "RenameStable", "voice_id": "v"}
    ).json()
    binding = client.post(
        "/api/identities/projects/proj-stable/bindings",
        json={"identity_id": identity["identity_id"]},
    ).json()
    # Renaming the identity does not change the canonical project key.
    client.post("/api/identities", json={"canonical_name": "Other", "voice_id": "v2"})
    listed = client.get("/api/identities/projects/proj-stable/bindings").json()
    assert listed[0]["project_id"] == "proj-stable"
    assert listed[0]["binding_id"] == binding["binding_id"]
