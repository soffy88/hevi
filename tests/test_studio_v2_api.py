import httpx
import pytest

from hevi.api.main import app
from hevi.api.routers import studio_v2
from hevi.auth.dependencies import get_current_user
from hevi.production_graph import (
    Beat,
    CanonicalShot,
    Episode,
    ProductionGraphRepository,
    ProductionPlan,
    ReferenceBundle,
    ReferenceItem,
    ReferenceRole,
    RevisionPatch,
    RevisionPatchOperation,
    Scene,
    apply_revision_patch,
)


@pytest.mark.asyncio
async def test_studio_v2_project_and_source_are_canonical_revision_writes() -> None:
    repo = ProductionGraphRepository()
    user = {"id": "api-user", "is_active": True}
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[studio_v2.get_graph_repository] = lambda: repo
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/studio/projects",
                json={"title": "API canonical project", "creative_brief": "one sentence"},
            )
            assert response.status_code == 201
            project = response.json()
            project_id = project["project"]["id"]
            assert project["revision"]["revision_no"] == 1

            source = await client.post(
                f"/api/studio/projects/{project_id}/sources",
                json={"title": "public domain source", "content": "A beginning."},
            )
            assert source.status_code == 201
            assert source.json()["revision"]["revision_no"] == 2

            loaded = await client.get(f"/api/studio/projects/{project_id}")
            assert loaded.status_code == 200
            assert len(loaded.json()["sources"]) == 1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_studio_v2_domain_routes_preserve_canonical_runtime_boundaries() -> None:
    repo = ProductionGraphRepository()
    user = {"id": "api-domain-user", "is_active": True}
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[studio_v2.get_graph_repository] = lambda: repo
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/api/studio/projects",
                json={"title": "Domain API project", "creative_brief": "historical opening"},
            )
            project_id = created.json()["project"]["id"]
            assert (await client.get("/api/studio/projects")).json()["total"] == 1
            patched = await client.patch(
                f"/api/studio/projects/{project_id}", json={"title": "Retitled"}
            )
            assert patched.json()["revision"]["revision_no"] == 2

            source_response = await client.post(
                f"/api/studio/projects/{project_id}/sources",
                json={"title": "Chapter 1", "content": "Arrival. Conflict."},
            )
            source_id = source_response.json()["source"]["id"]
            chapter = {
                "meta": {"source": "public domain"},
                "characters": [
                    {"character_id": "hero", "canonical_name": "Hero", "role_in_chapter": "lead"}
                ],
                "events": [
                    {"event_id": "arrival", "summary": "Arrival", "source_span": [0, 7]},
                    {
                        "event_id": "conflict",
                        "summary": "Conflict",
                        "actors": ["hero"],
                        "causes": ["arrival"],
                        "source_span": [8, 16],
                    },
                ],
            }
            narrative = await client.post(
                f"/api/studio/projects/{project_id}/narrative/build",
                json={"source_document_id": source_id, "chapter": chapter},
            )
            event_id = narrative.json()["narrative"]["events"][0]["id"]
            adapted = await client.post(
                f"/api/studio/projects/{project_id}/adapt",
                json={"source_event_ids": [event_id], "objective": "retain the opening"},
            )
            assert adapted.status_code == 200

            snapshot = await repo.get_snapshot(project_id)
            assert snapshot is not None
            episode = Episode(id="episode-api", project_id=project_id, number=1)
            scene = Scene(id="scene-api", project_id=project_id, episode_id=episode.id)
            beat = Beat(id="beat-api", project_id=project_id, scene_id=scene.id, action="arrives")
            shot = CanonicalShot(
                id="shot-api",
                project_id=project_id,
                scene_id=scene.id,
                beat_ids=[beat.id],
                reference_bundle_id="bundle-api",
                action_description="walks into frame",
            )
            bundle = ReferenceBundle(
                id="bundle-api",
                project_id=project_id,
                shot_id=shot.id,
                items=[
                    ReferenceItem(
                        id="ref-api",
                        role=ReferenceRole.CHARACTER_IDENTITY,
                        artifact_id="artifact-hero",
                    )
                ],
            )
            plan = ProductionPlan(
                id="production-plan-api",
                project_id=project_id,
                revision_id=snapshot.revision.id,
                shot_ids=[shot.id],
            )
            patch = RevisionPatch(
                project_id=project_id,
                base_revision_id=snapshot.revision.id,
                actor=user["id"],
                reason="seed canonical API entities",
                operations=[
                    RevisionPatchOperation(
                        op="add", path="/episodes/-", value=episode.model_dump(mode="json")
                    ),
                    RevisionPatchOperation(
                        op="add", path="/scenes/-", value=scene.model_dump(mode="json")
                    ),
                    RevisionPatchOperation(
                        op="add", path="/beats/-", value=beat.model_dump(mode="json")
                    ),
                    RevisionPatchOperation(
                        op="add", path="/shots/-", value=shot.model_dump(mode="json")
                    ),
                    RevisionPatchOperation(
                        op="add", path="/reference_bundles/-", value=bundle.model_dump(mode="json")
                    ),
                    RevisionPatchOperation(
                        op="add", path="/production_plans/-", value=plan.model_dump(mode="json")
                    ),
                ],
            )
            await repo.save_snapshot(apply_revision_patch(snapshot, patch))

            assert (
                await client.get(f"/api/studio/episodes/{episode.id}/scenes")
            ).status_code == 200
            assert (await client.get(f"/api/studio/scenes/{scene.id}/shots")).json()["shots"]
            assert (await client.get(f"/api/studio/shots/{shot.id}")).status_code == 200
            assert (await client.get(f"/api/studio/shots/{shot.id}/references")).json()[
                "reference_bundle"
            ]["id"] == bundle.id
            assert (await client.get(f"/api/studio/shots/{shot.id}/qa")).status_code == 200

            readiness = await client.post(
                f"/api/studio/shots/{shot.id}/prepare", json={"context": {}}
            )
            assert readiness.json()["shot"]["readiness_state"] == "READY"
            provider = {
                "provider_id": "test-provider",
                "model": "test-model",
                "supported_intents": ["IMAGE_TO_VIDEO"],
                "supported_reference_roles": ["CHARACTER_IDENTITY"],
                "supported_resolutions": ["720p"],
                "default_resolution": "720p",
            }
            compile_body = {"provider": provider}
            compiled = await client.post(f"/api/studio/shots/{shot.id}/compile", json=compile_body)
            assert compiled.status_code == 200
            queued = await client.post(f"/api/studio/shots/{shot.id}/generate", json=compile_body)
            assert queued.json()["status"] == "queued"
            assert (await client.get(f"/api/studio/shots/{shot.id}/revisions")).status_code == 200

            session_response = await client.post(
                f"/api/studio/director/sessions?project_id={project_id}",
                json={"objective": "review the opening"},
            )
            session_id = session_response.json()["session"]["id"]
            message = await client.post(
                f"/api/studio/director/sessions/{session_id}/messages",
                json={"decision_type": "review", "rationale": "keep the shot"},
            )
            assert message.status_code == 200
            decisions = await client.get(f"/api/studio/director/sessions/{session_id}/decisions")
            assert len(decisions.json()["decisions"]) == 1

            run = await client.post(
                f"/api/studio/runs?project_id={project_id}",
                json={"line_id": "shortdrama", "execute": False},
            )
            run_id = run.json()["run_id"]
            assert (await client.get(f"/api/studio/runs/{run_id}")).status_code == 200
            assert (await client.get("/api/studio/tasks")).json()["total"] == 1
            cancelled = await client.post(f"/api/studio/tasks/{run_id}/cancel")
            assert cancelled.json()["status"] == "cancelled"
            retried = await client.post(f"/api/studio/tasks/{run_id}/retry")
            assert retried.json()["status"] == "queued"
    finally:
        app.dependency_overrides.clear()
