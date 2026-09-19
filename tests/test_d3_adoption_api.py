"""D3-A/B/C/D: product-surface adoption (API runtime behavior)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from hevi.api.main import app
from hevi.api.routers.tasks import get_task_service
from hevi.auth.dependencies import get_current_user

USER_A = {"id": "user-a"}
USER_B = {"id": "user-b"}

BINDINGS = "/api/identities/projects"


@pytest.fixture()
def authed_a():
    app.dependency_overrides[get_current_user] = lambda: USER_A
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def dbs(tmp_path, monkeypatch):
    monkeypatch.setenv("HEVI_IDENTITY_DB", str(tmp_path / "identities.db"))
    monkeypatch.setenv("HEVI_INCIDENT_DB", str(tmp_path / "incidents.db"))
    return tmp_path


@pytest.fixture()
def client(authed_a, dbs):
    return TestClient(app)


def _create_identity(client: TestClient, name: str = "Anna") -> dict:
    response = client.post(
        "/api/identities",
        json={"canonical_name": name, "kind": "character", "voice_id": "v-anna"},
    )
    assert response.status_code == 201, response.text
    return response.json()


# -- identities ----------------------------------------------------------


def test_identities_require_auth(dbs):
    with TestClient(app) as anon:
        assert anon.get("/api/identities").status_code in (401, 403)


def test_identity_crud_bind_upgrade(client: TestClient) -> None:
    identity = _create_identity(client)
    identity_id = identity["identity_id"]

    listed = client.get("/api/identities").json()
    assert [entry["identity_id"] for entry in listed] == [identity_id]

    inspected = client.get(f"/api/identities/{identity_id}").json()
    assert inspected["canonical_name"] == "Anna"
    assert inspected["identity_version"] == 1

    appearance = client.post(
        f"/api/identities/{identity_id}/appearances",
        json={"appearance_id": "stage-outfit", "kind": "outfit"},
    )
    assert appearance.status_code == 201, appearance.text
    assert appearance.json()["identity_version"] == 2

    voice = client.post(
        f"/api/identities/{identity_id}/voice", json={"voice_id": "v-anna-live"}
    )
    assert voice.status_code == 200, voice.text
    assert voice.json()["voice"]["voice_id"] == "v-anna-live"

    binding = client.post(
        f"{BINDINGS}/proj-a/bindings", json={"identity_id": identity_id}
    )
    assert binding.status_code == 201, binding.text
    assert binding.json()["pinned_identity_version"] == 3

    # Idempotent reuse: same project + identity returns the same binding.
    reused = client.post(
        f"{BINDINGS}/proj-a/bindings", json={"identity_id": identity_id}
    )
    assert reused.status_code == 201
    assert reused.json()["binding_id"] == binding.json()["binding_id"]

    # New project gets its own binding to the same canonical identity.
    binding_b = client.post(
        f"{BINDINGS}/proj-b/bindings", json={"identity_id": identity_id}
    )
    assert binding_b.status_code == 201
    assert binding_b.json()["binding_id"] != binding.json()["binding_id"]
    assert binding_b.json()["identity_id"] == identity_id


def test_upgrade_binding_route(client: TestClient) -> None:
    identity = _create_identity(client)
    binding = client.post(
        f"{BINDINGS}/proj-a/bindings", json={"identity_id": identity["identity_id"]}
    ).json()
    upgraded = client.post(f"/api/identities/bindings/{binding['binding_id']}/upgrade")
    assert upgraded.status_code == 200, upgraded.text
    assert upgraded.json()["pinned_identity_version"] >= binding["pinned_identity_version"]


def test_identity_tenant_isolation(client: TestClient) -> None:
    identity = _create_identity(client)
    identity_id = identity["identity_id"]
    app.dependency_overrides[get_current_user] = lambda: USER_B
    try:
        assert client.get("/api/identities").json() == []
        assert client.get(f"/api/identities/{identity_id}").status_code == 404
        denied = client.post(
            f"{BINDINGS}/proj-x/bindings", json={"identity_id": identity_id}
        )
        assert denied.status_code == 404
    finally:
        app.dependency_overrides[get_current_user] = lambda: USER_A


def test_subject_link_owner_scoped(client: TestClient) -> None:
    from hevi.api.routers.subjects import get_subject_service

    identity = _create_identity(client)

    class _Svc:
        async def get_subject(self, _subject_id: str):
            return None

    app.dependency_overrides[get_subject_service] = lambda: _Svc()
    try:
        missing = client.post(
            "/api/identities/subjects/nope/link",
            json={"identity_id": identity["identity_id"]},
        )
        assert missing.status_code == 404
    finally:
        app.dependency_overrides.pop(get_subject_service, None)


# -- continuity ----------------------------------------------------------


def _bind(client: TestClient, identity_id: str, project: str = "proj-a") -> dict:
    response = client.post(
        f"{BINDINGS}/{project}/bindings", json={"identity_id": identity_id}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_continuity_fact_validate_gate(client: TestClient) -> None:
    identity = _create_identity(client)
    fact = client.post(
        "/api/continuity/facts",
        json={
            "identity_id": identity["identity_id"],
            "category": "location",
            "statement": "harbor city",
            "source": "canon",
        },
    )
    assert fact.status_code == 201, fact.text
    assert fact.json()["provenance"] == "canon"

    inferred = client.post(
        "/api/continuity/facts",
        json={
            "identity_id": identity["identity_id"],
            "category": "location",
            "statement": "desert outpost",
            "source": "llm-guess",
        },
    )
    assert inferred.json()["provenance"] == "inferred"

    facts = client.get(
        f"/api/continuity/identities/{identity['identity_id']}/facts"
    ).json()
    assert len(facts["facts"]) == 2

    binding = _bind(client, identity["identity_id"])
    validation = client.post(
        "/api/continuity/validate",
        json={"binding_id": binding["binding_id"], "planned_location": "harbor city"},
    )
    assert validation.status_code == 200, validation.text
    assert validation.json()["verdict"] == "pass"

    gate = client.post(
        "/api/continuity/gate",
        json={
            "binding_id": binding["binding_id"],
            "stage": "reference_preparation",
            "overridden_by": "user-a",
        },
    )
    assert gate.status_code == 200, gate.text

    decisions = client.get(
        "/api/continuity/decisions", params={"binding_id": binding["binding_id"]}
    ).json()
    assert len(decisions["decisions"]) >= 1


def test_continuity_gate_block_and_warn(client: TestClient) -> None:
    _create_identity(client)
    client.post(
        "/api/identities",
        json={
            "canonical_name": "AnnaConstrained",
            "voice_id": "v-anna",
            "canon_constraints": ["anna never leaves harbor city"],
        },
    )
    owner_identities = {
        entry["canonical_name"]: entry["identity_id"]
        for entry in client.get("/api/identities").json()
    }
    constrained_id = owner_identities["AnnaConstrained"]
    binding = _bind(client, constrained_id)

    blocked = client.post(
        "/api/continuity/gate",
        json={
            "binding_id": binding["binding_id"],
            "stage": "video_generation",
            "planned_statements": ["Plot twist: not anna never leaves harbor city"],
            "overridden_by": "user-a",
        },
    )
    assert blocked.status_code == 409

    warned = client.post(
        "/api/continuity/gate",
        json={
            "binding_id": binding["binding_id"],
            "stage": "voice_generation",
            "planned_voice_id": "v-wrong",
        },
    )
    assert warned.status_code == 422

    overridden = client.post(
        "/api/continuity/gate",
        json={
            "binding_id": binding["binding_id"],
            "stage": "voice_generation",
            "planned_voice_id": "v-wrong",
            "overridden_by": "user-a",
        },
    )
    assert overridden.status_code == 200
    assert overridden.json()["verdict"] == "warn"


# -- incidents -----------------------------------------------------------


def _open(client: TestClient, run: str = "run-1", node: str = "task.run") -> dict:
    response = client.post(
        "/api/incidents/open",
        json={
            "production_run_id": run,
            "node_key": node,
            "failure": "PROVIDER_FAILURE",
            "evidence": {"signature": "provider temporarily unavailable", "transient": True},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_incident_lifecycle_autosafe(client: TestClient) -> None:
    incident = _open(client)
    incident_id = incident["incident_id"]
    assert incident["needs_agent"] is False

    # Dedupe: same cause + node + run returns the same incident.
    assert _open(client)["incident_id"] == incident_id

    listed = client.get("/api/incidents", params={"production_run_id": "run-1"}).json()
    assert [entry["incident_id"] for entry in listed["incidents"]] == [incident_id]

    detail = client.get(f"/api/incidents/{incident_id}").json()
    assert detail["root_cause"] == "provider_temp_unavailable"

    confirmed = client.post(f"/api/incidents/{incident_id}/confirm", json={"confirmed": True})
    assert confirmed.status_code == 200, confirmed.text

    executed = client.post(f"/api/incidents/{incident_id}/executed")
    assert executed.status_code == 200, executed.text
    assert executed.json()["attempts"] == 1

    # Duplicate execution without a new cycle is refused.
    assert client.post(f"/api/incidents/{incident_id}/executed").status_code == 409

    verified = client.post(
        f"/api/incidents/{incident_id}/verify",
        json={
            "verification": {
                "task_ok": True,
                "artifact_ok": True,
                "currency_ok": True,
                "presentation_ok": True,
            }
        },
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "resolved"


def test_incident_confirm_required_and_refuse(client: TestClient) -> None:
    response = client.post(
        "/api/incidents/open",
        json={
            "production_run_id": "run-paid",
            "node_key": "shot.regenerate",
            "failure": "DELIVERY_INTEGRITY",
            "evidence": {
                "signature": "artifact stale, paid regeneration requested",
                "may_incur_cost": True,
                "estimated_cost_usd": 1.5,
            },
        },
    )
    assert response.status_code == 201
    incident_id = response.json()["incident_id"]

    unconfirmed = client.post(f"/api/incidents/{incident_id}/confirm", json={"confirmed": False})
    assert unconfirmed.status_code == 409

    refused = client.post(f"/api/incidents/{incident_id}/refuse", json={"reason": "too expensive"})
    assert refused.status_code == 200
    assert refused.json()["status"] == "escalated_manual"


def test_incident_propose_only_when_needed(client: TestClient) -> None:
    incident = _open(client, run="run-known")
    rejected = client.post(
        f"/api/incidents/{incident['incident_id']}/propose",
        json={"kind": "replan", "detail": "agent idea"},
    )
    assert rejected.status_code == 422

    unknown = client.post(
        "/api/incidents/open",
        json={
            "production_run_id": "run-unknown",
            "node_key": "scene.direct",
            "failure": "STYLE_DRIFT",
            "evidence": {"signature": "mysterious drift, needs creative call"},
        },
    ).json()
    assert unknown["needs_agent"] is True
    proposed = client.post(
        f"/api/incidents/{unknown['incident_id']}/propose",
        json={"kind": "replan", "detail": "agent: restyle", "policy": "confirm_required"},
    )
    assert proposed.status_code == 200, proposed.text


def test_incident_verify_server_recompute(client: TestClient) -> None:
    incident = _open(client, run="run-verify")
    incident_id = incident["incident_id"]
    client.post(f"/api/incidents/{incident_id}/confirm", json={"confirmed": True})
    client.post(f"/api/incidents/{incident_id}/executed")

    task_id = str(uuid4())

    class _Repo:
        async def get_task(self, _task_id):
            return {
                "id": str(task_id),
                "status": "completed",
                "config_json": {
                    "artifact_manifest": {
                        "artifacts": [
                            {
                                "kind": "video",
                                "path": "final.mp4",
                                "sha256": "abc123",
                                "logical_role": "final_video",
                            }
                        ]
                    }
                },
            }

    class _Svc:
        repository = _Repo()

    app.dependency_overrides[get_task_service] = lambda: _Svc()
    try:
        verified = client.post(
            f"/api/incidents/{incident_id}/verify",
            json={"verification": {}, "task_id": task_id},
        )
    finally:
        app.dependency_overrides.pop(get_task_service, None)
    assert verified.status_code == 200, verified.text
    body = verified.json()
    assert body["status"] == "resolved"
    assert body["verification_result"]["currency_ok"] is True


def test_incident_restart_recovery(dbs) -> None:
    from hevi.creative.layer4.incident_store import IncidentService

    first = IncidentService()
    incident = first.open_or_get(
        production_run_id="run-restart",
        node_key="task.run",
        failure="PROVIDER_FAILURE",
        evidence={"signature": "provider temporarily unavailable", "transient": True},
    )
    action = incident.candidate_actions[0]
    assert first.authorize(incident.incident_id, action)[0] is True
    first.record_execution(incident.incident_id)

    # Simulate process restart: a fresh service on the same DB recovers
    # the incident, the attempt count, and the loop-guard history.
    second = IncidentService()
    recovered = second.get(incident.incident_id)
    assert recovered.status.value == "repair_executing"
    assert recovered.attempts == 1
    open_incidents = second.list_incidents(production_run_id="run-restart")
    assert [entry.incident_id for entry in open_incidents] == [incident.incident_id]
