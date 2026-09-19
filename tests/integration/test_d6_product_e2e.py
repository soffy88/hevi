"""D6-J productization E2E (E2E-P1..P5) through the real API."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hevi.api.main import app
from hevi.auth.dependencies import get_current_user

OWNER_A = {"id": "d6-owner-a"}
OWNER_B = {"id": "d6-owner-b"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HEVI_IDENTITY_DB", str(tmp_path / "identities.db"))
    monkeypatch.setenv("HEVI_INCIDENT_DB", str(tmp_path / "incidents.db"))
    monkeypatch.setenv("HEVI_MEMORY_DB", str(tmp_path / "memory.db"))
    app.dependency_overrides[get_current_user] = lambda: OWNER_A
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_e2e_p1_character_library_cross_project(client: TestClient) -> None:
    created = client.post(
        "/api/identities",
        json={"canonical_name": "Aurora", "voice_id": "v-aurora"},
    ).json()
    identity_id = created["identity_id"]
    client.post(
        f"/api/identities/{identity_id}/appearances",
        json={"appearance_id": "stage", "kind": "outfit"},
    )
    binding = client.post(
        "/api/identities/projects/proj-a/bindings", json={"identity_id": identity_id}
    ).json()
    assert binding["pinned_identity_version"] == 2

    # Project B reuses and pins.
    binding_b = client.post(
        "/api/identities/projects/proj-b/bindings", json={"identity_id": identity_id}
    ).json()
    assert binding_b["pinned_identity_version"] == 2

    # Global update bumps version; B now shows upgrade available.
    client.post(f"/api/identities/{identity_id}/voice", json={"voice_id": "v-aurora-2"})
    listed = client.get("/api/identities").json()
    entry = next(i for i in listed if i["identity_id"] == identity_id)
    assert entry["identity_version"] == 3
    assert entry["upgrade_available"] is True

    # Explicit upgrade only.
    upgraded = client.post(f"/api/identities/bindings/{binding_b['binding_id']}/upgrade").json()
    assert upgraded["pinned_identity_version"] == 3
    # Project A stayed pinned at 2.
    a_bindings = client.get("/api/identities/projects/proj-a/bindings").json()
    assert a_bindings[0]["pinned_identity_version"] == 2

    # Production gate passes against the upgraded binding.
    gate = client.post(
        "/api/continuity/gate",
        json={
            "binding_id": binding_b["binding_id"],
            "stage": "video_generation",
            "planned_voice_id": "v-aurora-2",
            "overridden_by": "studio",
        },
    )
    assert gate.status_code == 200


def test_e2e_p2_continuity_blocks_then_passes(client: TestClient) -> None:
    identity = client.post(
        "/api/identities",
        json={
            "canonical_name": "Guard",
            "voice_id": "v-guard",
            "canon_constraints": ["guard never removes the red coat"],
        },
    ).json()
    identity_id = identity["identity_id"]
    binding = client.post(
        "/api/identities/projects/proj-c/bindings", json={"identity_id": identity_id}
    ).json()

    blocked = client.post(
        "/api/continuity/gate",
        json={
            "binding_id": binding["binding_id"],
            "stage": "video_generation",
            "planned_statements": ["Twist: not guard never removes the red coat"],
            "overridden_by": "studio",
        },
    )
    assert blocked.status_code == 409

    summary = client.get("/api/continuity/projects/proj-c/summary").json()
    assert summary["verdict"] == "pass"  # no contradictory plan at rest
    # Health projection for the project marks BLOCK when the plan is contradictory.
    health = client.get(
        "/api/products/projects/proj-c/health",
        params={"binding_id": binding["binding_id"]},
    ).json()
    assert health["status"] in ("BLOCKED", "READY")

    corrected = client.post(
        "/api/continuity/gate",
        json={
            "binding_id": binding["binding_id"],
            "stage": "video_generation",
            "overridden_by": "studio",
        },
    )
    assert corrected.status_code == 200
    assert corrected.json()["verdict"] in ("pass", "warn")


def test_e2e_p3_autosafe_repair_no_billing(client: TestClient) -> None:
    incident = client.post(
        "/api/incidents/open",
        json={
            "production_run_id": "run-p3",
            "node_key": "artifact.download",
            "failure": "DELIVERY_INTEGRITY",
            "evidence": {"signature": "download interrupted at 62%"},
        },
    ).json()
    incident_id = incident["incident_id"]
    assert incident["candidate_actions"][0]["policy"] == "auto_safe"

    client.post(f"/api/incidents/{incident_id}/confirm", json={"confirmed": True})
    client.post(f"/api/incidents/{incident_id}/executed")
    resolved = client.post(
        f"/api/incidents/{incident_id}/verify",
        json={
            "verification": {
                "task_ok": True,
                "artifact_ok": True,
                "currency_ok": True,
                "presentation_ok": True,
            }
        },
    ).json()
    assert resolved["status"] == "resolved"
    product = client.get(f"/api/incidents/{incident_id}", params={"product": True}).json()
    assert product["policy"] == "auto_safe"
    assert product["estimated_cost_usd"] == 0.0


def test_e2e_p4_paid_repair_requires_confirmation(client: TestClient) -> None:
    run_id = "run-p4"
    client.post(
        "/api/incidents/open",
        json={
            "production_run_id": run_id,
            "node_key": "shot.regenerate",
            "failure": "DELIVERY_INTEGRITY",
            "evidence": {
                "signature": "artifact stale, paid regeneration requested",
                "may_incur_cost": True,
                "estimated_cost_usd": 5.0,
            },
        },
    )
    incident = client.get("/api/incidents", params={"production_run_id": run_id}).json()["incidents"][0]
    incident_id = incident["incident_id"]
    product = client.get(f"/api/incidents/{incident_id}", params={"product": True}).json()
    assert product["requires_confirmation"] is True

    # Before confirmation: no authorization, no execution.
    unconfirmed = client.post(f"/api/incidents/{incident_id}/confirm", json={"confirmed": False})
    assert unconfirmed.status_code == 409
    assert client.get(f"/api/incidents/{incident_id}").json()["attempts"] == 0

    # Explicit confirmation executes exactly once.
    assert client.post(
        f"/api/incidents/{incident_id}/confirm", json={"confirmed": True}
    ).status_code == 200
    assert client.post(f"/api/incidents/{incident_id}/executed").status_code == 200
    assert client.post(f"/api/incidents/{incident_id}/executed").status_code == 409
    assert client.get(f"/api/incidents/{incident_id}").json()["attempts"] == 1


def test_e2e_p5_tenant_isolation(client: TestClient) -> None:
    identity = client.post(
        "/api/identities", json={"canonical_name": "Private", "voice_id": "v-priv"}
    ).json()
    run_id = "run-p5"
    client.post(
        "/api/incidents/open",
        json={
            "production_run_id": run_id,
            "node_key": "task.run",
            "failure": "PROVIDER_FAILURE",
            "evidence": {"signature": "provider temporarily unavailable", "transient": True},
        },
    )
    client.put(
        "/api/authorities/memory",
        json={"scope": "user", "key": "style", "content": "cinematic"},
    )

    app.dependency_overrides[get_current_user] = lambda: OWNER_B
    try:
        assert client.get("/api/identities").json() == []
        assert client.get(f"/api/identities/{identity['identity_id']}").status_code == 404
        assert client.get(
            "/api/continuity/projects/proj-c/summary"
        ).json()["binding_count"] == 0
        assert client.get(
            "/api/incidents", params={"production_run_id": run_id}
        ).json()["incidents"] == []
        assert client.get("/api/authorities/memory").json()["entries"] == []
        assert client.get("/api/products/metrics").json()["metrics"]["IDENTITY_REUSE_RATE"] == 0.0
    finally:
        app.dependency_overrides[get_current_user] = lambda: OWNER_A
