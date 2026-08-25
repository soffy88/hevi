"""Durable repair-run projection for dashboard and postmortem queries."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from obase.persistence import PgPool

from .evaluation import QualityEvaluation
from .gate_policy import GatePolicy
from .repair_controller import RepairController, RepairDecision
from .taxonomy import severity_for


class RepairRepository:
    def __init__(self, pool: PgPool) -> None:
        self.pool = pool

    async def save_run(
        self,
        *,
        task_id: uuid.UUID,
        production_id: uuid.UUID | None,
        policy: GatePolicy,
        controller: RepairController,
        decision: RepairDecision,
        evaluation: QualityEvaluation | None = None,
        revision_id: uuid.UUID | None = None,
        attempt_id: str | None = None,
        evidence_artifact_id: str | None = None,
    ) -> uuid.UUID:
        run_id = uuid.uuid5(uuid.NAMESPACE_URL, f"hevi:repair-run:{task_id}")
        current = controller.rounds[-1] if controller.rounds else None
        status = "passed" if decision.stop_reason == "gates_passed" else (
            "running" if decision.should_repair else "stopped"
        )
        now = datetime.now(UTC).replace(tzinfo=None)
        async with self.pool.acquire() as conn, conn.transaction():
            evaluation_id: uuid.UUID | None = None
            violation_hash = ""
            if evaluation is not None:
                import hashlib
                import json

                evaluation_id = uuid.uuid4()
                violations = [item for item in evaluation.evidence if not item.passed]
                violation_hash = hashlib.sha256(
                    json.dumps(
                        [
                            {"code": str(item.code), "scope": item.scope}
                            for item in violations
                        ],
                        sort_keys=True,
                    ).encode()
                ).hexdigest()
                await conn.execute(
                    """
                    INSERT INTO evaluations
                        (id, production_id, revision_id, task_id, attempt_id,
                         scope, evaluator, status, passed, score,
                         residual_severity, residual_count, evidence_artifact_id,
                         details_json, created_at)
                    VALUES ($1, $2, $3, $4, $5, 'production', 'hevi.quality',
                            'completed', $6, $7, $8, $9, $10, $11, $12)
                    """,
                    evaluation_id,
                    production_id,
                    revision_id,
                    task_id,
                    attempt_id,
                    evaluation.passed,
                    evaluation.score,
                    evaluation.residual_severity,
                    evaluation.residual_count,
                    evidence_artifact_id,
                    evaluation.model_dump(mode="json"),
                    now,
                )
                for item in violations:
                    evidence = dict(item.evidence)
                    await conn.execute(
                        """
                        INSERT INTO violations
                            (id, evaluation_id, taxonomy, severity, message,
                             repairable, scope, details_json, created_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                        """,
                        uuid.uuid4(),
                        evaluation_id,
                        str(item.code),
                        float(item.severity or severity_for(item.code)),
                        str(evidence.get("message") or evidence.get("detail") or item.code),
                        any(action.reason == item.code for action in decision.actions),
                        item.scope,
                        evidence,
                        now,
                    )
            await conn.execute(
                """
                INSERT INTO repair_runs
                    (id, task_id, production_id, policy_version, profile, status,
                     max_attempts, attempts_used, budget_limit_usd, spent_usd,
                     residual_severity, residual_count, stop_reason,
                     snapshot_json, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $15)
                ON CONFLICT (task_id) DO UPDATE SET
                    production_id = EXCLUDED.production_id,
                    policy_version = EXCLUDED.policy_version,
                    profile = EXCLUDED.profile,
                    status = EXCLUDED.status,
                    max_attempts = EXCLUDED.max_attempts,
                    attempts_used = EXCLUDED.attempts_used,
                    budget_limit_usd = EXCLUDED.budget_limit_usd,
                    spent_usd = EXCLUDED.spent_usd,
                    residual_severity = EXCLUDED.residual_severity,
                    residual_count = EXCLUDED.residual_count,
                    stop_reason = EXCLUDED.stop_reason,
                    snapshot_json = EXCLUDED.snapshot_json,
                    updated_at = EXCLUDED.updated_at
                """,
                run_id,
                task_id,
                production_id,
                1,
                policy.profile,
                status,
                controller.budget.max_attempts,
                max(0, len(controller.rounds) - 1),
                controller.budget.max_cost_usd,
                controller.spent_usd,
                current.residual_severity if current else 0.0,
                current.residual_count if current else 0,
                decision.stop_reason,
                {
                    "policy": policy.model_dump(mode="json"),
                    "controller": controller.snapshot(),
                    "decision": decision.model_dump(mode="json"),
                },
                now,
            )
            if evaluation_id is not None:
                for action in decision.actions:
                    await conn.execute(
                        """
                        INSERT INTO repair_plans
                            (id, production_id, task_id, evaluation_id,
                             violation_set_hash, action, scope, expected_gain,
                             max_cost_usd, status, decision_json, created_at, updated_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $12)
                        """,
                        uuid.uuid4(),
                        production_id,
                        task_id,
                        evaluation_id,
                        violation_hash,
                        action.kind,
                        action.scope,
                        action.expected_gain,
                        controller.budget.max_cost_usd,
                        "planned" if decision.should_repair else "stopped",
                        decision.model_dump(mode="json"),
                        now,
                    )
            for action in decision.actions:
                await conn.execute(
                    """
                    INSERT INTO repair_actions
                        (id, repair_run_id, attempt, scope, failure_code,
                         action, expected_gain, status, details_json, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, 'planned', $8, $9)
                    """,
                    uuid.uuid4(),
                    run_id,
                    max(0, len(controller.rounds) - 1),
                    action.scope,
                    action.reason.value,
                    action.kind,
                    action.expected_gain,
                    {},
                    now,
                )
        return run_id


__all__ = ["RepairRepository"]
