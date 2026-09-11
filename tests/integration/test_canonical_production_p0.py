from __future__ import annotations

import uuid

import pytest
from obase.persistence import PgPool

from hevi.production_graph import (
    ExecutionPlan,
    ProductionGraphRepository,
    ProductionProject,
    RevisionPatch,
    RevisionPatchOperation,
    SourceChunk,
    SourceDocument,
    TaskEnvelope,
    apply_revision_patch,
)
from hevi.production_graph.durable_execution import PostgresDurableExecutionStore


@pytest.mark.asyncio
async def test_canonical_snapshot_and_task_envelope_survive_restart(
    pool: PgPool, fresh_user: str
) -> None:
    project_id = str(uuid.uuid4())
    repository = ProductionGraphRepository(pool)
    try:
        first = await repository.create_project(
            ProductionProject(id=project_id, user_id=fresh_user, title="P0 DB project")
        )
        document = SourceDocument(
            id="source-db-p0",
            project_id=project_id,
            revision_id=first.revision.id,
            title="Source",
            content_hash="content-hash",
        )
        chunk = SourceChunk(
            id="chunk-db-p0",
            document_id=document.id,
            revision_id=first.revision.id,
            start_offset=0,
            end_offset=6,
            text_hash="text-hash",
            text="Source",
        )
        patch = RevisionPatch(
            project_id=project_id,
            base_revision_id=first.revision.id,
            actor="integration",
            reason="persist source",
            operations=[
                RevisionPatchOperation(
                    op="add", path="/sources/-", value=document.model_dump(mode="json")
                ),
                RevisionPatchOperation(
                    op="add", path="/source_chunks/-", value=chunk.model_dump(mode="json")
                ),
            ],
        )
        child = apply_revision_patch(first, patch)
        await repository.save_snapshot(child)

        reopened = await ProductionGraphRepository(pool).get_snapshot(project_id)
        assert reopened is not None
        assert reopened.revision.id == child.revision.id
        assert reopened.sources[0].id == document.id
        assert reopened.source_chunks[0].document_id == document.id
        revisions = await ProductionGraphRepository(pool).list_revisions(project_id)
        assert [item.revision_no for item in revisions] == [1, 2]

        plan = ExecutionPlan(
            id="plan-db-p0",
            project_id=project_id,
            production_id=project_id,
            revision_id=child.revision.id,
            shot_id="shot-db-p0",
            provider="test",
            model="deterministic",
            idempotency_key="idem-db-p0",
        )
        envelope = TaskEnvelope(
            id="task-db-p0",
            project_id=project_id,
            revision_id=child.revision.id,
            shot_id="shot-db-p0",
            stage="video_generation",
            execution_plan_id=plan.id,
            idempotency_key=plan.idempotency_key,
        )
        task_store = PostgresDurableExecutionStore(pool)
        persisted = await task_store.persist_intent(envelope)
        recovered = await PostgresDurableExecutionStore(pool).get_by_idempotency(
            envelope.idempotency_key
        )
        assert persisted.id == envelope.id
        assert recovered is not None
        assert recovered.execution_plan_id == plan.id

        run_repository = ProductionGraphRepository(pool)
        await run_repository.save_run(
            {
                "run_id": "run-db-p0",
                "project_id": project_id,
                "revision_id": child.revision.id,
                "user_id": fresh_user,
                "status": "scheduled",
            }
        )
        assert (await ProductionGraphRepository(pool).get_run("run-db-p0", user_id=fresh_user))[
            "status"
        ] == "scheduled"
        assert len(await ProductionGraphRepository(pool).list_runs(user_id=fresh_user)) >= 1
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM productions WHERE id = $1", uuid.UUID(project_id))
