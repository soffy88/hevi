"""Cross-P0 production-closure acceptance test on PostgreSQL."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from obase.persistence import PgPool

from hevi.artifact_store.object_store import LocalObjectStore
from hevi.artifact_store.repository import ArtifactRepository
from hevi.constraints import (
    Constraint,
    ConstraintGraph,
    ConstraintRepository,
    ConsumptionStage,
    CoverageReport,
    ProviderCapabilities,
    compile_graph,
)
from hevi.credits.account_service import AccountService
from hevi.credits.billing_service import BillingService
from hevi.credits.repository import CreditRepository
from hevi.execution.plan import ExecutionPlan, RepairPlan
from hevi.execution.repository import ExecutionPlanRepository
from hevi.production.adapters import ProductionAdapterRegistry
from hevi.production.artifacts import Artifact, ArtifactManifest
from hevi.production_graph.repository import ProductionGraphRepository
from hevi.quality.evaluation import QualityEvaluation
from hevi.quality.evidence import EvaluationEvidence
from hevi.quality.gate_policy import GatePolicy
from hevi.quality.repair_controller import RepairBudget, RepairController
from hevi.quality.repository import RepairRepository
from hevi.tasks.repository import TaskRepository
from hevi.tasks.task_service import TaskService


@dataclass
class _Lineage:
    production_id: uuid.UUID
    revision_id: uuid.UUID
    plan_v1_id: str = ""
    plan_v2_id: str = ""
    attempt_v1_id: str = ""
    attempt_v2_id: str = ""
    constraint_ids: list[str] = field(default_factory=list)
    receipt_ids: list[str] = field(default_factory=list)
    artifact_v1_ids: list[str] = field(default_factory=list)
    artifact_v2_ids: list[str] = field(default_factory=list)
    evaluation_v1_ids: list[str] = field(default_factory=list)
    evaluation_v2_ids: list[str] = field(default_factory=list)
    repair_plan_id: str = ""
    reservation_id: str = ""


class _FakeProvider:
    def __init__(self) -> None:
        self.job_id = f"cross-p0-job-{uuid.uuid4().hex}"

    async def submit(self, payload: dict[str, Any]) -> str:
        assert payload["constraints"]
        return self.job_id


def _hash_payload(value: Any) -> str:
    import hashlib
    import json

    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def _provider_adapter(task: dict[str, Any], pool: PgPool) -> dict[str, Any]:
    provider = task["provider"]
    repository = ConstraintRepository(pool)
    mappings: list[dict[str, Any]] = []
    for instruction in task["compiled_instructions"]:
        mapping = {
            "constraint_id": str(instruction["constraint_id"]),
            "mapping_type": "prompt",
            "mapping_path": f"request.constraints[{len(mappings)}]",
            "payload": instruction["payload"],
        }
        mappings.append(mapping)
        await repository.record_consumption_receipt(
            production_id=uuid.UUID(task["production_id"]),
            revision_id=uuid.UUID(task["revision_id"]),
            attempt_id=uuid.UUID(task["attempt_id"]),
            constraint_id=mapping["constraint_id"],
            provider_id="cross-p0-provider",
            adapter_id="cross-p0-production-adapter",
            stage=ConsumptionStage.ADAPTER_CONSUMED,
            mapping_type=mapping["mapping_type"],
            mapping_path=mapping["mapping_path"],
            payload_hash=_hash_payload(mapping["payload"]),
        )
    job_id = await provider.submit({"constraints": mappings})
    for mapping in mappings:
        for stage in (ConsumptionStage.PROVIDER_SUBMITTED, ConsumptionStage.PROVIDER_ACKED):
            await repository.record_consumption_receipt(
                production_id=uuid.UUID(task["production_id"]),
                revision_id=uuid.UUID(task["revision_id"]),
                attempt_id=uuid.UUID(task["attempt_id"]),
                constraint_id=mapping["constraint_id"],
                provider_id="cross-p0-provider",
                adapter_id="cross-p0-production-adapter",
                stage=stage,
                mapping_type=mapping["mapping_type"],
                mapping_path=mapping["mapping_path"],
                payload_hash=_hash_payload(mapping["payload"]),
                provider_request_id=job_id,
            )
    return {"job_id": job_id}


@pytest.mark.asyncio
async def test_cross_p0_production_closure_lineage(
    pool: PgPool, fresh_user: str, tmp_path: Path
) -> None:
    production_id = uuid.uuid4()
    task_id = uuid.uuid4()
    graph = ConstraintGraph(
        constraints=[
            Constraint(
                id=f"cross-{production_id.hex}-identity",
                type="identity",
                severity="required",
                scope="shot:0",
                payload={"subject": "alice"},
            )
        ],
        coverage=CoverageReport(expected_fields=1, derived_constraints=1),
    )
    graph_repo = ProductionGraphRepository(pool)
    lineage = _Lineage(production_id=production_id, revision_id=uuid.uuid4())
    plan_repository = ExecutionPlanRepository(pool)
    task_repository = TaskRepository(pool)
    try:
        production = await graph_repo.create(
            {
                "work_id": str(production_id),
                "user_id": fresh_user,
                "type": "cross-p0",
                "status": "draft",
                "constraint_graph": graph.model_dump(mode="json"),
            }
        )
        lineage.revision_id = uuid.UUID(str(production["revision_id"]))
        lineage.constraint_ids = [item.id for item in graph.constraints]
        compiled = compile_graph(
            graph,
            ProviderCapabilities(
                provider_id="cross-p0-provider", adapter_id="cross-p0-production-adapter"
            ),
        )
        await ConstraintRepository(pool).record_compilation(
            str(lineage.revision_id),
            compiled=len(compiled.compiled_constraint_ids),
            consumed=0,
            unsupported=len(compiled.unsupported),
            silent_drops=len(compiled.silent_drops),
        )
        plan_v1 = ExecutionPlan.create(
            str(production_id),
            str(lineage.revision_id),
            {
                "nodes": {
                    "A": [],
                    "B": ["A"],
                    "C": ["A"],
                    "D": ["B"],
                    "E": ["C"],
                },
                "constraints": lineage.constraint_ids,
            },
        )
        saved_plan_v1 = await plan_repository.save(plan_v1)
        lineage.plan_v1_id = saved_plan_v1.id

        now = datetime.now(UTC).replace(tzinfo=None)
        await task_repository.create_task(
            {
                "id": task_id,
                "topic": "cross-p0",
                "duration_archetype": "1-5min",
                "video_provider": "fake",
                "audio_provider": "fake",
                "status": "queued",
                "progress_pct": 0.0,
                "total_shots": 1,
                "completed_shots": 0,
                "user_id": fresh_user,
                "config_json": {
                    "production_id": str(production_id),
                    "revision_id": str(lineage.revision_id),
                    "production_source": "cross-p0",
                },
                "created_at": now,
                "updated_at": now,
                "queued_at": now,
                # Keep this acceptance task ahead of stale compatibility rows
                # left by interrupted local workers while still using the
                # production claim path.
                "priority": 1_000_000,
            }
        )
        claimed = await task_repository.claim_next_queued_task(worker_id="cross-p0-worker")
        assert claimed is not None and claimed["id"] == task_id
        service = TaskService(task_repository)
        attempt_v1 = await service._start_attempt(claimed)
        assert attempt_v1 is not None
        lineage.attempt_v1_id = str(attempt_v1["id"])

        attempt_placeholder = uuid.UUID(lineage.attempt_v1_id)
        for index, instruction in enumerate(compiled.instructions):
            await ConstraintRepository(pool).record_consumption_receipt(
                production_id=production_id,
                revision_id=lineage.revision_id,
                attempt_id=attempt_placeholder,
                constraint_id=str(instruction["constraint_id"]),
                provider_id="cross-p0-provider",
                adapter_id="cross-p0-production-adapter",
                stage=ConsumptionStage.COMPILED,
                mapping_type="compiled",
                mapping_path=f"compiled.instructions[{index}]",
                payload_hash=_hash_payload(instruction),
            )

        billing = BillingService(AccountService(CreditRepository(pool)), pool=pool)
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE credit_accounts SET balance = 100, reserved_balance = 0 WHERE user_id = $1",
                uuid.UUID(fresh_user),
            )
        reservation = await billing.reserve(
            fresh_user,
            100,
            production_id=str(production_id),
            task_id=str(task_id),
            attempt_id=lineage.attempt_v1_id,
            external_ref=f"cross-p0:reserve:{uuid.uuid4().hex}",
        )
        lineage.reservation_id = str(reservation["id"])

        compiled_task = {
            "config_json": {"production_source": "cross-p0"},
            "production_id": str(production_id),
            "revision_id": str(lineage.revision_id),
            "attempt_id": lineage.attempt_v1_id,
            "compiled_instructions": compiled.instructions,
            "provider": _FakeProvider(),
        }
        registry = ProductionAdapterRegistry()
        registry.register("cross-p0", _provider_adapter)
        await registry.execute(compiled_task, pool)

        store = LocalObjectStore(tmp_path / "objects")
        artifact_repository = ArtifactRepository(pool, store)
        v1_artifacts: list[Artifact] = []
        for node in ("A", "B", "C", "D", "E"):
            source = tmp_path / f"cross-{node}-v1.bin"
            source.write_bytes(f"cross-{node}-v1".encode())
            v1_artifacts.append(
                Artifact.from_path(
                    source,
                    kind="video",
                    media_type="video/mp4",
                    primary=node == "E",
                    logical_role=f"node-{node}",
                    created_by_attempt_id=lineage.attempt_v1_id,
                )
            )
        committed_v1 = await artifact_repository.commit(
            ArtifactManifest(
                production_id=str(production_id),
                revision_id=str(lineage.revision_id),
                attempt_id=lineage.attempt_v1_id,
                tenant_id=fresh_user,
                artifacts=v1_artifacts,
            )
        )
        lineage.artifact_v1_ids = [str(item.artifact_id) for item in committed_v1.artifacts]

        failed_evidence = EvaluationEvidence(
            id=str(uuid.uuid4()),
            attempt_id=lineage.attempt_v1_id,
            artifact_id=lineage.artifact_v1_ids[1],
            constraint_id=lineage.constraint_ids[0],
            evaluator_id="IDENTITY_MISMATCH",
            evaluator_version="cross-p0-evaluator.1",
            metric="IDENTITY_MISMATCH",
            score=0.2,
            threshold=0.75,
            passed=False,
            details={"scope": "B", "reason": "identity mismatch"},
        )
        policy = GatePolicy.for_profile("standard")
        quality_v1 = QualityEvaluation.from_evidence([failed_evidence], policy)
        controller = RepairController(RepairBudget(max_attempts=2, max_cost_usd=10.0))
        controller.observe(quality_v1)
        decision = controller.decide(quality_v1)
        repair_plan = RepairPlan.create(
            str(production_id),
            lineage.attempt_v1_id,
            "",
            lineage.constraint_ids,
            ["B"],
            ["B", "D"],
            [lineage.artifact_v1_ids[0], lineage.artifact_v1_ids[2], lineage.artifact_v1_ids[4]],
            1.0,
            0.8,
            "execute",
            "identity mismatch",
            1,
        )
        await RepairRepository(pool).save_run(
            task_id=task_id,
            production_id=production_id,
            revision_id=lineage.revision_id,
            attempt_id=lineage.attempt_v1_id,
            evidence_artifact_id=lineage.artifact_v1_ids[1],
            policy=policy,
            controller=controller,
            decision=decision,
            evaluation=quality_v1,
            repair_plan=repair_plan,
        )
        verdict_v1 = {
            "passed": quality_v1.passed,
            "evidence": quality_v1.evidence,
        }
        assert verdict_v1["passed"] is False
        await service._finish_attempt(
            claimed, status="failed", error="quality gate failed"
        )
        await task_repository.update_task(task_id, {"status": "failed"})

        async def runner(attempt_id: uuid.UUID, nodes: list[str]) -> ArtifactManifest:
            assert set(nodes) == {"B", "D"}
            plan_v2 = ExecutionPlan.from_existing(
                saved_plan_v1,
                {**saved_plan_v1.plan_json, "repair_nodes": nodes},
                created_by_attempt_id=str(attempt_id),
                change_reason="repair",
            )
            saved_plan = await plan_repository.save(plan_v2)
            lineage.plan_v2_id = saved_plan.id
            artifacts: list[Artifact] = []
            for node in nodes:
                source = tmp_path / f"cross-{node}-v2.bin"
                source.write_bytes(f"cross-{node}-v2".encode())
                artifacts.append(
                    Artifact.from_path(
                        source,
                        kind="video",
                        media_type="video/mp4",
                        primary=node == "D",
                        logical_role=f"node-{node}-repair",
                        created_by_attempt_id=str(attempt_id),
                    )
                )
            return ArtifactManifest(
                production_id=str(production_id),
                revision_id=str(lineage.revision_id),
                attempt_id=str(attempt_id),
                tenant_id=fresh_user,
                artifacts=artifacts,
            )

        async def evaluator(manifest: ArtifactManifest) -> list[EvaluationEvidence]:
            artifact = next(item for item in manifest.artifacts if item.primary)
            assert artifact.artifact_id
            return [
                EvaluationEvidence(
                    id=str(uuid.uuid4()),
                    attempt_id=str(manifest.attempt_id),
                    artifact_id=str(artifact.artifact_id),
                    constraint_id=lineage.constraint_ids[0],
                    evaluator_id="IDENTITY_MISMATCH",
                    evaluator_version="cross-p0-evaluator.2",
                    metric="IDENTITY_MISMATCH",
                    score=0.95,
                    threshold=0.75,
                    passed=True,
                )
            ]

        repaired = await service.run_repair_attempt(
            task_id,
            repair_plan,
            runner=runner,
            evaluator=evaluator,
            artifact_repository=artifact_repository,
            policy=policy,
        )
        lineage.attempt_v2_id = str(repaired["attempt"]["id"])
        lineage.artifact_v2_ids = [
            str(item.artifact_id) for item in repaired["manifest"].artifacts
        ]
        assert repaired["evaluation"].passed is True
        assert repaired["verdict"]["passed"] is True
        consumed = await billing.consume(
            lineage.reservation_id,
            100,
            external_ref=f"cross-p0:consume:{uuid.uuid4().hex}",
        )
        assert consumed["status"] == "consumed"

        async with pool.acquire() as conn:
            receipt_rows = await conn.fetch(
                """
                SELECT id, stage, mapping_path, payload_hash, provider_request_id
                FROM constraint_consumption_receipts
                WHERE production_id = $1 AND revision_id = $2 AND attempt_id = $3
                ORDER BY stage
                """,
                production_id,
                lineage.revision_id,
                attempt_placeholder,
            )
            lineage.receipt_ids = [str(row["id"]) for row in receipt_rows]
            assert {row["stage"] for row in receipt_rows} == {
                "compiled",
                "adapter_consumed",
                "provider_submitted",
                "provider_acked",
            }
            assert all(row["mapping_path"] and row["payload_hash"] for row in receipt_rows)
            assert receipt_rows[-1]["provider_request_id"]
            plan_parent = await conn.fetchval(
                "SELECT parent_plan_id FROM execution_plans WHERE id = $1",
                uuid.UUID(lineage.plan_v2_id),
            )
            assert plan_parent == uuid.UUID(lineage.plan_v1_id)
            attempt_source = await conn.fetchval(
                "SELECT source_attempt_id FROM task_attempts WHERE id = $1",
                uuid.UUID(lineage.attempt_v2_id),
            )
            assert attempt_source == uuid.UUID(lineage.attempt_v1_id)
            repair_row = await conn.fetchrow(
                """
                SELECT id, source_verdict_id FROM repair_plans
                WHERE task_id = $1 ORDER BY created_at DESC LIMIT 1
                """,
                task_id,
            )
            assert repair_row is not None and repair_row["source_verdict_id"] is not None
            lineage.repair_plan_id = str(repair_row["id"])
            eval_rows = await conn.fetch(
                "SELECT id, attempt_id, evidence_artifact_id FROM evaluations WHERE task_id = $1 ORDER BY created_at",
                task_id,
            )
            lineage.evaluation_v1_ids = [str(eval_rows[0]["id"])]
            lineage.evaluation_v2_ids = [str(eval_rows[-1]["id"])]
            assert str(eval_rows[-1]["attempt_id"]) == lineage.attempt_v2_id
            evidence_v2 = await conn.fetchrow(
                "SELECT artifact_id, passed FROM evaluation_evidence WHERE attempt_id = $1",
                uuid.UUID(lineage.attempt_v2_id),
            )
            assert evidence_v2 is not None
            assert str(evidence_v2["artifact_id"]) in lineage.artifact_v2_ids
            reservation_row = await conn.fetchrow(
                "SELECT id, task_id, attempt_id, status FROM billing_reservations WHERE id = $1",
                uuid.UUID(lineage.reservation_id),
            )
            assert reservation_row is not None
            assert reservation_row["task_id"] == task_id
            assert reservation_row["attempt_id"] == uuid.UUID(lineage.attempt_v1_id)
            assert reservation_row["status"] == "consumed"
            task_row = await conn.fetchrow(
                "SELECT status FROM video_tasks WHERE id = $1", task_id
            )
            assert task_row["status"] == "completed"

        assert lineage.plan_v2_id
        assert lineage.attempt_v2_id != lineage.attempt_v1_id
        assert set(lineage.artifact_v1_ids).isdisjoint(lineage.artifact_v2_ids)
        assert repaired["verdict"]["passed"] is True
        print(
            {
                "production_id": str(lineage.production_id),
                "revision_id": str(lineage.revision_id),
                "plan_v1_id": lineage.plan_v1_id,
                "plan_v2_id": lineage.plan_v2_id,
                "attempt_v1_id": lineage.attempt_v1_id,
                "attempt_v2_id": lineage.attempt_v2_id,
                "constraint_ids": lineage.constraint_ids,
                "receipt_ids": lineage.receipt_ids,
                "artifact_v1_ids": lineage.artifact_v1_ids,
                "artifact_v2_ids": lineage.artifact_v2_ids,
                "evaluation_v1_ids": lineage.evaluation_v1_ids,
                "evaluation_v2_ids": lineage.evaluation_v2_ids,
                "repair_plan_id": lineage.repair_plan_id,
                "reservation_id": lineage.reservation_id,
            }
        )
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM billing_reservations WHERE production_id = $1", production_id)
            await conn.execute("DELETE FROM credit_transactions WHERE user_id = $1", uuid.UUID(fresh_user))
            await conn.execute("DELETE FROM execution_plans WHERE production_id = $1", production_id)
            await conn.execute("DELETE FROM video_tasks WHERE id = $1", task_id)
            await conn.execute("DELETE FROM productions WHERE id = $1", production_id)
