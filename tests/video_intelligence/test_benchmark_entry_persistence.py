"""BenchmarkEntry persistence: caller is connected and references canonical entities."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from hevi.video_intelligence.benchmark_composition import (
    build_dimension_comparison,
    classify_evidence_type,
)


@pytest.mark.asyncio
async def test_benchmark_entry_caller_connected_with_canonical_references() -> None:
    intelligence = AsyncMock()
    intelligence.create_pattern = AsyncMock(return_value={"id": "pat-1"})
    intelligence.benchmark_entry = AsyncMock(return_value={"id": "e1"})
    intelligence.add_pattern_evidence = AsyncMock(return_value={"id": "ev1"})
    intelligence.mark_benchmark_running = AsyncMock(return_value=True)
    intelligence.finish_benchmark = AsyncMock(return_value=True)

    plan = {
        "case_id": "c1",
        "analysis_revision": "v1",
        "generation_mode": "exact_structure",
        "plan_hash": "h",
        "acceptance_dimensions": ["identity_consistency", "cost", "latency"],
    }
    children = [
        {
            "provider_id": "hyperframes",
            "model_id": "hyperframes",
            "reproduction_id": "r-hf",
            "reproduction": {
                "status": "succeeded",
                "verdict_id": "v-hf",
                "cost_amount": 0.0,
                "latency_ms": 100.0,
            },
        },
        {
            "provider_id": "manim",
            "model_id": "manim",
            "reproduction_id": "r-ma",
            "reproduction": {
                "status": "succeeded",
                "verdict_id": "v-ma",
                "cost_amount": 0.0,
                "latency_ms": 200.0,
            },
        },
    ]

    from hevi.video_intelligence.benchmark_composition import _LivePorts

    ports = _LivePorts.__new__(_LivePorts)
    ports.pool = None
    ports.task = {"id": "t"}
    ports.config = {}
    ports.user_id = "u"
    ports.case_id = "c1"
    ports.analysis_id = "a1"
    ports.benchmark_id = "b1"
    ports.plan = plan
    ports.plan_hash = "h"
    ports.plan_revision = "h"
    ports.providers = ["hyperframes", "manim"]
    ports.workspace_id = None

    async def _load_verdict(verdict_id: str) -> dict[str, Any]:
        return {
            "passed": True,
            "dimensions": {
                "identity_consistency": {"status": "PASS", "score": 1.0, "reason_codes": []},
            },
        }

    ports._load_verdict = _load_verdict  # type: ignore[method-assign]

    # Patch intelligence repository construction used inside aggregate.
    import hevi.video_intelligence.benchmark_composition as mod

    original = mod.IntelligenceRepository
    mod.IntelligenceRepository = lambda pool: intelligence  # type: ignore[misc,assignment]
    try:
        result = await ports.aggregate(children)
    finally:
        mod.IntelligenceRepository = original

    assert intelligence.benchmark_entry.await_count == 2
    call = intelligence.benchmark_entry.await_args_list[0]
    kwargs = call.kwargs
    assert kwargs["benchmark_id"] == "b1"
    assert kwargs["reproduction_id"] == "r-hf"
    assert kwargs["provider_id"] == "hyperframes"
    assert kwargs["model_id"] == "hyperframes"
    assert kwargs["verdict_id"] == "v-hf"
    assert kwargs["cost"] == 0.0
    assert kwargs["latency_ms"] == 100.0
    assert kwargs["dimensions"]["winner"] is None
    assert kwargs["dimensions"]["frozen_plan"]["plan_hash"] == "h"
    assert result["entry_count"] == 2
    assert intelligence.finish_benchmark.await_count == 1
    finish = intelligence.finish_benchmark.await_args.kwargs
    assert finish["status"] == "succeeded"
    assert finish["provider_count"] == 2
    assert finish["reproduction_count"] == 2


def test_dimension_comparison_references_verdict_without_copying_authority() -> None:
    verdict = {
        "passed": True,
        "dimensions": {
            "identity_consistency": {"status": "PASS", "score": 0.9, "reason_codes": []},
            "style_adherence": {"status": "NOT_OBSERVED", "score": None, "reason_codes": []},
        },
    }
    comparison = build_dimension_comparison(
        plan={
            "case_id": "c1",
            "analysis_revision": "rev",
            "plan_hash": "hh",
            "generation_mode": "exact_structure",
            "duration_ms": 1000,
            "aspect_ratio": "16:9",
            "acceptance_dimensions": ["identity_consistency", "style_adherence", "cost"],
        },
        provider_id="manim",
        model_id="manim",
        verdict=verdict,
        cost=None,
        latency_ms=None,
    )
    assert comparison["dimensions"]["identity_consistency"]["score"] == 0.9
    assert comparison["dimensions"]["style_adherence"]["status"] == "NOT_OBSERVED"
    assert comparison["dimensions"]["cost"]["status"] == "NOT_OBSERVED"
    assert "passed" not in comparison
    assert comparison["provider_id"] == "manim"


def test_evidence_type_classification_preserves_three_kinds() -> None:
    assert classify_evidence_type(verdict_passed=True, any_other_passed=False) == "positive"
    assert classify_evidence_type(verdict_passed=False, any_other_passed=False) == "negative"
    assert classify_evidence_type(verdict_passed=False, any_other_passed=True) == "counter_example"
