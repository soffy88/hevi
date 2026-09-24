"""Composition layer for cross-model benchmark child reproductions.

The benchmark adapter never calls a provider.  It freezes the plan, then this
module submits canonical ``case_reproduction`` tasks through TaskService,
persists the child relationship, waits for terminal fan-in, writes
BenchmarkEntry rows, and extracts pattern evidence from real verdicts.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Protocol

from obase.persistence import PgPool

from .intelligence_models import EvidenceType
from .intelligence_repository import IntelligenceRepository
from .patterns import PatternCategory
from .runtime_repository import CaseReproductionRepository

TERMINAL_REPRODUCTION_STATUSES = frozenset({"succeeded", "failed", "blocked"})
TERMINAL_TASK_STATUSES = frozenset({"completed", "failed", "interrupted", "canceled", "cancelled"})
DEFAULT_POLL_TIMEOUT_S = 600.0
DEFAULT_POLL_INTERVAL_S = 1.0
WORKER_ID = "benchmark-composition"

# Free-local generation budget matching the existing corpus/Track 4 runs.
_HYPERFRAMES_PARAMS: dict[str, Any] = {"width": 320, "height": 240, "duration_s": 1.0}
_MANIM_PARAMS: dict[str, Any] = {
    "mode": "code_scene", "width": 320, "height": 240, "duration_s": 1.0,
}
_PROVIDER_PARAMS: dict[str, dict[str, Any]] = {
    "hyperframes": dict(_HYPERFRAMES_PARAMS),
    "manim": dict(_MANIM_PARAMS),
}


def child_idempotency_key(benchmark_id: str, provider_id: str, plan_revision: str) -> str:
    """Canonical identity of one child: benchmark + provider + frozen plan revision."""
    return f"benchmark:{benchmark_id}:{provider_id}:{plan_revision}"


def child_task_idempotency_key(benchmark_id: str, provider_id: str, plan_revision: str) -> str:
    return f"case-benchmark-child:{benchmark_id}:{provider_id}:{plan_revision}"


def provider_generation_parameters(provider_id: str) -> dict[str, Any]:
    return dict(_PROVIDER_PARAMS.get(provider_id, _HYPERFRAMES_PARAMS))


def is_terminal_reproduction(status: str | None) -> bool:
    return str(status or "") in TERMINAL_REPRODUCTION_STATUSES


def build_dimension_comparison(
    *,
    plan: dict[str, Any],
    provider_id: str,
    model_id: str,
    verdict: dict[str, Any] | None,
    cost: float | None,
    latency_ms: float | None,
) -> dict[str, Any]:
    """Frozen-plan dimension comparison for one provider. Never picks a winner."""
    acceptance = [str(item) for item in (plan.get("acceptance_dimensions") or [])]
    verdict_dimensions = dict((verdict or {}).get("dimensions") or {})
    dimensions: dict[str, Any] = {}
    for name in acceptance:
        observed = dict(verdict_dimensions.get(name) or {})
        dimensions[name] = {
            "status": str(observed.get("status") or "NOT_OBSERVED"),
            "score": observed.get("score"),
            "reason_codes": list(observed.get("reason_codes") or []),
        }
        if name not in verdict_dimensions and name in {"cost", "latency"}:
            raw = cost if name == "cost" else latency_ms
            dimensions[name] = {
                "status": "PASS" if raw is not None else "NOT_OBSERVED",
                "score": float(raw) if raw is not None else None,
                "reason_codes": [],
            }
    return {
        "frozen_plan": {
            "case_id": plan.get("case_id"),
            "analysis_revision": plan.get("analysis_revision"),
            "plan_hash": plan.get("plan_hash"),
            "generation_mode": plan.get("generation_mode"),
            "duration_ms": plan.get("duration_ms"),
            "aspect_ratio": plan.get("aspect_ratio"),
        },
        "provider_id": provider_id,
        "model_id": model_id,
        "dimensions": dimensions,
        "cost": cost,
        "latency_ms": latency_ms,
        "winner": None,
    }


def classify_evidence_type(
    *, verdict_passed: bool, any_other_passed: bool
) -> str:
    """POSITIVE / NEGATIVE / COUNTER_EXAMPLE from real verdict outcomes."""
    if verdict_passed:
        return EvidenceType.POSITIVE.value
    if any_other_passed:
        return EvidenceType.COUNTER_EXAMPLE.value
    return EvidenceType.NEGATIVE.value


class BenchmarkPorts(Protocol):
    async def ensure_children(self) -> list[dict[str, Any]]: ...
    async def run_children(self, children: list[dict[str, Any]]) -> list[dict[str, Any]]: ...
    async def load_children(self, children: list[dict[str, Any]]) -> list[dict[str, Any]]: ...
    async def aggregate(self, children: list[dict[str, Any]]) -> dict[str, Any]: ...


class _LivePorts:
    def __init__(
        self,
        *,
        pool: PgPool,
        task: dict[str, Any],
        config: dict[str, Any],
        user_id: str,
        case_id: str,
        analysis_id: str,
        benchmark_id: str,
        plan: dict[str, Any],
        plan_hash: str,
        providers: list[str],
        workspace_id: str | None,
    ) -> None:
        self.pool = pool
        self.task = task
        self.config = config
        self.user_id = user_id
        self.case_id = case_id
        self.analysis_id = analysis_id
        self.benchmark_id = benchmark_id
        self.plan = plan
        self.plan_hash = plan_hash
        self.plan_revision = plan_hash
        self.providers = providers
        self.workspace_id = workspace_id

    async def ensure_children(self) -> list[dict[str, Any]]:
        from hevi.tasks.repository import TaskRepository
        from hevi.tasks.task_service import TaskService

        case = await _load_owned_case(self.pool, self.case_id, self.user_id)
        if case is None:
            raise RuntimeError("CASE_NOT_FOUND_OR_NOT_OWNED")
        repro_repo = CaseReproductionRepository(self.pool)
        task_repo = TaskRepository(self.pool)
        service = TaskService(task_repo)
        intelligence = IntelligenceRepository(self.pool)
        await intelligence.mark_benchmark_running(
            self.benchmark_id, user_id=self.user_id,
            provider_count=len(self.providers), reproduction_count=0,
        )
        children: list[dict[str, Any]] = []
        for provider in self.providers:
            key = child_idempotency_key(self.benchmark_id, provider, self.plan_revision)
            existing = await repro_repo.find_idempotent(
                case_id=self.case_id, user_id=self.user_id, key=key
            )
            if existing is not None:
                child = await self._ensure_existing_child(
                    service, task_repo, repro_repo, provider, key, case, existing
                )
                children.append(child)
                continue
            task_row = await self._create_child_task(service, provider)
            reproduction = await repro_repo.create_pending(
                case_id=self.case_id,
                user_id=self.user_id,
                workspace_id=self.workspace_id,
                key=key,
                provider_id=provider,
                model_id=provider,
                model_version=None,
                generation_mode=str(self.plan.get("generation_mode") or "exact_structure"),
                compiled_prompt=str(case.get("original_prompt") or ""),
                reference_bindings=list(self.plan.get("reference_bindings") or []),
                parameters=provider_generation_parameters(provider),
                task_id=str(task_row["id"]),
            )
            await self._patch_child_task_config(task_repo, task_row, str(reproduction["id"]), provider)
            await service.submit_task(uuid.UUID(str(task_row["id"])))
            children.append({
                "provider_id": provider,
                "model_id": provider,
                "reproduction_id": str(reproduction["id"]),
                "task_id": str(task_row["id"]),
                "reproduction": reproduction,
                "reused": False,
            })
        return children

    async def _ensure_existing_child(
        self,
        service: Any,
        task_repo: Any,
        repro_repo: Any,
        provider: str,
        key: str,
        case: dict[str, Any],
        existing: dict[str, Any],
    ) -> dict[str, Any]:
        task_id_raw = str(existing.get("task_id") or "")
        task_row = await task_repo.get_task(uuid.UUID(task_id_raw)) if task_id_raw else None
        if task_row is None:
            task_row = await self._create_child_task(service, provider)
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "UPDATE case_reproductions SET task_id=$1 WHERE id=$2 AND user_id=$3",
                    uuid.UUID(str(task_row["id"])),
                    uuid.UUID(str(existing["id"])),
                    uuid.UUID(self.user_id),
                )
            existing = dict(existing)
            existing["task_id"] = task_row["id"]
        await self._patch_child_task_config(
            task_repo, task_row, str(existing["id"]), provider
        )
        return {
            "provider_id": provider,
            "model_id": provider,
            "reproduction_id": str(existing["id"]),
            "task_id": str(task_row["id"]),
            "reproduction": existing,
            "reused": True,
        }

    async def _create_child_task(self, service: Any, provider: str) -> dict[str, Any]:
        task_key = child_task_idempotency_key(
            self.benchmark_id, provider, self.plan_revision
        )
        task = await service.create_task(
            topic=f"case-reproduction:{self.case_id}",
            duration_archetype="1-5min",
            video_provider=provider,
            audio_provider="vibevoice",
            user_id=self.user_id,
            idempotency_key=task_key,
            production_source="case_reproduction",
            case_id=self.case_id,
            analysis_id=self.analysis_id,
            provider_id=provider,
            model_id=provider,
            benchmark_id=self.benchmark_id,
        )
        return dict(task)

    async def _patch_child_task_config(
        self, task_repo: Any, task_row: dict[str, Any],
        reproduction_id: str, provider: str,
    ) -> None:
        config = dict(task_row.get("config_json") or {})
        config.update({
            "reproduction_id": reproduction_id,
            "provider_id": provider,
            "model_id": provider,
            "benchmark_id": self.benchmark_id,
            "analysis_id": self.analysis_id,
            "plan_hash": self.plan_hash,
        })
        await task_repo.update_task(task_row["id"], {"config_json": config})
        status = str(task_row.get("status") or "")
        if status in {"pending", "queued"}:
            from hevi.tasks.repository import TaskRepository
            from hevi.tasks.task_service import TaskService

            service = TaskService(
                task_repo if isinstance(task_repo, TaskRepository) else TaskRepository(self.pool)
            )
            await service.submit_task(uuid.UUID(str(task_row["id"])))

    async def run_children(self, children: list[dict[str, Any]]) -> list[dict[str, Any]]:
        from hevi.tasks.repository import TaskRepository
        from hevi.tasks.task_service import TaskService

        task_repo = TaskRepository(self.pool)
        service = TaskService(task_repo)
        repro_repo = CaseReproductionRepository(self.pool)
        results: list[dict[str, Any]] = []
        for child in children:
            task_id = uuid.UUID(str(child["task_id"]))
            repro_id = str(child["reproduction_id"])
            repro = await repro_repo.get_owned(repro_id, user_id=self.user_id)
            if repro is None:
                raise RuntimeError("CHILD_REPRODUCTION_MISSING")
            if is_terminal_reproduction(str(repro.get("status"))):
                results.append({**child, "reproduction": repro})
                continue
            task_row = await task_repo.get_task(task_id)
            if task_row is None:
                raise RuntimeError("CHILD_TASK_MISSING")
            status = str(task_row.get("status") or "")
            if status in TERMINAL_TASK_STATUSES:
                refreshed = await repro_repo.get_owned(repro_id, user_id=self.user_id)
                results.append({**child, "reproduction": refreshed or repro})
                continue
            if status == "pending":
                await service.submit_task(task_id)
                task_row = await task_repo.get_task(task_id) or task_row
                status = str(task_row.get("status") or "")
            if status == "queued":
                claimed = await task_repo.claim_task(task_id, worker_id=WORKER_ID)
                if claimed is not None:
                    status = "claimed"
                else:
                    task_row = await task_repo.get_task(task_id) or task_row
                    status = str(task_row.get("status") or "")
            if status == "claimed":
                worker = str((await task_repo.get_task(task_id) or {}).get("worker_id") or "")
                if worker == WORKER_ID:
                    await service.run_task(task_id)
                else:
                    await self._poll_child_reproduction(repro_repo, repro_id)
            else:
                await self._poll_child_reproduction(repro_repo, repro_id)
            refreshed = await repro_repo.get_owned(repro_id, user_id=self.user_id)
            results.append({**child, "reproduction": refreshed or repro})
        return results

    async def _poll_child_reproduction(
        self, repro_repo: Any, reproduction_id: str,
        *, timeout_s: float = DEFAULT_POLL_TIMEOUT_S,
    ) -> dict[str, Any] | None:
        deadline = time.monotonic() + timeout_s
        last: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            last = await repro_repo.get_owned(reproduction_id, user_id=self.user_id)
            if last is not None and is_terminal_reproduction(str(last.get("status"))):
                return last
            await asyncio.sleep(DEFAULT_POLL_INTERVAL_S)
        return last

    async def load_children(self, children: list[dict[str, Any]]) -> list[dict[str, Any]]:
        repro_repo = CaseReproductionRepository(self.pool)
        loaded: list[dict[str, Any]] = []
        for child in children:
            repro = await repro_repo.get_owned(str(child["reproduction_id"]), user_id=self.user_id)
            if repro is None:
                raise RuntimeError("CHILD_REPRODUCTION_MISSING")
            loaded.append({**child, "reproduction": repro})
        return loaded

    async def aggregate(self, children: list[dict[str, Any]]) -> dict[str, Any]:
        intelligence = IntelligenceRepository(self.pool)
        plan = dict(self.plan)
        plan["plan_hash"] = self.plan_hash
        passed_by_provider = {
            str(child["provider_id"]): _reproduction_passed(child["reproduction"])
            for child in children
        }
        entry_count = 0
        evidence_rows: list[dict[str, Any]] = []
        # Load real verdicts first so evidence classification uses verdict.passed,
        # not mere reproduction status.
        verdicts: dict[str, dict[str, Any] | None] = {}
        for child in children:
            repro = child["reproduction"]
            if str(repro.get("status")) != "succeeded":
                continue
            verdict_id = repro.get("verdict_id")
            if not verdict_id:
                continue
            verdicts[str(child["provider_id"])] = await self._load_verdict(str(verdict_id))
        passed_by_provider = {
            provider: bool((verdicts.get(provider) or {}).get("passed"))
            for provider in {str(c["provider_id"]) for c in children}
        }
        any_passed = any(passed_by_provider.values())
        pattern = await intelligence.create_pattern(
            user_id=self.user_id,
            workspace_id=self.workspace_id,
            category=PatternCategory.PROVIDER.value,
            name=f"benchmark-plan:{self.plan_hash[:16]}",
            conditions={
                "analysis_revision": plan.get("analysis_revision"),
                "generation_mode": plan.get("generation_mode"),
                "providers": sorted({str(c["provider_id"]) for c in children}),
            },
            structure={
                "shot_structure": plan.get("shot_structure") or [],
                "reference_bindings": plan.get("reference_bindings") or [],
                "acceptance_dimensions": plan.get("acceptance_dimensions") or [],
            },
            expected_effect="cross-model benchmark observation; never auto-promoted",
        )
        pattern_id = str(pattern["id"])
        for child in children:
            repro = child["reproduction"]
            status = str(repro.get("status") or "")
            if status != "succeeded":
                continue
            verdict_id = repro.get("verdict_id")
            if not verdict_id:
                continue
            provider = str(child["provider_id"])
            verdict = verdicts.get(provider)
            cost = float(repro["cost_amount"]) if repro.get("cost_amount") is not None else None
            latency = float(repro["latency_ms"]) if repro.get("latency_ms") is not None else None
            dimensions = build_dimension_comparison(
                plan=plan,
                provider_id=provider,
                model_id=str(child.get("model_id") or child["provider_id"]),
                verdict=verdict,
                cost=cost,
                latency_ms=latency,
            )
            await intelligence.benchmark_entry(
                benchmark_id=self.benchmark_id,
                reproduction_id=str(child["reproduction_id"]),
                provider_id=provider,
                model_id=str(child.get("model_id") or child["provider_id"]),
                verdict_id=str(verdict_id),
                dimensions=dimensions,
                cost=cost,
                latency_ms=latency,
            )
            entry_count += 1
            passed = bool((verdict or {}).get("passed"))
            others = [v for p, v in passed_by_provider.items() if p != provider]
            evidence_type = classify_evidence_type(
                verdict_passed=passed,
                any_other_passed=any(others) if others else False,
            )
            evidence = await intelligence.add_pattern_evidence(
                pattern_id=pattern_id,
                user_id=self.user_id,
                case_id=self.case_id,
                reproduction_id=str(child["reproduction_id"]),
                verdict_id=str(verdict_id),
                evidence_type=evidence_type,
                evidence={
                    "benchmark_id": self.benchmark_id,
                    "provider_id": child["provider_id"],
                    "plan_hash": self.plan_hash,
                    "verdict_passed": passed,
                    "dimension_comparison": dimensions,
                },
            )
            evidence_rows.append(dict(evidence))
            if passed and any_passed and not all(passed_by_provider.values()):
                counter = await intelligence.add_pattern_evidence(
                    pattern_id=pattern_id,
                    user_id=self.user_id,
                    case_id=self.case_id,
                    reproduction_id=str(child["reproduction_id"]),
                    verdict_id=str(verdict_id),
                    evidence_type=EvidenceType.COUNTER_EXAMPLE.value,
                    evidence={
                        "benchmark_id": self.benchmark_id,
                        "provider_id": provider,
                        "plan_hash": self.plan_hash,
                        "note": "cross-model disagreement on frozen plan",
                        "verdict_passed": passed,
                    },
                )
                evidence_rows.append(dict(counter))
        all_terminal = all(
            is_terminal_reproduction(str(c["reproduction"].get("status"))) for c in children
        )
        all_succeeded = all(
            str(c["reproduction"].get("status")) == "succeeded" for c in children
        )
        if not all_terminal:
            status = "failed"
            failure_code = "CHILD_REPRODUCTIONS_NOT_TERMINAL"
        elif all_succeeded and entry_count >= 1:
            status = "succeeded"
            failure_code = None
        elif entry_count >= 1:
            status = "succeeded"
            failure_code = "PARTIAL_CHILD_FAILURES"
        else:
            status = "failed"
            failure_code = "NO_BENCHMARK_ENTRIES"
        finished = await intelligence.finish_benchmark(
            self.benchmark_id,
            user_id=self.user_id,
            status=status,
            provider_count=len(self.providers),
            reproduction_count=len(children),
            failure_code=failure_code,
        )
        if not finished:
            raise RuntimeError("BENCHMARK_FINISH_COMMIT_LOST")
        return {
            "status": status,
            "failure_code": failure_code,
            "entry_count": entry_count,
            "pattern_id": pattern_id,
            "evidence_count": len(evidence_rows),
            "child_statuses": {
                str(c["provider_id"]): str(c["reproduction"].get("status"))
                for c in children
            },
        }

    async def _load_verdict(self, verdict_id: str) -> dict[str, Any] | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT checks_json, passed FROM shot_verdict WHERE id=$1",
                uuid.UUID(verdict_id),
            )
        if row is None:
            return None
        checks = dict(row["checks_json"] or {})
        checks.setdefault("passed", bool(row["passed"]))
        return checks


async def _load_owned_case(
    pool: PgPool, case_id: str, user_id: str
) -> dict[str, Any] | None:
    from .case_repository import CaseRepository

    case = await CaseRepository(pool).get_owned(case_id, user_id=user_id)
    return case.model_dump(mode="json") if case is not None else None


def _reproduction_passed(reproduction: dict[str, Any]) -> bool:
    if str(reproduction.get("status")) != "succeeded":
        return False
    return bool(reproduction.get("verdict_id"))


async def run_benchmark_composition(
    *,
    pool: PgPool,
    task: dict[str, Any],
    config: dict[str, Any],
    user_id: str,
    case_id: str,
    analysis_id: str,
    benchmark_id: str,
    plan: dict[str, Any],
    plan_hash: str,
    providers: list[str],
    workspace_id: str | None,
    ports: BenchmarkPorts | None = None,
    poll_timeout_s: float = DEFAULT_POLL_TIMEOUT_S,
) -> dict[str, Any]:
    """Submit children, wait for terminal fan-in, persist entries, extract evidence."""
    active = ports or _LivePorts(
        pool=pool, task=task, config=config, user_id=user_id, case_id=case_id,
        analysis_id=analysis_id, benchmark_id=benchmark_id, plan=plan,
        plan_hash=plan_hash, providers=providers, workspace_id=workspace_id,
    )
    children = await active.ensure_children()
    ran = await active.run_children(children)
    loaded = await active.load_children(ran)
    if not all(
        is_terminal_reproduction(str(child["reproduction"].get("status")))
        for child in loaded
    ):
        deadline = time.monotonic() + poll_timeout_s
        while time.monotonic() < deadline:
            loaded = await active.load_children(children)
            if all(
                is_terminal_reproduction(str(child["reproduction"].get("status")))
                for child in loaded
            ):
                break
            await asyncio.sleep(DEFAULT_POLL_INTERVAL_S)
    if not all(
        is_terminal_reproduction(str(child["reproduction"].get("status")))
        for child in loaded
    ):
        return {
            "status": "failed",
            "error": "CHILD_REPRODUCTIONS_NOT_TERMINAL",
            "config_json": {
                **config,
                "benchmark_id": benchmark_id,
                "child_reproductions_submitted": True,
                "child_reproductions_terminal": False,
            },
        }
    aggregate = await active.aggregate(loaded)
    return {
        "status": "completed",
        "domain_only": True,
        "config_json": {
            **config,
            "benchmark_id": benchmark_id,
            "benchmark_status": aggregate.get("status"),
            "benchmark_entry_count": aggregate.get("entry_count"),
            "pattern_id": aggregate.get("pattern_id"),
            "pattern_evidence_count": aggregate.get("evidence_count"),
            "child_reproductions_submitted": True,
            "child_reproductions_terminal": True,
            "benchmark_aggregated": True,
            "child_statuses": aggregate.get("child_statuses"),
            "failure_code": aggregate.get("failure_code"),
        },
    }


__all__ = [
    "DEFAULT_POLL_TIMEOUT_S",
    "TERMINAL_REPRODUCTION_STATUSES",
    "WORKER_ID",
    "build_dimension_comparison",
    "child_idempotency_key",
    "child_task_idempotency_key",
    "classify_evidence_type",
    "is_terminal_reproduction",
    "provider_generation_parameters",
    "run_benchmark_composition",
]
