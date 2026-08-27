"""P0-B: artifact-backed evaluation and delivery-gate integration tests."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from obase.persistence import PgPool

from hevi.artifact_store.object_store import LocalObjectStore
from hevi.artifact_store.repository import ArtifactRepository
from hevi.production.artifacts import Artifact, ArtifactManifest
from hevi.production_graph.repository import ProductionGraphRepository
from hevi.quality.evaluation import QualityEvaluation
from hevi.quality.evidence import ConstraintEvaluation, EvaluationEvidence
from hevi.quality.gate_policy import GatePolicy, gate_verdict
from hevi.quality.repair_controller import RepairBudget, RepairController
from hevi.quality.repository import RepairRepository
from hevi.quality.taxonomy import FailureCode
from hevi.tasks.repository import TaskRepository


@dataclass
class _ArtifactContext:
    production_id: uuid.UUID
    revision_id: uuid.UUID
    task_id: uuid.UUID
    attempt_id: uuid.UUID
    artifact_id: str
    manifest: ArtifactManifest
    store: LocalObjectStore


async def _make_context(pool: PgPool, tmp_path: Path, payload: bytes = b"artifact-pass") -> _ArtifactContext:
    production_id = uuid.uuid4()
    attempt_id = uuid.uuid4()
    revision = await ProductionGraphRepository(pool).create(
        {
            "work_id": str(production_id),
            "user_id": "p0b-integration",
            "type": "p0b",
            "status": "draft",
        }
    )
    revision_id = uuid.UUID(str(revision["revision_id"]))
    task_id = uuid.uuid4()
    now = __import__("datetime").datetime.now(__import__("datetime").UTC).replace(tzinfo=None)
    await TaskRepository(pool).create_task(
        {
            "id": task_id,
            "topic": "p0b-artifact",
            "duration_archetype": "1-5min",
            "video_provider": "fake",
            "audio_provider": "fake",
            "status": "pending",
            "progress_pct": 0.0,
            "total_shots": 1,
            "completed_shots": 0,
            "config_json": {"production_id": str(production_id)},
            "created_at": now,
            "updated_at": now,
        }
    )
    source = tmp_path / f"artifact-{uuid.uuid4().hex}.bin"
    source.write_bytes(payload)
    store = LocalObjectStore(tmp_path / "objects")
    artifact_repo = ArtifactRepository(pool, store)
    manifest = ArtifactManifest(
        production_id=str(production_id),
        revision_id=str(revision_id),
        attempt_id=str(attempt_id),
        tenant_id="p0b-integration",
        artifacts=[
            Artifact.from_path(
                source,
                kind="video",
                media_type="video/mp4",
                primary=True,
                logical_role="final_video",
                created_by_attempt_id=str(attempt_id),
            )
        ],
    )
    committed = await artifact_repo.commit(manifest)
    assert committed.artifacts[0].artifact_id
    loaded = await artifact_repo.get_manifest(str(production_id), revision_id=str(revision_id))
    assert loaded is not None
    return _ArtifactContext(
        production_id,
        revision_id,
        task_id,
        attempt_id,
        str(committed.artifacts[0].artifact_id),
        committed,
        store,
    )


async def _cleanup(pool: PgPool, context: _ArtifactContext) -> None:
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM productions WHERE id = $1", context.production_id)


def _evidence(
    context: _ArtifactContext,
    *,
    passed: bool | None,
    metric: str = FailureCode.IDENTITY_MISMATCH.value,
    details: dict[str, Any] | None = None,
) -> EvaluationEvidence:
    return EvaluationEvidence(
        id=str(uuid.uuid4()),
        attempt_id=str(context.attempt_id),
        artifact_id=context.artifact_id,
        constraint_id="p0b-required-identity",
        evaluator_id=metric,
        evaluator_version="p0b.fake-evaluator.1",
        metric=metric,
        score=0.95 if passed else (0.2 if passed is False else None),
        threshold=0.75 if passed is not None else None,
        passed=passed,
        evidence_artifact_ids=[],
        details=details or {},
    )


async def _evaluate_bytes(context: _ArtifactContext) -> EvaluationEvidence:
    artifact = context.manifest.artifacts[0]
    data = await context.store.get_bytes(str(artifact.uri))
    return _evidence(context, passed=data == b"artifact-pass", details={"bytes_read": len(data)})


@pytest.mark.asyncio
async def test_p0b_b1_real_artifact_evaluator_evidence_is_queryable(
    pool: PgPool, tmp_path: Path
) -> None:
    context = await _make_context(pool, tmp_path)
    try:
        evidence = await _evaluate_bytes(context)
        assert evidence.artifact_id == context.artifact_id
        assert evidence.constraint_id
        assert evidence.evaluator_id
        assert evidence.evaluator_version
        assert evidence.metric
        assert evidence.passed is True

        policy = GatePolicy.for_profile("standard")
        evaluation = QualityEvaluation.from_evidence([evidence], policy)
        controller = RepairController(RepairBudget(max_attempts=1, max_cost_usd=1.0))
        controller.observe(evaluation)
        decision = controller.decide(evaluation)
        # This is the existing production quality persistence path. It must
        # persist the raw evidence row, not only an aggregate JSON snapshot.
        try:
            await RepairRepository(pool).save_run(
                task_id=context.task_id,
                production_id=context.production_id,
                revision_id=context.revision_id,
                attempt_id=str(context.attempt_id),
                evidence_artifact_id=context.artifact_id,
                policy=policy,
                controller=controller,
                decision=decision,
                evaluation=evaluation,
            )
        except Exception as exc:
            pytest.fail(f"production evidence persistence path failed: {type(exc).__name__}: {exc}")

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT artifact_id, constraint_id, evaluator_id, evaluator_version,
                       metric, passed
                FROM evaluation_evidence WHERE id = $1
                """,
                uuid.UUID(evidence.id),
            )
        assert row is not None
        assert dict(row) == {
            "artifact_id": uuid.UUID(context.artifact_id),
            "constraint_id": evidence.constraint_id,
            "evaluator_id": evidence.evaluator_id,
            "evaluator_version": evidence.evaluator_version,
            "metric": evidence.metric,
            "passed": True,
        }
    finally:
        await _cleanup(pool, context)


@pytest.mark.asyncio
async def test_p0b_b2_missing_reference_is_unknown_and_blocked(pool: PgPool, tmp_path: Path) -> None:
    context = await _make_context(pool, tmp_path)
    try:
        evidence = _evidence(
            context,
            passed=None,
            details={"reason": "missing_reference_artifact"},
        )
        evaluation = QualityEvaluation.from_evidence([evidence], GatePolicy.for_profile("standard"))
        assert evaluation.violations == [
            ConstraintEvaluation(
                constraint_id=evidence.constraint_id or "",
                status="unknown",
                score=None,
                evidence_ids=[evidence.id],
                reason="missing_reference_artifact",
            )
        ]
        verdict = gate_verdict([evidence], GatePolicy.for_profile("standard"))
        assert verdict["passed"] is False
    finally:
        await _cleanup(pool, context)


@pytest.mark.asyncio
async def test_p0b_b3_evaluator_exception_becomes_unknown(pool: PgPool, tmp_path: Path) -> None:
    context = await _make_context(pool, tmp_path)
    try:
        async def evaluator() -> EvaluationEvidence:
            raise RuntimeError("evaluator unavailable")

        try:
            evidence = await evaluator()
        except Exception as exc:
            evidence = _evidence(
                context,
                passed=None,
                details={"reason": "evaluator_exception", "error": str(exc)},
            )
        assert evidence.passed is None
        assert QualityEvaluation.from_evidence(
            [evidence], GatePolicy.for_profile("standard")
        ).violations[0].status == "unknown"
        assert gate_verdict([evidence], GatePolicy.for_profile("standard"))["passed"] is False
    finally:
        await _cleanup(pool, context)


@pytest.mark.asyncio
async def test_p0b_b4_standard_required_unknown_blocks(pool: PgPool, tmp_path: Path) -> None:
    context = await _make_context(pool, tmp_path)
    try:
        evidence = _evidence(context, passed=None, details={"reason": "model_unavailable"})
        verdict = gate_verdict([evidence], GatePolicy.for_profile("standard"))
        assert verdict["passed"] is False
        assert verdict["evaluation"]["unknowns"] == [evidence.constraint_id]
    finally:
        await _cleanup(pool, context)


@pytest.mark.asyncio
async def test_p0b_b5_cinema_required_unknown_blocks(pool: PgPool, tmp_path: Path) -> None:
    context = await _make_context(pool, tmp_path)
    try:
        evidence = _evidence(context, passed=None, details={"reason": "no_reference"})
        verdict = gate_verdict([evidence], GatePolicy.for_profile("cinema"))
        assert verdict["passed"] is False
    finally:
        await _cleanup(pool, context)


@pytest.mark.asyncio
async def test_p0b_b6_economy_unknown_is_degraded_not_full_pass(
    pool: PgPool, tmp_path: Path
) -> None:
    context = await _make_context(pool, tmp_path)
    try:
        evidence = _evidence(context, passed=None, details={"reason": "model_unavailable"})
        verdict = gate_verdict([evidence], GatePolicy.for_profile("economy"))
        assert verdict["degraded"] is True
        assert not (verdict["passed"] and not verdict["degraded"])
    finally:
        await _cleanup(pool, context)


@pytest.mark.asyncio
async def test_p0b_b7_real_fail_blocks_delivery(pool: PgPool, tmp_path: Path) -> None:
    context = await _make_context(pool, tmp_path)
    try:
        evidence = _evidence(context, passed=False, details={"reason": "real_identity_fail"})
        verdict = gate_verdict([evidence], GatePolicy.for_profile("standard"))
        assert verdict["passed"] is False
        assert verdict["evaluation"]["blocking"]
    finally:
        await _cleanup(pool, context)


@pytest.mark.asyncio
async def test_p0b_b8_real_pass_allows_delivery(pool: PgPool, tmp_path: Path) -> None:
    context = await _make_context(pool, tmp_path)
    try:
        evidence = await _evaluate_bytes(context)
        verdict = gate_verdict([evidence], GatePolicy.for_profile("standard"))
        assert evidence.passed is True
        assert verdict["passed"] is True
        assert verdict["degraded"] is False
    finally:
        await _cleanup(pool, context)
