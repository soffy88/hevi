"""D5-A: memory endpoint tenant isolation (cross-owner + anonymous)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hevi.api.main import app
from hevi.auth.dependencies import get_current_user

USER_A = {"id": "mem-owner-a"}
USER_B = {"id": "mem-owner-b"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HEVI_MEMORY_DB", str(tmp_path / "memory.db"))
    app.dependency_overrides[get_current_user] = lambda: USER_A
    yield TestClient(app)
    app.dependency_overrides.clear()


def _put(client: TestClient, scope: str, key: str, content: str, project_id: str = ""):
    return client.put(
        "/api/authorities/memory",
        json={"scope": scope, "key": key, "content": content, "project_id": project_id},
    )


def _get(client: TestClient, scope: str, project_id: str = ""):
    return client.get(
        "/api/authorities/memory", params={"scope": scope, "project_id": project_id}
    )


def test_memory_requires_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("HEVI_MEMORY_DB", str(tmp_path / "anon.db"))
    # No lifespan context: unauthenticated request must be refused by the
    # auth dependency before any handler runs.
    anon = TestClient(app)
    assert anon.get("/api/authorities/memory").status_code in (401, 403)


def test_cross_owner_user_memory_read_refused(client: TestClient) -> None:
    assert _put(client, "user", "style", "cinematic realistic").status_code == 200
    owner_a = {entry["entry_key"] for entry in _get(client, "user").json()["entries"]}
    assert owner_a == {"style"}

    app.dependency_overrides[get_current_user] = lambda: USER_B
    try:
        owner_b = _get(client, "user").json()["entries"]
        assert owner_b == []  # no cross-tenant read
    finally:
        app.dependency_overrides[get_current_user] = lambda: USER_A
    # Owner A still sees their own entry.
    assert {e["entry_key"] for e in _get(client, "user").json()["entries"]} == {"style"}


def test_cross_owner_user_memory_write_refused(client: TestClient) -> None:
    assert _put(client, "user", "pacing", "slow").status_code == 200
    app.dependency_overrides[get_current_user] = lambda: USER_B
    try:
        # B's same key writes into B's namespace only; A is untouched.
        assert _put(client, "user", "pacing", "fast").status_code == 200
        b_entries = {e["entry_key"]: e["content"] for e in _get(client, "user").json()["entries"]}
        assert b_entries == {"pacing": "fast"}
    finally:
        app.dependency_overrides[get_current_user] = lambda: USER_A
    a_entries = {e["entry_key"]: e["content"] for e in _get(client, "user").json()["entries"]}
    assert a_entries == {"pacing": "slow"}


def test_cross_owner_project_convention_refused(client: TestClient) -> None:
    assert _put(client, "project:proj-shared", "tone", "warm", project_id="proj-shared").status_code == 200
    app.dependency_overrides[get_current_user] = lambda: USER_B
    try:
        # Same project_id, different owner: no shared truth.
        assert _get(client, "project:proj-shared", project_id="proj-shared").json()["entries"] == []
        assert _put(
            client, "project:proj-shared", "tone", "cold", project_id="proj-shared"
        ).status_code == 200
        b = _get(client, "project:proj-shared", project_id="proj-shared").json()["entries"]
        assert {e["content"] for e in b} == {"cold"}
    finally:
        app.dependency_overrides[get_current_user] = lambda: USER_A
    a = _get(client, "project:proj-shared", project_id="proj-shared").json()["entries"]
    assert {e["content"] for e in a} == {"warm"}


def test_owner_a_cannot_delete_owner_b_memory(client: TestClient) -> None:
    app.dependency_overrides[get_current_user] = lambda: USER_B
    try:
        assert _put(client, "user", "secret", "b-only").status_code == 200
    finally:
        app.dependency_overrides[get_current_user] = lambda: USER_A
    # A deleting the same key affects only A's (empty) namespace.
    response = client.delete(
        "/api/authorities/memory", params={"scope": "user", "key": "secret"}
    )
    assert response.status_code == 200
    app.dependency_overrides[get_current_user] = lambda: USER_B
    try:
        b = _get(client, "user").json()["entries"]
        assert {e["entry_key"] for e in b} == {"secret"}  # B's entry survived
    finally:
        app.dependency_overrides[get_current_user] = lambda: USER_A


def test_enumeration_does_not_disclose(client: TestClient) -> None:
    _put(client, "user", "k1", "v1")
    _put(client, "user", "k2", "v2")
    app.dependency_overrides[get_current_user] = lambda: USER_B
    try:
        # No client-supplied user_id exists; B sees an empty namespace.
        assert _get(client, "user").json()["entries"] == []
    finally:
        app.dependency_overrides[get_current_user] = lambda: USER_A
