"""Durable orchestration helpers for benchmark and learning projections."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from obase.persistence import PgPool

from .case_analysis import CaseAnalysis
from .case_repository import CaseRepository
from .intelligence_repository import IntelligenceRepository, pattern_plan_hash
from .runtime_repository import CaseAnalysisRepository

BENCHMARK_DIMENSIONS = (
    "identity_consistency", "action_completion", "action_contact",
    "temporal_continuity", "camera_adherence", "style_adherence",
    "object_persistence", "audio_alignment", "lip_sync", "cost", "latency",
)


async def execute_case_benchmark_task(task: dict[str, Any], pool: PgPool) -> dict[str, Any]:
    """Freeze one plan, fan out child reproductions, then durable fan-in."""
    config = dict(task.get("config_json") or {})
    user_id = str(task.get("user_id") or config.get("user_id") or "")
    case_id = str(config.get("case_id") or "")
    benchmark_id = str(config.get("benchmark_id") or "")
    case = await CaseRepository(pool).get_owned(case_id, user_id=user_id)
    analysis_id = str(config.get("analysis_id") or "")
    analysis_row = await CaseAnalysisRepository(pool).get_owned(analysis_id, user_id=user_id)
    if case is None or not analysis_row or not analysis_row.get("analysis_json"):
        return {"status": "failed", "error": "CASE_ANALYSIS_REQUIRED", "config_json": config}
    analysis = CaseAnalysis.model_validate(analysis_row["analysis_json"])
    plan = {
        "case_id": case_id,
        "analysis_revision": str(analysis.analyzer_version),
        "generation_mode": str(config.get("generation_mode") or "exact_structure"),
        "compiled_semantic_intent": case.original_prompt or "",
        "shot_structure": [item.model_dump(mode="json") for item in analysis.case_shots],
        "reference_bindings": [item.model_dump(mode="json") for item in analysis.reference_bindings],
        "duration_ms": case.duration_ms,
        "aspect_ratio": case.aspect_ratio,
        "acceptance_dimensions": list(BENCHMARK_DIMENSIONS),
    }
    plan_hash = pattern_plan_hash(plan)
    plan["plan_hash"] = plan_hash
    repo = IntelligenceRepository(pool)
    stored_plan = await repo.create_benchmark_plan(
        user_id=user_id, workspace_id=config.get("workspace_id"), case_id=case_id,
        analysis_revision=analysis.analyzer_version, plan=plan, plan_hash=plan_hash,
    )
    providers = [str(item) for item in config.get("benchmark_providers", []) if item]
    providers = list(dict.fromkeys(providers))
    if len(providers) < 2:
        await repo.finish_benchmark(
            benchmark_id, user_id=user_id, status="blocked", provider_count=len(providers),
            reproduction_count=0, failure_code="SECOND_REAL_PROVIDER_UNAVAILABLE",
        )
        return {
            "status": "blocked", "error": "SECOND_REAL_PROVIDER_UNAVAILABLE",
            "config_json": {**config, "benchmark_plan_id": str(stored_plan["id"])},
        }
    from .benchmark_composition import run_benchmark_composition

    return await run_benchmark_composition(
        pool=pool,
        task=task,
        config={**config, "benchmark_plan_id": str(stored_plan["id"])},
        user_id=user_id,
        case_id=case_id,
        analysis_id=analysis_id,
        benchmark_id=benchmark_id,
        plan=plan,
        plan_hash=plan_hash,
        providers=providers,
        workspace_id=config.get("workspace_id"),
    )


async def execute_template_qualification_task(task: dict[str, Any], pool: PgPool) -> dict[str, Any]:
    """Persist a qualification result; promotion is a separate explicit action."""
    config = dict(task.get("config_json") or {})
    template_id = str(config.get("template_id") or "")
    user_id = str(task.get("user_id") or config.get("user_id") or "")
    if not template_id or not user_id:
        return {"status": "failed", "error": "TEMPLATE_ID_REQUIRED", "config_json": config}
    run = await IntelligenceRepository(pool).qualify_template(
        template_id=template_id, user_id=user_id,
        status=str(config.get("qualification_status") or "candidate"),
        case_ids=[str(x) for x in config.get("case_ids", [])],
        reproduction_ids=[str(x) for x in config.get("reproduction_ids", [])],
        baseline_revision=config.get("baseline_revision"),
        dimension_deltas=dict(config.get("dimension_deltas") or {}),
        key=str(config.get("idempotency_key") or task["id"]),
    )
    return {"status": "completed", "domain_only": True, "config_json": {**config, "qualification_run_id": str(run["id"])}}


async def write_learning_event(pool: PgPool, *, user_id: str, workspace_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    return await IntelligenceRepository(pool).write_learning_event(
        user_id=user_id, workspace_id=workspace_id, payload=payload
    )


def prompt_hash(prompt: str | None) -> str | None:
    if not prompt:
        return None
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def retake_outcome(before: dict[str, Any], after: dict[str, Any]) -> str:
    before_score = sum(float(item.get("score") or 0) for item in (before.get("dimensions") or {}).values() if item.get("score") is not None)
    after_score = sum(float(item.get("score") or 0) for item in (after.get("dimensions") or {}).values() if item.get("score") is not None)
    if after_score > before_score:
        return "improved"
    if after_score < before_score:
        return "regressed"
    if str(after.get("status")) in {"FAILED", "BLOCKED"}:
        return "failed"
    return "unchanged"


def cluster_pattern_signatures(patterns: list[dict[str, Any]], *, algorithm_version: str = "signature-v1") -> list[dict[str, Any]]:
    """Return suggestion-only clusters; never merges or promotes patterns."""
    buckets: dict[str, list[dict[str, Any]]] = {}
    for pattern in patterns:
        signature = json.dumps({"category": pattern.get("category"), "conditions": pattern.get("conditions") or {}, "structure": pattern.get("structure") or {}}, sort_keys=True)
        key = hashlib.sha256(signature.encode()).hexdigest()[:16]
        buckets.setdefault(key, []).append(pattern)
    return [
        {"id": f"cluster:{key}", "pattern_ids": [str(item["id"]) for item in values], "evidence_ids": [], "algorithm": "exact_structural_signature", "algorithm_version": algorithm_version, "confidence": 1.0, "suggestion_only": True}
        for key, values in buckets.items()
    ]


__all__ = ["BENCHMARK_DIMENSIONS", "cluster_pattern_signatures", "execute_case_benchmark_task", "execute_template_qualification_task", "prompt_hash", "retake_outcome", "write_learning_event"]
