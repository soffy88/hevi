"""Pattern evidence wiring from real benchmark/verdict outcomes only."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from hevi.video_intelligence.benchmark_composition import classify_evidence_type
from hevi.video_intelligence.intelligence_models import EvidenceType


@pytest.mark.asyncio
async def test_pattern_evidence_written_from_real_verdicts_only() -> None:
    intelligence = AsyncMock()
    intelligence.create_pattern = AsyncMock(return_value={"id": "pat-bench"})
    intelligence.benchmark_entry = AsyncMock(return_value={"id": "e"})
    intelligence.add_pattern_evidence = AsyncMock(return_value={"id": "ev"})
    intelligence.finish_benchmark = AsyncMock(return_value=True)

    # hyperframes passed, manim failed → mixed outcomes → counter_example path.
    children = [
        {
            "provider_id": "hyperframes",
            "model_id": "hyperframes",
            "reproduction_id": "r-hf",
            "reproduction": {
                "status": "succeeded",
                "verdict_id": "v-hf",
                "cost_amount": 0.0,
                "latency_ms": 10.0,
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
                "latency_ms": 20.0,
            },
        },
    ]
    verdicts = {
        "v-hf": {
            "passed": True,
            "dimensions": {"identity_consistency": {"status": "PASS", "score": 1.0, "reason_codes": []}},
        },
        "v-ma": {
            "passed": False,
            "dimensions": {"identity_consistency": {"status": "FAIL", "score": 0.0, "reason_codes": ["IDENTITY_DRIFT"]}},
        },
    }

    from hevi.video_intelligence.benchmark_composition import _LivePorts

    ports = _LivePorts.__new__(_LivePorts)
    ports.pool = None
    ports.task = {"id": "t"}
    ports.config = {}
    ports.user_id = "u"
    ports.case_id = "c1"
    ports.analysis_id = "a1"
    ports.benchmark_id = "b1"
    ports.plan = {
        "case_id": "c1",
        "analysis_revision": "v1",
        "generation_mode": "exact_structure",
        "plan_hash": "h",
        "acceptance_dimensions": ["identity_consistency", "cost", "latency"],
    }
    ports.plan_hash = "h"
    ports.plan_revision = "h"
    ports.providers = ["hyperframes", "manim"]
    ports.workspace_id = None

    async def _load_verdict(verdict_id: str) -> dict[str, Any]:
        return verdicts[verdict_id]

    ports._load_verdict = _load_verdict  # type: ignore[method-assign]

    import hevi.video_intelligence.benchmark_composition as mod

    original = mod.IntelligenceRepository
    mod.IntelligenceRepository = lambda pool: intelligence  # type: ignore[misc,assignment]
    try:
        result = await ports.aggregate(children)
    finally:
        mod.IntelligenceRepository = original

    intelligence.create_pattern.assert_awaited_once()
    pattern_kwargs = intelligence.create_pattern.await_args.kwargs
    assert pattern_kwargs["name"].startswith("benchmark-plan:")
    assert intelligence.add_pattern_evidence.await_count >= 2
    evidence_types = [
        call.kwargs["evidence_type"]
        for call in intelligence.add_pattern_evidence.await_args_list
    ]
    assert EvidenceType.POSITIVE.value in evidence_types
    assert EvidenceType.COUNTER_EXAMPLE.value in evidence_types
    for call in intelligence.add_pattern_evidence.await_args_list:
        assert call.kwargs["case_id"] == "c1"
        assert call.kwargs["reproduction_id"].startswith("r-")
        assert call.kwargs["verdict_id"].startswith("v-")
        payload = call.kwargs["evidence"]
        assert payload["benchmark_id"] == "b1"
        assert payload["plan_hash"] == "h"
    assert result["entry_count"] == 2
    assert result["pattern_id"] == "pat-bench"


@pytest.mark.asyncio
async def test_all_failed_children_write_negative_evidence_not_positive() -> None:
    intelligence = AsyncMock()
    intelligence.create_pattern = AsyncMock(return_value={"id": "pat"})
    intelligence.benchmark_entry = AsyncMock(return_value={"id": "e"})
    intelligence.add_pattern_evidence = AsyncMock(return_value={"id": "ev"})
    intelligence.finish_benchmark = AsyncMock(return_value=True)

    children = [
        {
            "provider_id": "hyperframes",
            "model_id": "hyperframes",
            "reproduction_id": "r-hf",
            "reproduction": {"status": "succeeded", "verdict_id": "v1", "cost_amount": None, "latency_ms": 1.0},
        },
        {
            "provider_id": "manim",
            "model_id": "manim",
            "reproduction_id": "r-ma",
            "reproduction": {"status": "succeeded", "verdict_id": "v2", "cost_amount": None, "latency_ms": 2.0},
        },
    ]

    from hevi.video_intelligence.benchmark_composition import _LivePorts

    ports = _LivePorts.__new__(_LivePorts)
    ports.pool = None
    ports.task = {}
    ports.config = {}
    ports.user_id = "u"
    ports.case_id = "c1"
    ports.analysis_id = "a1"
    ports.benchmark_id = "b1"
    ports.plan = {
        "case_id": "c1",
        "analysis_revision": "v1",
        "generation_mode": "exact_structure",
        "plan_hash": "h",
        "acceptance_dimensions": ["cost", "latency"],
    }
    ports.plan_hash = "h"
    ports.plan_revision = "h"
    ports.providers = ["hyperframes", "manim"]
    ports.workspace_id = None

    async def _load_verdict(verdict_id: str) -> dict[str, Any]:
        return {"passed": False, "dimensions": {}}

    ports._load_verdict = _load_verdict  # type: ignore[method-assign]

    import hevi.video_intelligence.benchmark_composition as mod

    original = mod.IntelligenceRepository
    mod.IntelligenceRepository = lambda pool: intelligence  # type: ignore[misc,assignment]
    try:
        await ports.aggregate(children)
    finally:
        mod.IntelligenceRepository = original

    evidence_types = {
        call.kwargs["evidence_type"]
        for call in intelligence.add_pattern_evidence.await_args_list
    }
    assert evidence_types == {EvidenceType.NEGATIVE.value}


def test_evidence_type_enum_values_are_preserved() -> None:
    assert EvidenceType.POSITIVE.value == "positive"
    assert EvidenceType.NEGATIVE.value == "negative"
    assert EvidenceType.COUNTER_EXAMPLE.value == "counter_example"
    assert classify_evidence_type(verdict_passed=True, any_other_passed=True) == "positive"
    assert classify_evidence_type(verdict_passed=False, any_other_passed=False) == "negative"
    assert classify_evidence_type(verdict_passed=False, any_other_passed=True) == "counter_example"
