"""PostgreSQL-backed restart/resume proof for the canonical execution path."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from hevi.production_graph import (
    DurableExecutionCoordinator,
    ExecutionPlan,
    PostgresDurableExecutionStore,
    ProductionGraphRepository,
    ProductionProject,
    envelope_from_execution_plan,
)


class RestartableProvider:
    def __init__(self, artifact: Path) -> None:
        self.artifact = artifact
        self.create_calls = 0
        self.poll_calls = 0

    async def send(self, request: dict, *, idempotency_key: str) -> str:
        del request, idempotency_key
        self.create_calls += 1
        return "postgres-job-1"

    async def poll(self, provider_job_id: str) -> dict:
        assert provider_job_id == "postgres-job-1"
        self.poll_calls += 1
        if self.poll_calls == 1:
            raise TimeoutError("controlled transient polling failure")
        return {"status": "completed", "artifact_path": str(self.artifact)}

    async def download(self, provider_job_id: str, destination: str) -> str:
        del provider_job_id, destination
        return str(self.artifact)

    async def cancel(self, provider_job_id: str) -> None:
        del provider_job_id

    def parse_error(self, error: Exception) -> dict:
        return {"error": str(error)}


@pytest.mark.asyncio
async def test_database_backed_resume_preserves_provider_job_and_idempotency(
    pool, fresh_user: str, tmp_path: Path
) -> None:
    project_id = str(uuid.uuid4())
    repo = ProductionGraphRepository(pool)
    await repo.create_project(
        ProductionProject(id=project_id, user_id=fresh_user, title="P0 durable")
    )
    snapshot = await repo.get_snapshot(project_id)
    assert snapshot is not None
    artifact = tmp_path / "resumed.mp4"
    artifact.write_bytes(b"controlled provider artifact")
    plan = ExecutionPlan(
        project_id=project_id,
        production_id=project_id,
        revision_id=snapshot.revision.id,
        shot_id="shot-durable-p0",
        provider="controlled-postgres-provider",
        idempotency_key=f"p0:{project_id}",
    )
    envelope = envelope_from_execution_plan(plan)
    provider = RestartableProvider(artifact)

    first = await DurableExecutionCoordinator(PostgresDurableExecutionStore(pool)).execute(
        envelope, provider, {"prompt": "resume"}
    )
    assert first.status == "interrupted"
    assert first.provider_job_id == "postgres-job-1"

    restarted_store = PostgresDurableExecutionStore(pool)
    recovered = await restarted_store.get_by_idempotency(plan.idempotency_key)
    assert recovered is not None
    assert recovered.provider_job_id == "postgres-job-1"
    second = await DurableExecutionCoordinator(restarted_store).execute(
        envelope, provider, {}, register_artifact=lambda path, _: f"artifact:{path}"
    )
    assert second.status == "completed"
    assert provider.create_calls == 1
    assert second.envelope.provider_job_id == "postgres-job-1"
    assert second.artifact_ids == [f"artifact:{artifact}"]

    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM production_graph_entities WHERE project_id = $1", uuid.UUID(project_id)
        )
        await conn.execute(
            "UPDATE productions SET active_revision_id = NULL WHERE id = $1", uuid.UUID(project_id)
        )
        await conn.execute(
            "DELETE FROM production_revisions WHERE production_id = $1", uuid.UUID(project_id)
        )
        await conn.execute("DELETE FROM productions WHERE id = $1", uuid.UUID(project_id))
