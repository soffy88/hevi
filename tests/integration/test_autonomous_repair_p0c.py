"""P0-C: PostgreSQL-backed attempts/artifacts with bounded repair decisions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from obase.persistence import PgPool

from hevi.artifact_store.object_store import LocalObjectStore
from hevi.artifact_store.repository import ArtifactRepository
from hevi.execution.plan import RepairPlan, compute_dag_closure, decide_repair
from hevi.production.artifacts import Artifact, ArtifactManifest
from hevi.production_graph.repository import ProductionGraphRepository
from hevi.quality.evaluation import QualityEvaluation
from hevi.quality.evidence import EvaluationEvidence
from hevi.quality.gate_policy import GatePolicy
from hevi.quality.repair_controller import RepairBudget, RepairController
from hevi.tasks.attempt_repository import AttemptRepository
from hevi.tasks.repository import TaskRepository
from hevi.tasks.task_service import TaskService


@dataclass
class _RepairContext:
    production_id: uuid.UUID
    revision_id: uuid.UUID
    task_id: uuid.UUID
    attempt_a: uuid.UUID
    artifacts: dict[str, str]
    task: dict[str, Any]
    store: LocalObjectStore


async def _make_context(pool: PgPool, tmp_path: Path) -> _RepairContext:
    production_id = uuid.uuid4()
    revision = await ProductionGraphRepository(pool).create(
        {
            "work_id": str(production_id),
            "user_id": "p0c-integration",
            "type": "p0c",
            "status": "draft",
        }
    )
    revision_id = uuid.UUID(str(revision["revision_id"]))
    task_id = uuid.uuid4()
    now = datetime.now(UTC).replace(tzinfo=None)
    task = await TaskRepository(pool).create_task(
        {
            "id": task_id,
            "topic": "p0c-repair",
            "duration_archetype": "1-5min",
            "video_provider": "fake",
            "audio_provider": "fake",
            "status": "queued",
            "progress_pct": 0.0,
            "total_shots": 5,
            "completed_shots": 0,
            "config_json": {"production_id": str(production_id), "revision_id": str(revision_id)},
            "created_at": now,
            "updated_at": now,
            "queued_at": now,
        }
    )
    lease_token = f"p0c-lease-{uuid.uuid4().hex}"
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE video_tasks
            SET worker_id = $2, lease_token = $3,
                lease_until = $4, heartbeat_at = $4
            WHERE id = $1
            """,
            task_id,
            "p0c-worker-a",
            lease_token,
            now + timedelta(minutes=5),
        )
    task = await TaskRepository(pool).get_task(task_id) or task
    service = TaskService(TaskRepository(pool))
    attempt = await service._start_attempt(task)
    assert attempt is not None
    attempt_a = uuid.UUID(str(attempt["id"]))

    store = LocalObjectStore(tmp_path / "objects")
    artifact_repo = ArtifactRepository(pool, store)
    artifacts: dict[str, str] = {}
    for node in ("A", "B", "C", "D", "E"):
        source = tmp_path / f"{node.lower()}-v1.bin"
        source.write_bytes(f"artifact-{node}-v1".encode())
        manifest = ArtifactManifest(
            production_id=str(production_id),
            revision_id=str(revision_id),
            attempt_id=str(attempt_a),
            tenant_id="p0c-integration",
            artifacts=[
                Artifact.from_path(
                    source,
                    kind="video",
                    media_type="video/mp4",
                    primary=True,
                    logical_role=f"node-{node}",
                    created_by_attempt_id=str(attempt_a),
                )
            ],
        )
        committed = await artifact_repo.commit(manifest)
        artifacts[node] = str(committed.artifacts[0].artifact_id)
    return _RepairContext(production_id, revision_id, task_id, attempt_a, artifacts, task, store)


async def _cleanup(pool: PgPool, context: _RepairContext) -> None:
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM video_tasks WHERE id = $1", context.task_id)
        await conn.execute("DELETE FROM productions WHERE id = $1", context.production_id)


def _failed_evaluation(context: _RepairContext) -> QualityEvaluation:
    evidence = EvaluationEvidence(
        id=str(uuid.uuid4()),
        attempt_id=str(context.attempt_a),
        artifact_id=context.artifacts["B"],
        constraint_id="p0c-constraint-B",
        evaluator_id="IDENTITY_MISMATCH",
        evaluator_version="p0c.fake-evaluator.1",
        metric="IDENTITY_MISMATCH",
        score=0.2,
        threshold=0.75,
        passed=False,
        details={"scope": "B"},
    )
    return QualityEvaluation.from_evidence([evidence], GatePolicy.for_profile("standard"))


@pytest.mark.asyncio
async def test_p0c_c1_fail_attempt_triggers_new_attempt_with_lineage(
    pool: PgPool, tmp_path: Path
) -> None:
    context = await _make_context(pool, tmp_path)
    try:
        controller = RepairController(RepairBudget(max_attempts=2, max_cost_usd=10.0))
        evaluation = _failed_evaluation(context)
        controller.observe(evaluation)
        decision = controller.decide(evaluation)
        assert decision.should_repair is True

        attempts = AttemptRepository(pool)
        assert await attempts.finish(
            context.attempt_a,
            lease_token=str(context.task["lease_token"]),
            status="failed",
            error="quality gate failed",
        )
        context.task["lease_token"] = f"p0c-lease-{uuid.uuid4().hex}"
        context.task["worker_id"] = "p0c-worker-b"
        context.task["lease_until"] = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=5)
        context.task["_source_attempt_id"] = str(context.attempt_a)
        attempt_b = await TaskService(TaskRepository(pool))._start_attempt(context.task)
        assert attempt_b is not None
        attempt_b_id = uuid.UUID(str(attempt_b["id"]))
        assert attempt_b_id != context.attempt_a
        async with pool.acquire() as conn:
            lineage = await conn.fetchval(
                "SELECT source_attempt_id FROM task_attempts WHERE id = $1", attempt_b_id
            )
        assert lineage == context.attempt_a
        repair_plan = RepairPlan.create(
            str(context.production_id),
            str(context.attempt_a),
            "verdict-p0c-c1",
            ["p0c-constraint-B"],
            ["B"],
            ["B", "D"],
            [context.artifacts["A"], context.artifacts["C"], context.artifacts["E"]],
            1.0,
            0.8,
            "execute",
            "identity failure",
            1,
        )
        assert repair_plan.source_attempt_id == str(context.attempt_a)
    finally:
        await _cleanup(pool, context)


@pytest.mark.asyncio
async def test_p0c_c2_repair_is_scoped_to_b_and_d(pool: PgPool, tmp_path: Path) -> None:
    context = await _make_context(pool, tmp_path)
    try:
        rerun, preserve = compute_dag_closure(
            ["B"],
            {"A": ["B", "C"], "B": ["D"], "C": ["E"]},
            context.artifacts,
            {context.artifacts["B"], context.artifacts["D"]},
        )
        assert set(rerun) == {"B", "D"}
        assert set(preserve) == {
            context.artifacts["A"],
            context.artifacts["C"],
            context.artifacts["E"],
        }
        assert set(rerun) != set(context.artifacts)
    finally:
        await _cleanup(pool, context)


@pytest.mark.asyncio
async def test_p0c_c3_preserve_artifacts_and_create_new_b_d_artifacts(
    pool: PgPool, tmp_path: Path
) -> None:
    context = await _make_context(pool, tmp_path)
    try:
        attempts = AttemptRepository(pool)
        await attempts.finish(
            context.attempt_a,
            lease_token=str(context.task["lease_token"]),
            status="failed",
            error="quality gate failed",
        )
        context.task["lease_token"] = f"p0c-lease-{uuid.uuid4().hex}"
        context.task["worker_id"] = "p0c-worker-b"
        context.task["lease_until"] = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=5)
        attempt_b = await TaskService(TaskRepository(pool))._start_attempt(context.task)
        assert attempt_b is not None
        attempt_b_id = str(attempt_b["id"])
        repo = ArtifactRepository(pool, context.store)
        new_ids: dict[str, str] = {}
        for node in ("B", "D"):
            source = tmp_path / f"{node.lower()}-v2.bin"
            source.write_bytes(f"artifact-{node}-v2".encode())
            committed = await repo.commit(
                ArtifactManifest(
                    production_id=str(context.production_id),
                    revision_id=str(context.revision_id),
                    attempt_id=attempt_b_id,
                    tenant_id="p0c-integration",
                    artifacts=[
                        Artifact.from_path(
                            source,
                            kind="video",
                            media_type="video/mp4",
                            primary=True,
                            logical_role=f"node-{node}",
                            created_by_attempt_id=attempt_b_id,
                        )
                    ],
                )
            )
            new_ids[node] = str(committed.artifacts[0].artifact_id)
        loaded = await repo.get_manifest(str(context.production_id), revision_id=str(context.revision_id))
        assert loaded is not None
        by_role = {item.logical_role: str(item.artifact_id) for item in loaded.artifacts}
        for node in ("A", "C", "E"):
            assert by_role[f"node-{node}"] == context.artifacts[node]
        for node in ("B", "D"):
            assert new_ids[node] != context.artifacts[node]
            assert by_role[f"node-{node}"] == new_ids[node]
    finally:
        await _cleanup(pool, context)


@pytest.mark.asyncio
async def test_p0c_c4_repair_completion_runs_artifact_evaluation_verdict_chain(
    pool: PgPool, tmp_path: Path
) -> None:
    context = await _make_context(pool, tmp_path)
    try:
        repair_plan = RepairPlan.create(
            str(context.production_id),
            str(context.attempt_a),
            str(uuid.uuid4()),
            ["p0c-constraint-B"],
            ["B"],
            ["B", "D"],
            [context.artifacts["A"], context.artifacts["C"], context.artifacts["E"]],
            1.0,
            0.8,
            "execute",
            "quality failure",
            1,
        )

        async def runner(attempt_id: uuid.UUID, nodes: list[str]) -> ArtifactManifest:
            assert set(nodes) == {"B", "D"}
            source = tmp_path / "repair-b-v2.bin"
            source.write_bytes(b"artifact-pass")
            return ArtifactManifest(
                production_id=str(context.production_id),
                revision_id=str(context.revision_id),
                attempt_id=str(attempt_id),
                tenant_id="p0c-integration",
                artifacts=[
                    Artifact.from_path(
                        source,
                        kind="video",
                        media_type="video/mp4",
                        primary=True,
                        logical_role="node-B-repair",
                        created_by_attempt_id=str(attempt_id),
                    )
                ],
            )

        async def evaluator(manifest: ArtifactManifest) -> list[EvaluationEvidence]:
            artifact = manifest.artifacts[0]
            assert artifact.artifact_id
            return [
                EvaluationEvidence(
                    id=str(uuid.uuid4()),
                    attempt_id=str(manifest.attempt_id),
                    artifact_id=str(artifact.artifact_id),
                    constraint_id="p0c-constraint-B",
                    evaluator_id="IDENTITY_MISMATCH",
                    evaluator_version="p0c.fake-evaluator.2",
                    metric="IDENTITY_MISMATCH",
                    score=0.95,
                    threshold=0.75,
                    passed=True,
                )
            ]

        result = await TaskService(TaskRepository(pool)).run_repair_attempt(
            context.task_id,
            repair_plan,
            runner=runner,
            evaluator=evaluator,
            artifact_repository=ArtifactRepository(pool, context.store),
        )
        new_attempt_id = uuid.UUID(str(result["attempt"]["id"]))
        assert new_attempt_id != context.attempt_a
        assert result["evaluation"].passed is True
        assert result["verdict"]["passed"] is True
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT a.status, a.source_attempt_id, t.status AS task_status,
                       e.artifact_id, e.passed
                FROM task_attempts a
                JOIN video_tasks t ON t.id = a.task_id
                JOIN evaluation_evidence e ON e.attempt_id = a.id
                WHERE a.id = $1
                """,
                new_attempt_id,
            )
        assert row is not None
        assert row["status"] == "succeeded"
        assert row["source_attempt_id"] == context.attempt_a
        assert row["task_status"] == "completed"
        assert row["passed"] is True
    finally:
        await _cleanup(pool, context)


@pytest.mark.asyncio
async def test_p0c_c5_second_fail_enters_decide_repair(pool: PgPool, tmp_path: Path) -> None:
    context = await _make_context(pool, tmp_path)
    try:
        first = decide_repair(0.20, None, 0, 10.0, 1.0)
        second = decide_repair(0.20, 0.20, 1, 9.0, 1.0)
        assert first[0] is True
        assert second == (False, "marginal_gain_below_threshold")
    finally:
        await _cleanup(pool, context)


@pytest.mark.asyncio
async def test_p0c_c6_max_iterations_stops(pool: PgPool, tmp_path: Path) -> None:
    context = await _make_context(pool, tmp_path)
    try:
        should_repair, reason = decide_repair(0.2, 0.1, 2, 10.0, 1.0, max_iterations=2)
        assert should_repair is False
        assert reason == "max_iterations_reached"
    finally:
        await _cleanup(pool, context)


@pytest.mark.asyncio
async def test_p0c_c7_insufficient_budget_stops(pool: PgPool, tmp_path: Path) -> None:
    context = await _make_context(pool, tmp_path)
    try:
        should_repair, reason = decide_repair(0.2, None, 0, 0.5, 1.0)
        assert should_repair is False
        assert reason == "budget_exhausted"
    finally:
        await _cleanup(pool, context)


@pytest.mark.asyncio
async def test_p0c_c8_oscillating_stops(pool: PgPool, tmp_path: Path) -> None:
    context = await _make_context(pool, tmp_path)
    try:
        should_repair, reason = decide_repair(0.2, None, 0, 10.0, 1.0, convergence_state="oscillating")
        assert should_repair is False
        assert reason == "convergence_oscillating"
    finally:
        await _cleanup(pool, context)


@pytest.mark.asyncio
async def test_p0c_c9_diverging_stops(pool: PgPool, tmp_path: Path) -> None:
    context = await _make_context(pool, tmp_path)
    try:
        should_repair, reason = decide_repair(0.2, None, 0, 10.0, 1.0, convergence_state="diverging")
        assert should_repair is False
        assert reason == "convergence_diverging"
    finally:
        await _cleanup(pool, context)
