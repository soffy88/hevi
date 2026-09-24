"""Durable fan-in: aggregate only after every required child is terminal."""

from __future__ import annotations

from typing import Any

import pytest

from hevi.video_intelligence.benchmark_composition import (
    is_terminal_reproduction,
    run_benchmark_composition,
)


class FanInPorts:
    def __init__(self, statuses: dict[str, str]) -> None:
        self.statuses = statuses
        self.aggregate_calls = 0
        self.load_calls = 0
        self.run_calls = 0
        self._round = 0

    def _children(self) -> list[dict[str, Any]]:
        return [
            {
                "provider_id": provider,
                "model_id": provider,
                "reproduction_id": f"r-{provider}",
                "task_id": f"t-{provider}",
                "reproduction": {"status": self.statuses[provider]},
            }
            for provider in sorted(self.statuses)
        ]

    async def ensure_children(self) -> list[dict[str, Any]]:
        return self._children()

    async def run_children(self, children: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.run_calls += 1
        # First run leaves one child non-terminal; second run (after poll loop
        # with zero timeout we mark terminal here to model worker completion).
        self._round += 1
        if self._round >= 1 and all(
            is_terminal_reproduction(s) for s in self.statuses.values()
        ):
            return children
        return children

    async def load_children(self, children: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.load_calls += 1
        return self._children()

    async def aggregate(self, children: list[dict[str, Any]]) -> dict[str, Any]:
        self.aggregate_calls += 1
        succeeded = [c for c in children if c["reproduction"].get("status") == "succeeded"]
        failed = [c for c in children if c["reproduction"].get("status") == "failed"]
        failure_code = "PARTIAL_CHILD_FAILURES" if failed and succeeded else None
        return {
            "status": "succeeded" if succeeded else "failed",
            "failure_code": failure_code,
            "entry_count": len(succeeded),
            "pattern_id": "p",
            "evidence_count": len(succeeded),
            "child_statuses": {
                str(c["provider_id"]): str(c["reproduction"].get("status"))
                for c in children
            },
        }


async def _run(ports: FanInPorts) -> dict[str, Any]:
    return await run_benchmark_composition(
        pool=None,  # type: ignore[arg-type]
        task={"id": "t"},
        config={"case_id": "c1", "benchmark_id": "b1"},
        user_id="u",
        case_id="c1",
        analysis_id="a1",
        benchmark_id="b1",
        plan={"case_id": "c1", "analysis_revision": "v1"},
        plan_hash="h",
        providers=sorted(ports.statuses),
        workspace_id=None,
        ports=ports,
        poll_timeout_s=0.0,
    )


@pytest.mark.asyncio
async def test_fan_in_waits_for_all_children_terminal() -> None:
    ports = FanInPorts({"hyperframes": "succeeded", "manim": "running"})
    result = await _run(ports)
    assert result["status"] == "failed"
    assert result["error"] == "CHILD_REPRODUCTIONS_NOT_TERMINAL"
    assert ports.aggregate_calls == 0


@pytest.mark.asyncio
async def test_fan_in_runs_when_both_children_terminal() -> None:
    ports = FanInPorts({"hyperframes": "succeeded", "manim": "succeeded"})
    result = await _run(ports)
    assert result["status"] == "completed"
    assert ports.aggregate_calls == 1
    assert result["config_json"]["benchmark_entry_count"] == 2
    assert result["config_json"]["child_reproductions_terminal"] is True


@pytest.mark.asyncio
async def test_fan_in_includes_failed_terminal_child_without_dropping_success() -> None:
    ports = FanInPorts({"hyperframes": "succeeded", "manim": "failed"})
    result = await _run(ports)
    assert result["status"] == "completed"
    assert ports.aggregate_calls == 1
    assert result["config_json"]["child_statuses"] == {
        "hyperframes": "succeeded",
        "manim": "failed",
    }
    assert result["config_json"]["benchmark_entry_count"] == 1
    assert result["config_json"]["failure_code"] == "PARTIAL_CHILD_FAILURES"
