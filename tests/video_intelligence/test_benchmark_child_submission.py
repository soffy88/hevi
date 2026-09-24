"""Child reproduction submission for cross-model benchmarks."""

from __future__ import annotations

from typing import Any

import pytest

from hevi.video_intelligence.benchmark_composition import (
    child_idempotency_key,
    child_task_idempotency_key,
    provider_generation_parameters,
    run_benchmark_composition,
)


class FakePorts:
    def __init__(self) -> None:
        self.ensure_calls = 0
        self.run_calls = 0
        self.aggregate_calls: list[list[dict[str, Any]]] = []
        self.children: list[dict[str, Any]] = [
            {
                "provider_id": "hyperframes",
                "model_id": "hyperframes",
                "reproduction_id": "r-hf",
                "task_id": "t-hf",
                "reproduction": {"status": "pending", "provider_id": "hyperframes"},
                "reused": False,
            },
            {
                "provider_id": "manim",
                "model_id": "manim",
                "reproduction_id": "r-ma",
                "task_id": "t-ma",
                "reproduction": {"status": "pending", "provider_id": "manim"},
                "reused": False,
            },
        ]
        self.terminal_after_run = True

    async def ensure_children(self) -> list[dict[str, Any]]:
        self.ensure_calls += 1
        return list(self.children)

    async def run_children(self, children: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.run_calls += 1
        if self.terminal_after_run:
            for child in children:
                child["reproduction"] = {
                    **child["reproduction"],
                    "status": "succeeded",
                    "verdict_id": f"v-{child['provider_id']}",
                }
        return children

    async def load_children(self, children: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return children

    async def aggregate(self, children: list[dict[str, Any]]) -> dict[str, Any]:
        self.aggregate_calls.append(list(children))
        return {
            "status": "succeeded",
            "failure_code": None,
            "entry_count": len(children),
            "pattern_id": "p1",
            "evidence_count": len(children),
            "child_statuses": {
                str(c["provider_id"]): str(c["reproduction"].get("status"))
                for c in children
            },
        }


def _config() -> dict[str, Any]:
    return {"case_id": "c1", "benchmark_id": "b1", "benchmark_providers": ["hyperframes", "manim"]}


def _plan() -> dict[str, Any]:
    return {
        "case_id": "c1",
        "analysis_revision": "v1",
        "generation_mode": "exact_structure",
        "acceptance_dimensions": ["identity_consistency", "cost", "latency"],
        "plan_hash": "abc",
    }


@pytest.mark.asyncio
async def test_submission_creates_children_for_each_provider() -> None:
    ports = FakePorts()
    result = await run_benchmark_composition(
        pool=None,  # type: ignore[arg-type]
        task={"id": "t"},
        config=_config(),
        user_id="u",
        case_id="c1",
        analysis_id="a1",
        benchmark_id="b1",
        plan=_plan(),
        plan_hash="abc",
        providers=["hyperframes", "manim"],
        workspace_id=None,
        ports=ports,
        poll_timeout_s=0.0,
    )
    assert ports.ensure_calls == 1
    assert ports.run_calls == 1
    assert len(ports.aggregate_calls) == 1
    assert result["status"] == "completed"
    assert result["domain_only"] is True
    cfg = result["config_json"]
    assert cfg["child_reproductions_submitted"] is True
    assert cfg["child_reproductions_terminal"] is True
    assert cfg["benchmark_aggregated"] is True
    assert cfg["benchmark_entry_count"] == 2


def test_child_idempotency_key_is_benchmark_provider_revision() -> None:
    key = child_idempotency_key("b1", "hyperframes", "rev1")
    assert key == "benchmark:b1:hyperframes:rev1"
    assert child_idempotency_key("b1", "manim", "rev1") != key
    assert child_idempotency_key("b2", "hyperframes", "rev1") != key
    assert child_idempotency_key("b1", "hyperframes", "rev2") != key


def test_child_task_idempotency_key_is_distinct_from_reproduction_key() -> None:
    assert child_task_idempotency_key("b1", "manim", "r") != child_idempotency_key(
        "b1", "manim", "r"
    )


def test_provider_generation_parameters_are_free_local_budget() -> None:
    hf = provider_generation_parameters("hyperframes")
    ma = provider_generation_parameters("manim")
    assert hf["width"] == 320 and hf["height"] == 240
    assert ma["mode"] == "code_scene"
    assert provider_generation_parameters("unknown")["width"] == 320
