#!/usr/bin/env python3
"""Run one real cross-model benchmark end-to-end (hyperframes + manim).

Creates a durable case_benchmark through IntelligenceRepository + TaskService
(exactly the API path), claims the parent task under our lease, and executes
run_benchmark_composition which:
  - submits child case_reproductions idempotently
  - runs them nested under worker_id=benchmark-composition
  - fans in after all children terminal
  - persists BenchmarkEntry rows + pattern evidence

Free local only — never spends owner budget. Writes evidence JSON.

Exit 0 only when REAL gates pass:
  CHILD_REPRODUCTIONS_SUBMITTED=YES, TERMINAL=YES,
  BENCHMARK_AGGREGATED=YES, entry_count>=2, provider_count>=2,
  pattern evidence written (or classified correctly when all children fail
  before verdict — still requires >=2 entries for CROSS_MODEL_RUNTIME).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

TERMINAL_TASK = frozenset({"completed", "failed", "interrupted", "canceled", "cancelled"})


def _seed_user() -> str:
    return "7914fd9b-2bf6-403e-8384-fb4c29e362e0"


async def _pick_case(pool: Any, user_id: str) -> tuple[str, str]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT c.id::text AS case_id, a.id::text AS analysis_id "
            "FROM video_cases c "
            "JOIN video_case_analyses a ON a.case_id=c.id AND a.status='succeeded' "
            "WHERE c.analysis_status='completed' AND c.user_id=$1 "
            "ORDER BY c.created_at LIMIT 1",
            uuid.UUID(user_id),
        )
        if row is None:
            raise RuntimeError("NO_CASE_WITH_SUCCEEDED_ANALYSIS")
        return str(row["case_id"]), str(row["analysis_id"])


async def run_benchmark(*, timeout_s: float, workspace_id: str, key: str) -> dict[str, Any]:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")

    from hevi.db.pg_pool import get_hevi_pg_pool
    from hevi.production.composition import configure_application_adapters
    from hevi.providers.registry import register_all_providers
    from hevi.tasks.repository import TaskRepository
    from hevi.tasks.task_service import TaskService
    from hevi.video_intelligence.case_analysis import CaseAnalysis
    from hevi.video_intelligence.case_repository import CaseRepository
    from hevi.video_intelligence.intelligence_repository import (
        IntelligenceRepository,
        pattern_plan_hash,
    )
    from hevi.video_intelligence.intelligence_runtime import BENCHMARK_DIMENSIONS
    from hevi.video_intelligence.runtime_repository import CaseAnalysisRepository

    register_all_providers()
    configure_application_adapters()
    pool = await get_hevi_pg_pool()
    try:
        user_id = _seed_user()
        case_id, analysis_id = await _pick_case(pool, user_id)
        case = await CaseRepository(pool).get_owned(case_id, user_id=user_id)
        if case is None:
            raise RuntimeError("CASE_NOT_FOUND")
        analysis_row = await CaseAnalysisRepository(pool).get_owned(
            analysis_id, user_id=user_id
        )
        if not analysis_row or not analysis_row.get("analysis_json"):
            raise RuntimeError("ANALYSIS_JSON_MISSING")
        analysis = CaseAnalysis.model_validate(analysis_row["analysis_json"])

        plan: dict[str, Any] = {
            "case_id": case_id,
            "analysis_revision": str(analysis.analyzer_version),
            "generation_mode": "exact_structure",
            "compiled_semantic_intent": case.original_prompt or "",
            "shot_structure": [item.model_dump(mode="json") for item in analysis.case_shots],
            "reference_bindings": [
                item.model_dump(mode="json") for item in analysis.reference_bindings
            ],
            "duration_ms": case.duration_ms,
            "aspect_ratio": case.aspect_ratio,
            "acceptance_dimensions": list(BENCHMARK_DIMENSIONS),
        }
        plan_hash = pattern_plan_hash(plan)
        plan["plan_hash"] = plan_hash

        ir = IntelligenceRepository(pool)
        plan_row = await ir.create_benchmark_plan(
            user_id=user_id,
            workspace_id=workspace_id,
            case_id=case_id,
            analysis_revision=str(plan["analysis_revision"]),
            plan=plan,
            plan_hash=plan_hash,
        )
        benchmark = await ir.create_benchmark(
            user_id=user_id,
            workspace_id=workspace_id,
            case_id=case_id,
            plan_id=str(plan_row["id"]),
            key=key,
        )
        benchmark_id = str(benchmark["id"])

        task_repo = TaskRepository(pool)
        service = TaskService(task_repo)
        task_key = f"case-benchmark:{key}"
        existing_task = await task_repo.get_task_by_idempotency_key(user_id, task_key)
        if existing_task:
            task = dict(existing_task)
            task_id = str(task["id"])
        else:
            task = await service.create_task(
                topic=f"case-benchmark:{case_id}",
                duration_archetype="1-5min",
                video_provider="benchmark",
                audio_provider="vibevoice",
                user_id=user_id,
                idempotency_key=task_key,
                production_source="case_benchmark",
                case_id=case_id,
                analysis_id=analysis_id,
                benchmark_id=benchmark_id,
                benchmark_providers=["hyperframes", "manim"],
                workspace_id=workspace_id,
            )
            task_id = str(task["id"])
            task = await service.submit_task(uuid.UUID(task_id))

        status = str(task.get("status") or "")
        if status in TERMINAL_TASK:
            finished = task
        else:
            claimed = await task_repo.claim_task(
                uuid.UUID(task_id), worker_id="cross-model-benchmark-e2e"
            )
            if claimed is None:
                # Another worker owns it — poll until terminal.
                finished = await _poll_terminal(task_repo, task_id, timeout_s=timeout_s)
            else:
                task = dict(claimed)
                finished = await service.run_task(uuid.UUID(task_id))

        # Reload durable state.
        async with pool.acquire() as conn:
            b_row = await conn.fetchrow(
                "SELECT * FROM case_benchmarks WHERE id=$1",
                uuid.UUID(benchmark_id),
            )
            entries = await conn.fetch(
                "SELECT * FROM case_benchmark_entries WHERE benchmark_id=$1",
                uuid.UUID(benchmark_id),
            )
            evidence = await conn.fetch(
                "SELECT id::text, pattern_id::text, evidence_type, reproduction_id::text "
                "FROM video_pattern_evidence WHERE (evidence_json->>'benchmark_id')=$1",
                benchmark_id,
            )
            patterns = await conn.fetch(
                "SELECT p.id::text, p.name, count(e.id)::int AS evidence_count "
                "FROM video_patterns p "
                "LEFT JOIN video_pattern_evidence e ON e.pattern_id=p.id "
                "WHERE p.name LIKE 'benchmark-plan:%' "
                "GROUP BY p.id, p.name"
            )
            children = await conn.fetch(
                "SELECT provider_id, status, id::text, verdict_id::text "
                "FROM case_reproductions "
                "WHERE idempotency_key LIKE $1",
                f"benchmark:{benchmark_id}:%",
            )

        b = dict(b_row) if b_row else {}
        entry_rows = [dict(r) for r in entries]
        evidence_rows = [dict(r) for r in evidence]
        child_rows = [dict(r) for r in children]
        child_providers = sorted({str(c["provider_id"]) for c in child_rows})
        child_terminal = all(
            str(c["status"]) in {"succeeded", "failed", "blocked"} for c in child_rows
        ) and len(child_rows) >= 2

        cfg = dict(finished.get("config_json") or {})
        report = {
            "benchmark_id": benchmark_id,
            "task_id": task_id,
            "task_status": str(finished.get("status") or ""),
            "task_error": finished.get("error"),
            "case_id": case_id,
            "analysis_id": analysis_id,
            "plan_hash": plan_hash,
            "plan_id": str(plan_row["id"]),
            "benchmark_providers": ["hyperframes", "manim"],
            "benchmark": {
                "status": str(b.get("status") or ""),
                "failure_code": b.get("failure_code"),
                "provider_count": int(b.get("provider_count") or 0),
                "reproduction_count": int(b.get("reproduction_count") or 0),
            },
            "children": child_rows,
            "child_providers": child_providers,
            "child_count": len(child_rows),
            "child_terminal": child_terminal,
            "entries": [
                {
                    "id": str(e["id"]),
                    "reproduction_id": str(e["reproduction_id"]),
                    "provider_id": str(e["provider_id"]),
                    "verdict_id": str(e["verdict_id"]),
                    "cost": e.get("cost"),
                    "latency_ms": e.get("latency_ms"),
                }
                for e in entry_rows
            ],
            "entry_count": len(entry_rows),
            "evidence": evidence_rows,
            "evidence_count": len(evidence_rows),
            "patterns": [dict(p) for p in patterns],
            "config": {
                "child_reproductions_submitted": cfg.get("child_reproductions_submitted"),
                "child_reproductions_terminal": cfg.get("child_reproductions_terminal"),
                "benchmark_aggregated": cfg.get("benchmark_aggregated"),
                "benchmark_entry_count": cfg.get("benchmark_entry_count"),
                "failure_code": cfg.get("failure_code"),
                "child_statuses": cfg.get("child_statuses"),
            },
        }

        # Gates
        submitted = report["config"]["child_reproductions_submitted"] is True
        terminal = report["config"]["child_reproductions_terminal"] is True
        aggregated = report["config"]["benchmark_aggregated"] is True
        entry_count = report["entry_count"]
        real_provider_count = len(child_providers)
        status_ok = str(b.get("status") or "") == "succeeded"
        gates = {
            "CHILD_REPRODUCTIONS_SUBMITTED": submitted,
            "CHILD_REPRODUCTIONS_TERMINAL": terminal,
            "BENCHMARK_AGGREGATED": aggregated,
            "REAL_BENCHMARK_ENTRY_COUNT_GE_2": entry_count >= 2,
            "REAL_BENCHMARK_PROVIDER_COUNT_GE_2": real_provider_count >= 2,
            "BENCHMARK_STATUS_SUCCEEDED": status_ok,
            "TASK_COMPLETED": str(finished.get("status") or "") == "completed",
        }
        report["gates"] = gates
        report["cross_model_runtime_qualified"] = all(gates.values())
        # AUTO_PATTERN_PROMOTION stays 0 — we never promote.
        report["auto_pattern_promotion"] = 0
        return report
    finally:
        await pool.close()


async def _poll_terminal(repo: Any, task_id: str, *, timeout_s: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = dict(await repo.get_task(uuid.UUID(task_id)) or {})
        if str(last.get("status") or "") in TERMINAL_TASK:
            return last
        await asyncio.sleep(1.0)
    return last


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout-s", type=float, default=600.0)
    parser.add_argument("--workspace", default="closure-smoke")
    parser.add_argument("--key", default=None)
    parser.add_argument(
        "--json",
        type=Path,
        default=Path("artifacts/qualification/cross-model-benchmark-runtime.json"),
    )
    args = parser.parse_args()
    key = args.key or f"cross-model-runtime-{int(time.time())}"
    report = asyncio.run(
        run_benchmark(timeout_s=args.timeout_s, workspace_id=args.workspace, key=key)
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    ok = bool(report.get("cross_model_runtime_qualified"))
    print(f"cross_model_runtime_qualified={'PASS' if ok else 'FAIL'}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
