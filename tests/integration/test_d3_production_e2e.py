"""D3 production E2Es: E2E-D3-1..5 through the real API + services."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from hevi.api.main import app
from hevi.api.routers.tasks import get_task_service
from hevi.auth.dependencies import get_current_user
from hevi.creative.layer4.repair_incident import IncidentError

USER = {"id": "e2e-user"}


@pytest.fixture(autouse=True)
def _isolated_dbs(tmp_path, monkeypatch):
    monkeypatch.setenv("HEVI_IDENTITY_DB", str(tmp_path / "identities.db"))
    monkeypatch.setenv("HEVI_INCIDENT_DB", str(tmp_path / "incidents.db"))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HEVI_IDENTITY_DB", str(tmp_path / "identities.db"))
    monkeypatch.setenv("HEVI_INCIDENT_DB", str(tmp_path / "incidents.db"))
    app.dependency_overrides[get_current_user] = lambda: USER
    yield TestClient(app)
    app.dependency_overrides.clear()


def _manifest_task(task_id: str) -> dict:
    return {
        "id": task_id,
        "status": "completed",
        "config_json": {
            "artifact_manifest": {
                "artifacts": [
                    {
                        "kind": "video",
                        "path": "final.mp4",
                        "sha256": "e2e-sha",
                        "logical_role": "final_video",
                    }
                ]
            }
        },
    }


class _Repo:
    def __init__(self, task: dict):
        self._task = task

    async def get_task(self, _task_id):
        return self._task


class _Svc:
    def __init__(self, task: dict):
        self.repository = _Repo(task)


def test_e2e_d3_1_persistent_identity_cross_project_production(client: TestClient) -> None:
    """Project A builds identity -> Project B binds+pins -> production artifact."""
    identity = client.post(
        "/api/identities",
        json={
            "canonical_name": "E2EAnna",
            "kind": "presenter",
            "voice_id": "v-e2e-anna",
            "default_references": ["ref-anna"],
        },
    ).json()
    identity_id = identity["identity_id"]
    client.post(
        f"/api/identities/{identity_id}/appearances",
        json={"appearance_id": "stage-outfit", "kind": "outfit",
              "reference_asset_ids": ["ref-stage"]},
    )

    binding_a = client.post(
        "/api/identities/projects/proj-e2e-a/bindings", json={"identity_id": identity_id}
    ).json()
    validation_a = client.post(
        "/api/continuity/validate",
        json={
            "binding_id": binding_a["binding_id"],
            "planned_appearance_id": "stage-outfit",
            "planned_voice_id": "v-e2e-anna",
        },
    )
    assert validation_a.json()["verdict"] == "pass"
    artifact_a = {
        "artifact_id": "artifact-e2e-a1",
        "project_id": "proj-e2e-a",
        "identity_id": identity_id,
    }
    fact_a = client.post(
        "/api/continuity/facts",
        json={
            "identity_id": identity_id,
            "category": "appearance",
            "statement": "stage-outfit worn in proj-e2e-a ep1",
            "source": "production-artifact",
            "source_artifact_id": artifact_a["artifact_id"],
            "episode": "ep1",
        },
    )
    assert fact_a.status_code == 201

    # Project B reuses the same canonical identity: new binding, pinned version.
    binding_b = client.post(
        "/api/identities/projects/proj-e2e-b/bindings", json={"identity_id": identity_id}
    ).json()
    assert binding_b["identity_id"] == identity_id
    assert binding_b["binding_id"] != binding_a["binding_id"]
    assert binding_b["pinned_identity_version"] == 2

    gate_b = client.post(
        "/api/continuity/gate",
        json={
            "binding_id": binding_b["binding_id"],
            "stage": "video_generation",
            "planned_appearance_id": "stage-outfit",
            "planned_voice_id": "v-e2e-anna",
            "overridden_by": "e2e-user",
        },
    )
    assert gate_b.status_code == 200, gate_b.text
    assert gate_b.json()["verdict"] == "pass"


def test_e2e_d3_2_continuity_gate_blocks_then_updates(client: TestClient) -> None:
    """State (red coat + injured + sword lost) -> contradictory request BLOCKs
    paid generation; corrected request produces and updates continuity."""
    identity = client.post(
        "/api/identities",
        json={
            "canonical_name": "E2EGuard",
            "voice_id": "v-guard",
            "canon_constraints": ["guard never removes the red coat on duty"],
        },
    ).json()
    identity_id = identity["identity_id"]
    for category, statement in (
        ("appearance", "wears red coat"),
        ("character_state", "injured left arm"),
        ("prop", "sword lost at the harbor"),
    ):
        response = client.post(
            "/api/continuity/facts",
            json={
                "identity_id": identity_id,
                "category": category,
                "statement": statement,
                "source": "approved-shot-result",
                "source_artifact_id": "artifact-ep1",
                "episode": "ep1",
            },
        )
        assert response.status_code == 201
    binding = client.post(
        "/api/identities/projects/proj-e2e-c/bindings", json={"identity_id": identity_id}
    ).json()

    blocked = client.post(
        "/api/continuity/gate",
        json={
            "binding_id": binding["binding_id"],
            "stage": "video_generation",
            "planned_appearance_id": "default",
            "planned_location": "harbor",
            "planned_props": ["sword in hand"],
            "planned_statements": ["Scene: not guard never removes the red coat on duty"],
            "overridden_by": "e2e-user",
        },
    )
    assert blocked.status_code == 409

    corrected = client.post(
        "/api/continuity/gate",
        json={
            "binding_id": binding["binding_id"],
            "stage": "video_generation",
            "planned_location": "harbor",
            "overridden_by": "e2e-user",
        },
    )
    assert corrected.status_code == 200, corrected.text

    # Production succeeds -> canonical commit path writes the new fact.
    new_fact = client.post(
        "/api/continuity/facts",
        json={
            "identity_id": identity_id,
            "category": "prop",
            "statement": "brass compass recovered",
            "source": "approved-shot-result",
            "source_artifact_id": "artifact-ep2",
            "episode": "ep2",
            "revision": "rev-5",
        },
    )
    assert new_fact.status_code == 201
    assert new_fact.json()["revision"] == "rev-5"
    ep2 = client.get(
        f"/api/continuity/identities/{identity_id}/facts", params={"episode": "ep2"}
    ).json()
    assert [fact["statement"] for fact in ep2["facts"]] == ["brass compass recovered"]


def test_e2e_d3_3_autosafe_repair_no_billing(client: TestClient) -> None:
    """Recoverable failure -> incident -> AUTO_SAFE -> execute -> verify CURRENT."""
    task_id = str(uuid4())
    app.dependency_overrides[get_task_service] = lambda: _Svc(_manifest_task(task_id))
    try:
        incident = client.post(
            "/api/incidents/open",
            json={
                "production_run_id": task_id,
                "node_key": "artifact.download",
                "failure": "DELIVERY_INTEGRITY",
                "evidence": {"signature": "download interrupted at 62%"},
            },
        ).json()
        incident_id = incident["incident_id"]
        action = incident["candidate_actions"][0]
        assert action["policy"] == "auto_safe"
        assert action["estimated_cost_usd"] == 0.0

        assert client.post(
            f"/api/incidents/{incident_id}/confirm", json={"confirmed": True}
        ).status_code == 200
        assert client.post(f"/api/incidents/{incident_id}/executed").status_code == 200
        verified = client.post(
            f"/api/incidents/{incident_id}/verify",
            json={"verification": {}, "task_id": task_id},
        )
        assert verified.status_code == 200, verified.text
        body = verified.json()
        assert body["status"] == "resolved"
        assert body["verification_result"]["presentation_ok"] is True
    finally:
        app.dependency_overrides.pop(get_task_service, None)


def test_e2e_d3_4_paid_repair_confirm_gate() -> None:
    """Paid regen: unconfirmed -> 409 with zero submits; confirmed -> exactly one."""
    from hevi.creative.layer4.incident_store import IncidentService

    service = IncidentService()
    incident = service.open_or_get(
        production_run_id="run-paid-e2e",
        node_key="shot.regenerate",
        failure="DELIVERY_INTEGRITY",
        evidence={
            "signature": "artifact stale, paid regeneration requested",
            "may_incur_cost": True,
            "estimated_cost_usd": 2.0,
        },
    )
    action = incident.candidate_actions[0]
    assert action.policy.value == "confirm_required"

    provider_submits = 0
    approved, _ = service.authorize(incident.incident_id, action, confirmed=False)
    assert approved is False
    assert provider_submits == 0  # UNCONFIRMED_PAID_REPAIR=0

    approved, _ = service.authorize(incident.incident_id, action, confirmed=True)
    assert approved is True
    service.record_execution(incident.incident_id)
    provider_submits += 1  # the single allowed execution, delegated to runtime
    assert provider_submits == 1
    assert service.get(incident.incident_id).attempts == 1

    resolved = service.verify(
        incident.incident_id,
        {"task_ok": True, "artifact_ok": True, "currency_ok": True,
         "presentation_ok": True},
    )
    assert resolved.status.value == "resolved"


def test_e2e_d3_5_restart_resume_no_duplicates() -> None:
    """Repair active -> restart -> resume same incident/action, no duplicates."""
    from hevi.creative.layer4.incident_store import IncidentService

    first = IncidentService()
    incident = first.open_or_get(
        production_run_id="run-restart-e2e",
        node_key="task.run",
        failure="PROVIDER_FAILURE",
        evidence={"signature": "provider temporarily unavailable", "transient": True},
    )
    action = incident.candidate_actions[0]
    assert first.authorize(incident.incident_id, action)[0] is True
    first.record_execution(incident.incident_id)

    restarted = IncidentService()
    recovered = restarted.get(incident.incident_id)
    assert recovered.attempts == 1
    assert recovered.status.value == "repair_executing"

    # No duplicate side effects: recording again without a new cycle refuses.
    with pytest.raises(IncidentError, match="REPAIR_DUPLICATE_EXECUTION_REFUSED"):
        restarted.record_execution(incident.incident_id)

    resolved = restarted.verify(
        incident.incident_id,
        {"task_ok": True, "artifact_ok": True, "currency_ok": True,
         "presentation_ok": True},
    )
    assert resolved.status.value == "resolved"
    assert resolved.attempts == 1
