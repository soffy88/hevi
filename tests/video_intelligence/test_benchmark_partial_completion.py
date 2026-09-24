"""Partial child completion: one succeeded, one failed — results are preserved."""

from __future__ import annotations

from typing import Any

import pytest

from hevi.video_intelligence.benchmark_composition import (
    build_dimension_comparison,
    is_terminal_reproduction,
    run_benchmark_composition,
)


class PartialPorts:
    def __init__(self) -> None:
        self.children = [
            {
                "provider_id": "hyperframes",
                "model_id": "hyperframes",
                "reproduction_id": "r-hf",
                "task_id": "t-hf",
                "reproduction": {"status": "succeeded", "verdict_id": "v-hf", "provider_id": "hyperframes"},
                "reused": False,
            },
            {
                "provider_id": "manim",
                "model_id": "manim",
                "reproduction_id": "r-ma",
                "task_id": "t-ma",
                "reproduction": {"status": "failed", "failure_code": "PROVIDER_ERROR", "provider_id": "manim"},
                "reused": False,
            },
        ]
        self.aggregated: list[dict[str, Any]] = []

    async def ensure_children(self) -> list[dict[str, Any]]:
        return [dict(c) for c in self.children]

    async def run_children(self, children: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return children

    async def load_children(self, children: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [dict(c) for c in self.children]

    async def aggregate(self, children: list[dict[str, Any]]) -> dict[str, Any]:
        self.aggregated = list(children)
        succeeded = [c for c in children if c["reproduction"].get("status") == "succeeded"]
        failed = [c for c in children if c["reproduction"].get("status") == "failed"]
        return {
            "status": "succeeded" if succeeded else "failed",
            "failure_code": "PARTIAL_CHILD_FAILURES" if failed and succeeded else None,
            "entry_count": len(succeeded),
            "pattern_id": "p",
            "evidence_count": len(succeeded),
            "child_statuses": {
                str(c["provider_id"]): str(c["reproduction"].get("status"))
                for c in children
            },
        }


@pytest.mark.asyncio
async def test_partial_completion_preserves_successful_child_results() -> None:
    ports = PartialPorts()
    result = await run_benchmark_composition(
        pool=None,  # type: ignore[arg-type]
        task={"id": "t"},
        config={"case_id": "c1", "benchmark_id": "b1"},
        user_id="u",
        case_id="c1",
        analysis_id="a1",
        benchmark_id="b1",
        plan={"case_id": "c1", "analysis_revision": "v1"},
        plan_hash="h",
        providers=["hyperframes", "manim"],
        workspace_id=None,
        ports=ports,
        poll_timeout_s=0.0,
    )
    assert result["status"] == "completed"
    assert len(ports.aggregated) == 2
    statuses = {c["provider_id"]: c["reproduction"]["status"] for c in ports.aggregated}
    assert statuses == {"hyperframes": "succeeded", "manim": "failed"}
    assert result["config_json"]["benchmark_entry_count"] == 1
    assert result["config_json"]["child_statuses"]["manim"] == "failed"
    assert result["config_json"]["failure_code"] == "PARTIAL_CHILD_FAILURES"


def test_terminal_status_set_covers_succeeded_failed_blocked() -> None:
    assert is_terminal_reproduction("succeeded")
    assert is_terminal_reproduction("failed")
    assert is_terminal_reproduction("blocked")
    assert not is_terminal_reproduction("pending")
    assert not is_terminal_reproduction("running")
    assert not is_terminal_reproduction("generated")
    assert not is_terminal_reproduction("verdicted")
    assert not is_terminal_reproduction(None)


def test_dimension_comparison_never_emits_winner() -> None:
    comparison = build_dimension_comparison(
        plan={
            "case_id": "c1",
            "analysis_revision": "v1",
            "plan_hash": "h",
            "generation_mode": "exact_structure",
            "acceptance_dimensions": ["identity_consistency", "cost", "latency"],
        },
        provider_id="hyperframes",
        model_id="hyperframes",
        verdict={
            "dimensions": {
                "identity_consistency": {"status": "PASS", "score": 1.0, "reason_codes": []},
            }
        },
        cost=0.0,
        latency_ms=1200.0,
    )
    assert comparison["winner"] is None
    assert comparison["dimensions"]["identity_consistency"]["status"] == "PASS"
    assert comparison["dimensions"]["cost"]["status"] == "PASS"
    assert comparison["dimensions"]["latency"]["score"] == 1200.0
    assert comparison["frozen_plan"]["plan_hash"] == "h"
