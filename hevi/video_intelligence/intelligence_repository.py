"""Persistence for intelligence projections.

This repository intentionally contains no provider calls and no queue logic.
It stores references to the canonical HEVI runtime records and enforces
workspace/user fences in every mutation.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from obase.persistence import PgPool


def _uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    return uuid.UUID(str(value)) if value else None


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class IntelligenceRepository:
    def __init__(self, pool: PgPool) -> None:
        self.pool = pool

    async def list_case_summaries(
        self, *, user_id: str, case_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Return owner-scoped reproduction/verdict summaries for the Cases UI.

        The intelligence tables remain projections; this query only joins
        canonical case reproductions and verdicts and never creates a second
        case authority.  The owner predicate is applied to every joined
        projection so a foreign reproduction cannot leak through a case row.
        """
        if not case_ids:
            return {}
        ids = [uuid.UUID(str(item)) for item in case_ids]
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT c.id, COUNT(r.id)::int AS reproduction_count, "
                "(ARRAY_AGG(r.status ORDER BY r.created_at DESC) "
                "FILTER (WHERE r.id IS NOT NULL))[1] AS latest_reproduction_status, "
                "(ARRAY_AGG(r.verdict_id ORDER BY r.created_at DESC) "
                "FILTER (WHERE r.verdict_id IS NOT NULL))[1] AS latest_verdict_id "
                "FROM video_cases c LEFT JOIN case_reproductions r "
                "ON r.case_id=c.id AND r.user_id=c.user_id "
                "WHERE c.user_id=$1 AND c.id = ANY($2::uuid[]) "
                "GROUP BY c.id",
                uuid.UUID(user_id), ids,
            )
        return {
            str(row["id"]): {
                "reproduction_count": int(row["reproduction_count"] or 0),
                "latest_reproduction_status": row["latest_reproduction_status"],
                "latest_verdict_id": str(row["latest_verdict_id"])
                if row["latest_verdict_id"]
                else None,
            }
            for row in rows
        }

    async def list_benchmarks(self, *, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT b.*, p.analysis_revision, p.plan_json, "
                "(SELECT COUNT(*)::int FROM case_benchmark_entries e "
                "WHERE e.benchmark_id=b.id) AS entry_count, "
                "COALESCE((SELECT json_agg(json_build_object( "
                "'id',e.id,'reproduction_id',e.reproduction_id,'provider_id',e.provider_id, "
                "'model_id',e.model_id,'verdict_id',e.verdict_id, "
                "'dimension_comparison',e.dimension_comparison,'cost_amount',e.cost_amount, "
                "'latency_ms',e.latency_ms) ORDER BY e.provider_id,e.model_id) "
                "FROM case_benchmark_entries e WHERE e.benchmark_id=b.id), '[]'::json) AS entries "
                "FROM case_benchmarks b JOIN benchmark_plans p "
                "ON p.id=b.benchmark_plan_id AND p.user_id=b.user_id "
                "WHERE b.user_id=$1 ORDER BY b.created_at DESC LIMIT $2",
                uuid.UUID(user_id), max(1, min(limit, 500)),
            )
        return [dict(row) for row in rows]

    async def get_benchmark(self, benchmark_id: str, *, user_id: str) -> dict[str, Any] | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT b.*, p.analysis_revision, p.plan_json "
                "FROM case_benchmarks b JOIN benchmark_plans p "
                "ON p.id=b.benchmark_plan_id AND p.user_id=b.user_id "
                "WHERE b.id=$1 AND b.user_id=$2",
                uuid.UUID(benchmark_id), uuid.UUID(user_id),
            )
            if row is None:
                return None
            entries = await conn.fetch(
                "SELECT * FROM case_benchmark_entries "
                "WHERE benchmark_id=$1 ORDER BY provider_id,model_id",
                uuid.UUID(benchmark_id),
            )
        result = dict(row)
        result["entries"] = [dict(item) for item in entries]
        return result

    async def list_patterns(self, *, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT p.*, COUNT(e.id)::int AS evidence_count, "
                "COUNT(e.id) FILTER (WHERE e.evidence_type IN "
                "('negative','counter_example'))::int AS counter_evidence_count "
                "FROM video_patterns p LEFT JOIN video_pattern_evidence e "
                "ON e.pattern_id=p.id AND e.user_id=p.user_id "
                "WHERE p.user_id=$1 GROUP BY p.id ORDER BY p.updated_at DESC LIMIT $2",
                uuid.UUID(user_id), max(1, min(limit, 500)),
            )
        return [dict(row) for row in rows]

    async def get_pattern(self, pattern_id: str, *, user_id: str) -> dict[str, Any] | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM video_patterns WHERE id=$1 AND user_id=$2",
                uuid.UUID(pattern_id), uuid.UUID(user_id),
            )
            if row is None:
                return None
            evidence = await conn.fetch(
                "SELECT * FROM video_pattern_evidence "
                "WHERE pattern_id=$1 AND user_id=$2 ORDER BY created_at DESC",
                uuid.UUID(pattern_id), uuid.UUID(user_id),
            )
        result = dict(row)
        result["evidence"] = [dict(item) for item in evidence]
        return result

    async def list_templates(self, *, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT t.*, COUNT(q.id)::int AS qualification_run_count, "
                "MAX(q.completed_at) AS last_qualified_at "
                "FROM prompt_templates t LEFT JOIN template_qualification_runs q "
                "ON q.template_id=t.id AND q.user_id=t.user_id "
                "WHERE t.user_id=$1 GROUP BY t.id ORDER BY t.name,t.version DESC LIMIT $2",
                uuid.UUID(user_id), max(1, min(limit, 500)),
            )
        return [dict(row) for row in rows]

    async def get_template(self, template_id: str, *, user_id: str) -> dict[str, Any] | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM prompt_templates WHERE id=$1 AND user_id=$2",
                uuid.UUID(template_id), uuid.UUID(user_id),
            )
            if row is None:
                return None
            runs = await conn.fetch(
                "SELECT * FROM template_qualification_runs "
                "WHERE template_id=$1 AND user_id=$2 ORDER BY completed_at DESC",
                uuid.UUID(template_id), uuid.UUID(user_id),
            )
        result = dict(row)
        result["qualification_runs"] = [dict(item) for item in runs]
        return result

    async def create_benchmark_plan(
        self, *, user_id: str, workspace_id: str | None, case_id: str,
        analysis_revision: str, plan: dict[str, Any], plan_hash: str,
    ) -> dict[str, Any]:
        plan_id = uuid.uuid4()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO benchmark_plans "
                "(id,workspace_id,user_id,case_id,analysis_revision,plan_json,plan_hash) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7) "
                "ON CONFLICT (user_id,case_id,plan_hash) DO UPDATE SET plan_json=benchmark_plans.plan_json "
                "RETURNING *",
                plan_id, workspace_id, uuid.UUID(user_id), uuid.UUID(case_id),
                analysis_revision, plan, plan_hash,
            )
        if not row:
            raise RuntimeError("BENCHMARK_PLAN_PERSISTENCE_FAILED")
        return dict(row)

    async def create_benchmark(
        self, *, user_id: str, workspace_id: str | None, case_id: str,
        plan_id: str, key: str,
    ) -> dict[str, Any]:
        benchmark_id = uuid.uuid4()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO case_benchmarks "
                "(id,workspace_id,user_id,case_id,benchmark_plan_id,idempotency_key) "
                "VALUES ($1,$2,$3,$4,$5,$6) "
                "ON CONFLICT (user_id,case_id,idempotency_key) DO UPDATE SET id=case_benchmarks.id "
                "RETURNING *",
                benchmark_id, workspace_id, uuid.UUID(user_id), uuid.UUID(case_id),
                uuid.UUID(plan_id), key,
            )
        if not row:
            raise RuntimeError("BENCHMARK_PERSISTENCE_FAILED")
        return dict(row)

    async def benchmark_entry(
        self, *, benchmark_id: str, reproduction_id: str, provider_id: str,
        model_id: str, verdict_id: str | None, dimensions: dict[str, Any],
        cost: float | None, latency_ms: float | None,
    ) -> dict[str, Any]:
        entry_id = uuid.uuid4()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO case_benchmark_entries "
                "(id,benchmark_id,reproduction_id,provider_id,model_id,verdict_id,dimension_comparison,cost_amount,latency_ms) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) "
                "ON CONFLICT (benchmark_id,reproduction_id) DO UPDATE SET dimension_comparison=EXCLUDED.dimension_comparison "
                "RETURNING *",
                entry_id, uuid.UUID(benchmark_id), uuid.UUID(reproduction_id), provider_id, model_id,
                _uuid(verdict_id), dimensions, Decimal(str(cost)) if cost is not None else None, latency_ms,
            )
        if not row:
            raise RuntimeError("BENCHMARK_ENTRY_PERSISTENCE_FAILED")
        return dict(row)

    async def finish_benchmark(
        self, benchmark_id: str, *, user_id: str, status: str,
        provider_count: int, reproduction_count: int, failure_code: str | None = None,
    ) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE case_benchmarks SET status=$1,provider_count=$2,reproduction_count=$3,"
                "failure_code=$4,completed_at=NOW() WHERE id=$5 AND user_id=$6",
                status, provider_count, reproduction_count, failure_code,
                uuid.UUID(benchmark_id), uuid.UUID(user_id),
            )
        return str(result).endswith("1")

    async def create_pattern(
        self, *, user_id: str, workspace_id: str | None, category: str,
        name: str, conditions: dict[str, Any], structure: dict[str, Any],
        expected_effect: str,
    ) -> dict[str, Any]:
        pattern_id = uuid.uuid4()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO video_patterns "
                "(id,workspace_id,user_id,category,name,conditions,structure,expected_effect) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8) "
                "ON CONFLICT (user_id,name) DO UPDATE SET conditions=video_patterns.conditions "
                "RETURNING *",
                pattern_id, workspace_id, uuid.UUID(user_id), category, name,
                conditions, structure, expected_effect,
            )
        if not row:
            raise RuntimeError("PATTERN_PERSISTENCE_FAILED")
        return dict(row)

    async def add_pattern_evidence(
        self, *, pattern_id: str, user_id: str, case_id: str, reproduction_id: str,
        verdict_id: str | None, evidence_type: str, evidence: dict[str, Any],
    ) -> dict[str, Any]:
        evidence_id = uuid.uuid4()
        async with self.pool.acquire() as conn, conn.transaction():
                row = await conn.fetchrow(
                    "INSERT INTO video_pattern_evidence "
                    "(id,pattern_id,user_id,case_id,reproduction_id,verdict_id,evidence_type,evidence_json) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8) "
                    "ON CONFLICT (pattern_id,case_id,reproduction_id,evidence_type) DO UPDATE SET evidence_json=EXCLUDED.evidence_json "
                    "RETURNING *",
                    evidence_id, uuid.UUID(pattern_id), uuid.UUID(user_id), uuid.UUID(case_id),
                    uuid.UUID(reproduction_id), _uuid(verdict_id), evidence_type, evidence,
                )
                await conn.execute(
                    "UPDATE video_patterns p SET positive_evidence_count=s.count_positive,"
                    "negative_evidence_count=s.count_negative,confidence=CASE WHEN s.total=0 THEN 0 "
                    "ELSE s.count_positive::float/s.total END,updated_at=NOW(),lifecycle_status=CASE "
                    "WHEN s.total >= 5 AND s.provider_count >= 2 THEN 'qualified' "
                    "WHEN s.total >= 3 THEN 'observed' ELSE p.lifecycle_status END "
                    "FROM (SELECT pattern_id, count(*) FILTER (WHERE evidence_type='positive') AS count_positive, "
                    "count(*) FILTER (WHERE evidence_type IN ('negative','counter_example')) AS count_negative, "
                    "count(*) AS total, count(DISTINCT reproduction_id) AS reproduction_count, "
                    "count(DISTINCT r.provider_id) AS provider_count FROM video_pattern_evidence e "
                    "LEFT JOIN case_reproductions r ON r.id=e.reproduction_id WHERE pattern_id=$1 GROUP BY pattern_id) s "
                    "WHERE p.id=s.pattern_id AND p.user_id=$2",
                    uuid.UUID(pattern_id), uuid.UUID(user_id),
                )
        if not row:
            raise RuntimeError("PATTERN_EVIDENCE_PERSISTENCE_FAILED")
        return dict(row)

    async def promote_pattern(self, pattern_id: str, *, user_id: str) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE video_patterns SET lifecycle_status='promoted',updated_at=NOW() "
                "WHERE id=$1 AND user_id=$2 AND lifecycle_status='qualified'",
                uuid.UUID(pattern_id), uuid.UUID(user_id),
            )
        return str(result).endswith("1")

    async def create_template_revision(
        self, *, user_id: str, workspace_id: str | None, name: str, version: int,
        required_slots: list[str], optional_slots: list[str], structure: dict[str, Any],
        constraints: list[str], supported_modes: list[str], source_pattern_ids: list[str],
    ) -> dict[str, Any]:
        template_id = uuid.uuid4()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO prompt_templates "
                "(id,workspace_id,user_id,name,version,required_slots,optional_slots,structure,constraints,supported_modes,source_pattern_ids) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING *",
                template_id, workspace_id, uuid.UUID(user_id), name, version,
                required_slots, optional_slots, structure, constraints, supported_modes, source_pattern_ids,
            )
        if not row:
            raise RuntimeError("TEMPLATE_PERSISTENCE_FAILED")
        return dict(row)

    async def qualify_template(
        self, *, template_id: str, user_id: str, status: str,
        case_ids: list[str], reproduction_ids: list[str], baseline_revision: str | None,
        dimension_deltas: dict[str, Any], key: str,
    ) -> dict[str, Any]:
        run_id = uuid.uuid4()
        async with self.pool.acquire() as conn:
            requested = [uuid.UUID(str(item)) for item in reproduction_ids]
            if requested:
                valid = await conn.fetchval(
                    "SELECT count(*) FROM case_reproductions WHERE user_id=$1 "
                    "AND id = ANY($2::uuid[]) AND status='succeeded' AND verdict_id IS NOT NULL",
                    uuid.UUID(user_id), requested,
                )
                if int(valid or 0) != len(requested):
                    status = "failed"
            if status == "qualified":
                await conn.execute(
                    "UPDATE prompt_templates SET qualification_status='qualified' "
                    "WHERE id=$1 AND user_id=$2 AND qualification_status='candidate'",
                    uuid.UUID(template_id), uuid.UUID(user_id),
                )
            row = await conn.fetchrow(
                "INSERT INTO template_qualification_runs "
                "(id,template_id,user_id,status,case_ids,reproduction_ids,baseline_revision,dimension_deltas,idempotency_key,completed_at) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,NOW()) "
                "ON CONFLICT (user_id,template_id,idempotency_key) DO UPDATE SET status=EXCLUDED.status "
                "RETURNING *",
                run_id, uuid.UUID(template_id), uuid.UUID(user_id), status,
                [str(x) for x in case_ids], [str(x) for x in reproduction_ids], baseline_revision,
                dimension_deltas, key,
            )
        if not row:
            raise RuntimeError("TEMPLATE_QUALIFICATION_PERSISTENCE_FAILED")
        return dict(row)

    async def promote_template(self, template_id: str, *, user_id: str) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE prompt_templates SET qualification_status='promoted' WHERE id=$1 AND user_id=$2 "
                "AND qualification_status='qualified'",
                uuid.UUID(template_id), uuid.UUID(user_id),
            )
        return str(result).endswith("1")

    async def write_learning_event(
        self, *, user_id: str, workspace_id: str | None, payload: dict[str, Any]
    ) -> dict[str, Any]:
        event_id = uuid.uuid4()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO production_learning_events "
                "(id,workspace_id,user_id,production_id,shot_id,provider_id,model_id,model_version,template_id,template_revision,pattern_ids,prompt_hash,generation_mode,generation_cost,latency_ms,retake_count,initial_verdict_id,final_verdict_id,final_status,idempotency_key) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20) "
                "ON CONFLICT (user_id,production_id,shot_id,idempotency_key) DO UPDATE SET final_status=production_learning_events.final_status "
                "RETURNING *",
                event_id, workspace_id, uuid.UUID(user_id), payload["production_id"], payload["shot_id"],
                payload["provider_id"], payload["model_id"], payload.get("model_version"),
                _uuid(payload.get("template_id")), payload.get("template_revision"), payload.get("pattern_ids", []),
                payload.get("prompt_hash"), payload.get("generation_mode", "unknown"),
                Decimal(str(payload["generation_cost"])) if payload.get("generation_cost") is not None else None,
                payload.get("latency_ms"), payload.get("retake_count", 0), _uuid(payload.get("initial_verdict_id")),
                _uuid(payload.get("final_verdict_id")), payload["final_status"], payload["idempotency_key"],
            )
        if not row:
            raise RuntimeError("LEARNING_EVENT_PERSISTENCE_FAILED")
        return dict(row)

    async def attach_learning_verdict(
        self, *, event_id: str, user_id: str, verdict_id: str
    ) -> bool:
        """Attach a verdict produced by the canonical production evaluator.

        Production completion is durable before the learning projection is
        written.  This owner-scoped, idempotent link lets a post-completion
        verdict stage finish the same event without creating another event or
        another scoring authority.
        """
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE production_learning_events SET final_verdict_id=$1 "
                "WHERE id=$2 AND user_id=$3 AND final_verdict_id IS NULL",
                uuid.UUID(verdict_id), uuid.UUID(event_id), uuid.UUID(user_id),
            )
        return str(result).endswith("1")

    async def write_retake_record(
        self, *, user_id: str, workspace_id: str | None, payload: dict[str, Any]
    ) -> dict[str, Any]:
        changed = [payload.get(name, False) for name in (
            "changed_prompt", "changed_provider", "changed_reference", "changed_duration", "changed_camera",
        )]
        record_id = uuid.uuid4()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO retake_learning_records "
                "(id,workspace_id,user_id,production_id,shot_id,failure_reason_codes,retake_level,retake_strategy,changed_prompt,changed_provider,changed_reference,changed_duration,changed_camera,before_verdict_id,after_verdict_id,cost_delta,latency_delta,outcome,multi_variable_retake) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19) RETURNING *",
                record_id, workspace_id, uuid.UUID(user_id), payload["production_id"], payload["shot_id"],
                payload.get("failure_reason_codes", []), payload["retake_level"], payload["retake_strategy"],
                *changed, _uuid(payload.get("before_verdict_id")), _uuid(payload.get("after_verdict_id")),
                payload.get("cost_delta"), payload.get("latency_delta"), payload["outcome"], sum(bool(x) for x in changed) > 1,
            )
        if not row:
            raise RuntimeError("RETAKE_LEARNING_PERSISTENCE_FAILED")
        return dict(row)

    async def refresh_observed_stats(self, *, user_id: str) -> int:
        """Refresh only from persisted reproductions/events, never declarations."""
        async with self.pool.acquire() as conn:
            reproduction_rows = await conn.fetch(
                "SELECT r.provider_id,r.model_id,COALESCE(r.model_version,'') AS model_version,"
                "r.generation_mode,r.status,r.cost_amount,r.latency_ms,v.checks_json "
                "FROM case_reproductions r LEFT JOIN shot_verdict v ON v.id=r.verdict_id "
                "WHERE r.user_id=$1",
                uuid.UUID(user_id),
            )
            learning_rows = await conn.fetch(
                "SELECT e.provider_id,e.model_id,COALESCE(e.model_version,'') AS model_version,"
                "e.generation_mode,e.final_status AS status,e.generation_cost AS cost_amount,"
                "e.latency_ms,v.checks_json "
                "FROM production_learning_events e "
                "LEFT JOIN shot_verdict v ON v.id=e.final_verdict_id "
                "WHERE e.user_id=$1",
                uuid.UUID(user_id),
            )
            rows = [*reproduction_rows, *learning_rows]
            buckets: dict[tuple[str, str, str, str], list[Any]] = {}
            for row in rows:
                key = (row["provider_id"], row["model_id"], row["model_version"], row["generation_mode"])
                buckets.setdefault(key, []).append(row)
            for key, bucket in buckets.items():
                costs = sorted(float(item["cost_amount"]) for item in bucket if item["cost_amount"] is not None)
                latencies = sorted(float(item["latency_ms"]) for item in bucket if item["latency_ms"] is not None)
                successes = sum(item["status"] == "succeeded" for item in bucket)
                def median(values: list[float]) -> float | None:
                    if not values:
                        return None
                    mid = len(values) // 2
                    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2
                def failure_rate(dimension: str, current_bucket: list[Any] = bucket) -> float:
                    observed = 0
                    failed = 0
                    for item in current_bucket:
                        checks = item["checks_json"] or {}
                        dimensions = checks.get("case_dimensions", {}) if isinstance(checks, dict) else {}
                        status = (dimensions.get(dimension) or {}).get("status")
                        if status in {"PASS", "FAIL", "WARN"}:
                            observed += 1
                            failed += status == "FAIL"
                    return failed / observed if observed else 0.0
                provider_id, model_id, model_version, generation_mode = key
                await conn.execute(
                    "INSERT INTO provider_observed_stats "
                    "(id,user_id,provider_id,model_id,model_version,generation_mode,sample_count,success_count,median_cost,median_latency) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) "
                    "ON CONFLICT (user_id,provider_id,model_id,model_version,shot_type,style,generation_mode) DO UPDATE SET sample_count=EXCLUDED.sample_count,success_count=EXCLUDED.success_count,median_cost=EXCLUDED.median_cost,median_latency=EXCLUDED.median_latency,last_observed_at=NOW()",
                    uuid.uuid4(), uuid.UUID(user_id), provider_id, model_id, model_version,
                    generation_mode, len(bucket), successes, median(costs), median(latencies),
                )
                await conn.execute(
                    "UPDATE provider_observed_stats SET identity_failure_rate=$1,action_failure_rate=$2,"
                    "continuity_failure_rate=$3,style_failure_rate=$4,retake_rate=COALESCE((SELECT count(*)::float/NULLIF($5,0) FROM retake_learning_records WHERE user_id=$6),0),last_observed_at=NOW() "
                    "WHERE user_id=$6 AND provider_id=$7 AND model_id=$8 AND model_version=$9 "
                    "AND shot_type='unknown' AND style='unknown' AND generation_mode=$10",
                    failure_rate("identity_consistency"), failure_rate("action_completion"),
                    failure_rate("temporal_continuity"), failure_rate("style_adherence"), len(bucket),
                    uuid.UUID(user_id), provider_id, model_id, model_version, generation_mode,
                )
        return len(buckets)


def pattern_plan_hash(plan: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


__all__ = ["IntelligenceRepository", "pattern_plan_hash"]
