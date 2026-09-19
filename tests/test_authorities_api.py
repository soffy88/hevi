"""W13 gates: product surfaces read the authorities, and only them."""

from __future__ import annotations

import shutil
import subprocess
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hevi.api.main import app
from hevi.api.routers import authorities
from hevi.auth.dependencies import get_current_user

client = TestClient(app)


@pytest.fixture()
def authed():
    app.dependency_overrides[get_current_user] = lambda: {"id": "test-user"}
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def stores(tmp_path, monkeypatch):
    monkeypatch.setenv("HEVI_USAGE_DB", str(tmp_path / "usage.db"))
    monkeypatch.setenv("HEVI_ENDPOINTS_DB", str(tmp_path / "endpoints.db"))
    monkeypatch.setenv("HEVI_MEMORY_DB", str(tmp_path / "memory.db"))
    return tmp_path


def test_usage_endpoints_require_auth():
    assert client.get("/api/authorities/usage/calls").status_code == 401
    assert client.get("/api/authorities/usage/analytics").status_code == 401


def test_usage_dashboard_reads_ledger_only(authed, stores) -> None:
    from hevi.creative.layer4.authority_stores import CallLedgerStore
    from hevi.creative.layer4.usage_ledger import begin_call, complete_call, fail_call

    store = CallLedgerStore()
    ok = complete_call(
        begin_call(
            project_ref="pa",
            provider="p1",
            model="m1",
            operation_type="video_generate",
            estimated_cost=1.0,
        ),
        actual_cost=0.8,
    )
    bad = fail_call(
        begin_call(
            project_ref="pa",
            provider="p1",
            model="m1",
            operation_type="video_generate",
            estimated_cost=1.0,
        ),
        provider_error_code="500",
        normalized_error_code="SERVER_ERROR",
        safe_error_message="down",
    )
    store.append(ok.model_dump(mode="json"))
    store.append(bad.model_dump(mode="json"))

    listing = client.get("/api/authorities/usage/calls").json()
    assert listing["total"] == 2
    detail = client.get(f"/api/authorities/usage/calls/{ok.call_id}").json()
    assert detail["actual_cost"] == 0.8
    assert client.get("/api/authorities/usage/calls/nope").status_code == 404
    analytics = client.get("/api/authorities/usage/analytics").json()
    assert analytics["total_calls"] == 2
    assert analytics["succeeded"] == 1
    assert analytics["cost_by_project"]["pa"]["actual"] == 0.8
    filtered = client.get("/api/authorities/usage/calls", params={"status": "failed"}).json()
    assert filtered["total"] == 1


def _endpoint_definition() -> dict[str, Any]:
    return {
        "name": "demo-video",
        "provider_family": "demo",
        "base_url": "https://provider.example/v1/generate",
        "auth_mode": "api_key_header",
        "headers_template": {"X-API-Key": "{$SECRET:demo_key}"},
        "request_schema": {"properties": {"prompt": {}}},
        "request_template": '{"prompt": "{{prompt}}"}',
        "sync_mode": "sync",
        "artifact_url_path": "video_url",
        "capability": {"media_type": "video", "durations_s": [5]},
        "secret_references": ["demo_key"],
    }


def test_endpoint_settings_lifecycle(authed, stores) -> None:
    created = client.post(
        "/api/authorities/endpoints", json={"definition": _endpoint_definition()}
    ).json()
    assert created["name"] == "demo-video"
    assert client.get("/api/authorities/endpoints/demo-video").json()["state"] == "draft"
    assert client.get("/api/authorities/endpoints").json()["endpoints"][0]["name"] == "demo-video"

    validated = client.post("/api/authorities/endpoints/demo-video/validate").json()
    assert validated["valid"] is True

    preview = client.post(
        "/api/authorities/endpoints/demo-video/preview-request",
        json={"params": {"prompt": "hi"}},
    ).json()
    assert preview["sent"] is False
    assert preview["headers"] == {"X-API-Key": "{$SECRET:demo_key}"}

    checked = client.post(
        "/api/authorities/endpoints/demo-video/check-response",
        json={"raw_response": {"video_url": "https://cdn.example/x.mp4"}},
    ).json()
    assert checked["artifact_url"] == "https://cdn.example/x.mp4"
    assert checked["persisted"] is False

    capability = client.post(
        "/api/authorities/endpoints/demo-video/check-capability",
        json={"requirement": {"media_type": "video", "duration_s": 5}},
    ).json()
    assert capability["admitted"] is True

    assert client.post("/api/authorities/endpoints/demo-video/enable").status_code == 409
    trial = client.post(
        "/api/authorities/endpoints/demo-video/trial",
        json={"outcome": "success", "provider_job_ref": "job-9"},
    ).json()
    assert trial["state"] == "tested"
    assert client.post("/api/authorities/endpoints/demo-video/enable").json()["state"] == "enabled"
    assert (
        client.post("/api/authorities/endpoints/demo-video/disable").json()["state"] == "disabled"
    )
    assert client.delete("/api/authorities/endpoints/demo-video").json()["deleted"] == "demo-video"
    assert client.get("/api/authorities/endpoints/demo-video").status_code == 404


def test_endpoint_settings_reject_secrets(authed, stores) -> None:
    evil = _endpoint_definition()
    evil["headers_template"] = {"X-API-Key": "sk-abcdefgh1234567890"}
    assert client.post("/api/authorities/endpoints", json={"definition": evil}).status_code == 422


def test_memory_settings_with_pii_gate(authed, stores) -> None:
    put = client.put(
        "/api/authorities/memory",
        json={"scope": "user", "key": "subtitle_style", "content": "双语"},
    ).json()
    assert put["entry_key"] == "subtitle_style"
    listed = client.get("/api/authorities/memory", params={"scope": "user"}).json()
    assert [e["content"] for e in listed["entries"]] == ["双语"]
    edited = client.put(
        "/api/authorities/memory",
        json={"scope": "user", "key": "subtitle_style", "content": "单语"},
    ).json()
    assert edited["content"] == "单语"
    leaked = client.put(
        "/api/authorities/memory",
        json={"scope": "user", "key": "k", "content": "api_key: SECRET1"},
    )
    assert leaked.status_code == 422
    client.delete("/api/authorities/memory", params={"scope": "user", "key": "subtitle_style"})
    assert client.get("/api/authorities/memory", params={"scope": "user"}).json() == {"entries": []}
    project = client.put(
        "/api/authorities/memory",
        json={"scope": "project:p1", "key": "pacing", "content": "慢", "project_id": "p1"},
    ).json()
    assert project["scope"] == "project:p1"
    assert (
        len(
            client.get(
                "/api/authorities/memory", params={"scope": "project:p1", "project_id": "p1"}
            ).json()["entries"]
        )
        == 1
    )


def test_character_variants_visibility(authed, monkeypatch) -> None:
    async def fake_subject(pool: Any, character_id: str) -> dict[str, Any] | None:
        if character_id == "ghost":
            return None
        return {
            "id": "ch-anna",
            "name": "Anna",
            "aliases": ["Ann"],
            "reference_images": ["/r/anna.png"],
            "metadata": {"voice_ref": "v-anna"},
        }

    monkeypatch.setattr(authorities, "_load_subject", fake_subject)
    view = client.get("/api/authorities/characters/ch-anna/variants").json()
    assert view["canonical_name"] == "Anna"
    assert view["default_appearance_id"] == "default"
    assert view["appearances"][0]["appearance_id"] == "default"
    assert view["voice_by_appearance"] == {"default": "v-anna"}
    assert client.get("/api/authorities/characters/ghost/variants").status_code == 404


def _task_with_manifest(tmp_path, with_sha: bool):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg required")
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=1:size=128x128:rate=10",
            "-pix_fmt",
            "yuv420p",
            str(clip),
            "-y",
        ],
        check=True,
    )
    import hashlib

    sha = hashlib.sha256(clip.read_bytes()).hexdigest() if with_sha else None
    artifact: dict[str, Any] = {
        "artifact_id": "v-1",
        "kind": "video",
        "path": str(clip),
        "media_type": "video/mp4",
        "primary": True,
        "logical_role": "final_video",
    }
    if sha:
        artifact["sha256"] = sha
    return {
        "id": str(uuid.uuid4()),
        "status": "completed",
        "config_json": {
            "revision_id": "rev-9",
            "artifact_manifest": {"production_id": "p", "artifacts": [artifact]},
        },
    }


def test_task_presentation_and_currency_visibility(authed, tmp_path, monkeypatch) -> None:
    async def fake_task(pool: Any, task_id: Any) -> dict[str, Any] | None:
        return _task_with_manifest(tmp_path, with_sha=True)

    monkeypatch.setattr(authorities, "_load_task", fake_task)
    task_id = str(uuid.uuid4())
    presentation = client.get(f"/api/authorities/tasks/{task_id}/presentation").json()
    assert presentation["video_artifact_id"] == "v-1"
    assert presentation["effective_duration_ms"] == 1000
    currency = client.get(f"/api/authorities/tasks/{task_id}/currency").json()
    assert currency["evaluations"]["v-1"]["currency"] == "current"
    assert currency["usable"] == 1


def test_task_currency_missing_without_sha(authed, tmp_path, monkeypatch) -> None:
    async def fake_task(pool: Any, task_id: Any) -> dict[str, Any] | None:
        task = _task_with_manifest(tmp_path, with_sha=False)
        task["config_json"]["artifact_manifest"]["artifacts"][0]["path"] = "/nonexistent/x.mp4"
        return task

    monkeypatch.setattr(authorities, "_load_task", fake_task)
    currency = client.get(f"/api/authorities/tasks/{uuid.uuid4()}/currency").json()
    assert currency["evaluations"]["v-1"]["currency"] == "missing"
    assert currency["usable"] == 0


def test_task_plan_projection_consumer(authed, tmp_path, monkeypatch) -> None:
    """W17 K02 consumer: plan projection served for a real task state."""

    async def fake_task(pool: Any, task_id: Any) -> dict[str, Any] | None:
        return _task_with_manifest(tmp_path, with_sha=True)

    monkeypatch.setattr(authorities, "_load_task", fake_task)
    plan = client.get(f"/api/authorities/tasks/{uuid.uuid4()}/plan").json()
    assert plan["counts"]["completed"] + plan["counts"]["ready"] == 1
    target = plan["targets"][0]
    assert target["target_id"] == "v-1"
    assert target["status"] in {"completed", "ready"}


def test_regeneration_plan_and_explicit_reuse(authed, tmp_path, monkeypatch) -> None:
    """O04: stale/current media is reusable; reuse short-circuits regeneration."""

    from hevi.api.routers import tasks as tasks_router

    task = _task_with_manifest(tmp_path, with_sha=True)
    task["user_id"] = "test-user"

    class Repo:
        pool = object()

        async def get_task(self, _task_id: object) -> dict[str, Any]:
            return task

        async def get_shots(self, _task_id: object) -> list[dict[str, Any]]:
            return []

    repo = Repo()
    monkeypatch.setattr(tasks_router, "_regeneration_plan", tasks_router._regeneration_plan)

    async def fake_get_service() -> Any:
        class Svc:
            repository = repo

        return Svc()

    app.dependency_overrides[tasks_router.get_task_service] = fake_get_service
    try:
        task_id = task["id"]
        plan = client.get(f"/api/tasks/{task_id}/regenerate/plan").json()
        assert plan["available"] is True
        assert plan["all_usable"] is True
        assert plan["targets"][0]["currency"] == "current"

        reused = client.post(
            f"/api/tasks/{task_id}/regenerate",
            json={"shot_ids": [0], "reuse_current": True},
        ).json()
        assert reused["reused"] is True
        assert reused["currency_targets"][0]["artifact_id"] == "v-1"
    finally:
        app.dependency_overrides.pop(tasks_router.get_task_service, None)
