"""Worker restart recovery: re-entry reuses durable children and finishes fan-in."""

from __future__ import annotations

from typing import Any

import pytest

from hevi.video_intelligence.benchmark_composition import run_benchmark_composition


class RestartPorts:
    """First entry leaves children mid-flight; second entry finishes them."""

    def __init__(self) -> None:
        self.entries = 0
        self.ensure_calls = 0
        self.aggregate_calls = 0
        self.children: list[dict[str, Any]] = [
            {
                "provider_id": "hyperframes",
                "model_id": "hyperframes",
                "reproduction_id": "r-hf",
                "task_id": "t-hf",
                "reproduction": {"status": "running"},
                "reused": False,
            },
            {
                "provider_id": "manim",
                "model_id": "manim",
                "reproduction_id": "r-ma",
                "task_id": "t-ma",
                "reproduction": {"status": "pending"},
                "reused": False,
            },
        ]

    async def ensure_children(self) -> list[dict[str, Any]]:
        self.ensure_calls += 1
        self.entries += 1
        reused = self.entries > 1
        return [{**c, "reused": reused} for c in self.children]

    async def run_children(self, children: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self.entries >= 2:
            for child in children:
                child["reproduction"] = {
                    **child["reproduction"],
                    "status": "succeeded",
                    "verdict_id": "v",
                }
                # Persist terminal state for load_children on this entry.
            self.children = children
        return children

    async def load_children(self, children: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{**c, "reproduction": dict(c["reproduction"])} for c in self.children]

    async def aggregate(self, children: list[dict[str, Any]]) -> dict[str, Any]:
        self.aggregate_calls += 1
        return {
            "status": "succeeded",
            "failure_code": None,
            "entry_count": len(children),
            "pattern_id": "p",
            "evidence_count": len(children),
            "child_statuses": {
                str(c["provider_id"]): str(c["reproduction"].get("status"))
                for c in children
            },
        }


def _kwargs(ports: RestartPorts) -> dict[str, Any]:
    return {
        "pool": None,
        "task": {"id": "t"},
        "config": {"case_id": "c1", "benchmark_id": "b1"},
        "user_id": "u",
        "case_id": "c1",
        "analysis_id": "a1",
        "benchmark_id": "b1",
        "plan": {"case_id": "c1", "analysis_revision": "v1"},
        "plan_hash": "h",
        "providers": ["hyperframes", "manim"],
        "workspace_id": None,
        "ports": ports,
        "poll_timeout_s": 0.0,
    }


@pytest.mark.asyncio
async def test_restart_with_non_terminal_children_does_not_aggregate() -> None:
    ports = RestartPorts()
    result = await run_benchmark_composition(**_kwargs(ports))  # type: ignore[arg-type]
    assert result["status"] == "failed"
    assert result["error"] == "CHILD_REPRODUCTIONS_NOT_TERMINAL"
    assert result["config_json"]["child_reproductions_submitted"] is True
    assert result["config_json"]["child_reproductions_terminal"] is False
    assert ports.aggregate_calls == 0


@pytest.mark.asyncio
async def test_restart_recovery_reuses_children_and_aggregates() -> None:
    ports = RestartPorts()
    await run_benchmark_composition(**_kwargs(ports))  # type: ignore[arg-type]
    result = await run_benchmark_composition(**_kwargs(ports))  # type: ignore[arg-type]
    assert result["status"] == "completed"
    assert ports.ensure_calls == 2
    assert ports.aggregate_calls == 1
    assert result["config_json"]["benchmark_aggregated"] is True
    assert all(c.get("reused") for c in ports.children)


@pytest.mark.asyncio
async def test_children_already_terminal_on_first_reentry_aggregate_immediately() -> None:
    ports = RestartPorts()
    # Simulate: worker already finished children before benchmark re-entered.
    for child in ports.children:
        child["reproduction"] = {"status": "succeeded", "verdict_id": "v"}
    result = await run_benchmark_composition(**_kwargs(ports))  # type: ignore[arg-type]
    assert result["status"] == "completed"
    assert ports.aggregate_calls == 1
    assert result["config_json"]["benchmark_entry_count"] == 2
