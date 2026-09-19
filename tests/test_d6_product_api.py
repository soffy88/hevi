"""D6 backend product projections: health, timeline, identity library signals."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from hevi.api.main import app
from hevi.api.routers.tasks import get_repository
from hevi.auth.dependencies import get_current_user

USER_A = {"id": "prod-owner-a"}
USER_B = {"id": "prod-owner-b"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HEVI_IDENTITY_DB", str(tmp_path / "identities.db"))
    monkeypatch.setenv("HEVI_INCIDENT_DB", str(tmp_path / "incidents.db"))
    app.dependency_overrides[get_current_user] = lambda: USER_A
    yield TestClient(app)
    app.dependency_overrides.clear()


class _Repo:
    def __init__(self, task):
        self._task = task

    async def get_task(self, _task_id):
        return self._task


def _manifest_task(status: str = "completed", user_id: str = USER_A["id"]):
    return {
        "id": str(uuid4()),
        "user_id": user_id,
        "status": status,
        "config_json": {
            "artifact_manifest": {
                "artifacts": [
                    {
                        "kind": "video",
                        "path": "final.mp4",
                        "sha256": "abc",
                        "logical_role": "final_video",
                    }
                ]
            }
        },
    }


def test_project_health_complete_and_next_action_export(client: TestClient) -> None:
    task = _manifest_task(status="completed")
    app.dependency_overrides[get_repository] = lambda: _Repo(task)
    try:
        body = client.get(f"/api/products/projects/{task['id']}/health").json()
    finally:
        app.dependency_overrides.pop(get_repository, None)
    assert body["status"] == "COMPLETE"
    assert body["next_action"]["kind"] == "export"


def test_project_health_needs_attention_on_open_incident(client: TestClient) -> None:
    task = _manifest_task(status="completed")
    run_id = task["id"]
    client.post(
        "/api/incidents/open",
        json={
            "production_run_id": run_id,
            "node_key": "task.run",
            "failure": "PROVIDER_FAILURE",
            "evidence": {"signature": "provider temporarily unavailable", "transient": True},
        },
    )
    app.dependency_overrides[get_repository] = lambda: _Repo(task)
    try:
        body = client.get(f"/api/products/projects/{run_id}/health").json()
    finally:
        app.dependency_overrides.pop(get_repository, None)
    assert body["status"] == "NEEDS_ATTENTION"
    assert body["next_action"]["kind"] == "repair"
    assert body["incidents"][0]["policy"] == "auto_safe"


def test_project_health_blocked_manual(client: TestClient) -> None:
    task = _manifest_task(status="running")
    run_id = task["id"]
    client.post(
        "/api/incidents/open",
        json={
            "production_run_id": run_id,
            "node_key": "scene.cast",
            "failure": "IDENTITY_MISMATCH",
            "evidence": {"missing_reference": "anna/stage"},
        },
    )
    # MANUAL_ONLY authorizes -> escalated_manual.
    incident = client.get(
        "/api/incidents", params={"production_run_id": run_id}
    ).json()["incidents"][0]
    client.post(f"/api/incidents/{incident['incident_id']}/confirm", json={"confirmed": True})
    app.dependency_overrides[get_repository] = lambda: _Repo(task)
    try:
        body = client.get(f"/api/products/projects/{run_id}/health").json()
    finally:
        app.dependency_overrides.pop(get_repository, None)
    assert body["status"] == "BLOCKED"
    assert body["next_action"]["kind"] == "manual_fix"


def test_incident_timeline_and_product_view(client: TestClient) -> None:
    run_id = str(uuid4())
    incident = client.post(
        "/api/incidents/open",
        json={
            "production_run_id": run_id,
            "node_key": "task.run",
            "failure": "PROVIDER_FAILURE",
            "evidence": {"signature": "provider temporarily unavailable", "transient": True},
        },
    ).json()
    incident_id = incident["incident_id"]
    client.post(f"/api/incidents/{incident_id}/confirm", json={"confirmed": True})
    client.post(f"/api/incidents/{incident_id}/executed")
    client.post(
        f"/api/incidents/{incident_id}/verify",
        json={
            "verification": {
                "task_ok": True,
                "artifact_ok": True,
                "currency_ok": True,
                "presentation_ok": True,
            },
            "preserved_artifact_ids": ["artifact-1"],
        },
    )
    timeline = client.get(f"/api/incidents/{incident_id}/timeline").json()["events"]
    events = [event["event"] for event in timeline]
    assert "detected" in events and "diagnosed" in events
    assert "authorized" in events and "executed" in events
    assert "verified_resolved" in events

    product = client.get(f"/api/incidents/{incident_id}", params={"product": True}).json()
    assert product["status"] == "resolved"
    assert product["policy"] == "auto_safe"
    assert product["estimated_cost_usd"] == 0.0
    assert product["preserved_artifact_ids"] == ["artifact-1"]


def test_identity_library_upgrade_signal_and_archive(client: TestClient) -> None:
    identity = client.post(
        "/api/identities", json={"canonical_name": "Nova", "voice_id": "v-nova"}
    ).json()
    identity_id = identity["identity_id"]
    binding = client.post(
        "/api/identities/projects/proj-x/bindings", json={"identity_id": identity_id}
    ).json()
    assert binding["pinned_identity_version"] == 1

    # Global update bumps version; the binding reports upgrade_available.
    client.post(
        f"/api/identities/{identity_id}/appearances",
        json={"appearance_id": "winter", "kind": "outfit"},
    )
    listed = client.get("/api/identities").json()
    entry = next(i for i in listed if i["identity_id"] == identity_id)
    assert entry["identity_version"] == 2
    assert entry["upgrade_available"] is True
    assert entry["projects_using"] == ["proj-x"]

    # Archive preserves history (no dangling reference).
    archived = client.post(f"/api/identities/{identity_id}/archive").json()
    assert archived["archived"] is True
    assert client.get("/api/identities").json() == []
    assert len(client.get("/api/identities", params={"include_archived": True}).json()) == 1
    integrity = client.get(f"/api/identities/{identity_id}/integrity").json()
    assert integrity["dangling"] == {}


def test_continuity_project_summary(client: TestClient) -> None:
    identity = client.post(
        "/api/identities",
        json={
            "canonical_name": "Orion",
            "voice_id": "v-orion",
            "canon_constraints": ["orion never removes the red coat"],
        },
    ).json()
    identity_id = identity["identity_id"]
    client.post(
        "/api/identities/projects/proj-cont/bindings", json={"identity_id": identity_id}
    )
    summary = client.get("/api/continuity/projects/proj-cont/summary").json()
    assert summary["verdict"] == "pass"
    assert summary["gate_ready"] is True
    assert summary["binding_count"] == 1


def test_product_tenant_isolation(client: TestClient) -> None:
    identity = client.post(
        "/api/identities", json={"canonical_name": "Iso", "voice_id": "v-iso"}
    ).json()
    run_id = str(uuid4())
    client.post(
        "/api/incidents/open",
        json={
            "production_run_id": run_id,
            "node_key": "task.run",
            "failure": "PROVIDER_FAILURE",
            "evidence": {"signature": "provider temporarily unavailable", "transient": True},
        },
    )
    app.dependency_overrides[get_current_user] = lambda: USER_B
    try:
        assert client.get("/api/identities").json() == []
        assert client.get(f"/api/identities/{identity['identity_id']}").status_code == 404
        assert client.get("/api/identities", params={"include_archived": True}).json() == []
        assert client.get(
            "/api/incidents", params={"production_run_id": run_id}
        ).json()["incidents"] == []
        assert client.get(
            "/api/products/projects/" + run_id + "/health"
        ).json()["incidents"] == []
    finally:
        app.dependency_overrides[get_current_user] = lambda: USER_A


def test_track_task_failure_propagates_owner(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HEVI_INCIDENT_DB", str(tmp_path / "incidents.db"))
    from hevi.creative.layer4.incident_store import IncidentService, track_task_failure

    incident_id = track_task_failure(
        production_run_id="run-owner",
        node_key="task.run",
        failure="PROVIDER_FAILURE",
        evidence={"signature": "provider temporarily unavailable", "transient": True},
        owner_id="owner-xyz",
    )
    assert incident_id is not None
    service = IncidentService()
    surfaced = service.list_incidents(production_run_id="run-owner", owner_id="owner-xyz")
    assert [i.incident_id for i in surfaced] == [incident_id]


def test_product_metrics_owner_scoped(client: TestClient) -> None:
    identity = client.post(
        "/api/identities", json={"canonical_name": "Metric", "voice_id": "v-metric"}
    ).json()
    identity_id = identity["identity_id"]
    client.post(
        "/api/identities/projects/proj-m1/bindings", json={"identity_id": identity_id}
    )
    client.post(
        "/api/identities/projects/proj-m2/bindings", json={"identity_id": identity_id}
    )
    body = client.get("/api/products/metrics").json()
    assert body["owner_id"] == USER_A["id"]
    assert body["metrics"]["IDENTITY_REUSE_RATE"] == 2.0
    assert body["metrics"]["CONTINUITY_BLOCKS_CAUGHT"] == 0
