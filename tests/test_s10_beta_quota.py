"""S10: public-beta quota policy + canvas parallel layer execution."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from hevi.canvas.incremental_executor import ExecuteOptions, IncrementalExecutor
from hevi.canvas.koubo_template import build_koubo_graph
from hevi.canvas.node_store import InMemoryNodeStore
from hevi.quota import (
    QuotaError,
    beta_free_enabled,
    requested_duration_seconds,
    resolve_max_duration_s,
)


def test_beta_policy_defaults_and_duration_map(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HEVI_BETA_FREE", raising=False)
    monkeypatch.delenv("HEVI_BETA_MAX_DURATION_S", raising=False)
    assert beta_free_enabled() is True
    assert resolve_max_duration_s() == 60
    assert requested_duration_seconds(duration_archetype="short") == 10
    assert requested_duration_seconds(duration_archetype="1-5min") == 180
    assert requested_duration_seconds(duration_s=30) == 30
    assert requested_duration_seconds(duration_archetype="unknown") == 0


def test_beta_policy_env_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEVI_BETA_FREE", "0")
    monkeypatch.setenv("HEVI_BETA_MAX_DURATION_S", "45")
    assert beta_free_enabled() is False
    assert resolve_max_duration_s() == 45

    monkeypatch.setenv("HEVI_BETA_FREE", "1")
    monkeypatch.setenv("HEVI_BETA_MAX_DURATION_S", "not-a-number")
    assert resolve_max_duration_s() == 60


def test_quota_error_carries_friendly_detail() -> None:
    exc = QuotaError("今天已生成 5 条成片", code="daily_limit_reached", status_code=429)
    detail = exc.detail()
    assert detail["error"] == "daily_limit_reached"
    assert detail["message"].startswith("今天已生成")
    assert detail["daily_limit"] == 5
    assert detail["max_duration_s"] == 60
    assert detail["max_concurrent"] == 1


def _pass_reviewer(node: Any, output: Any, **kwargs: Any) -> dict[str, Any]:
    return {"result": "pass", "reasons": [], "suggested_prompt": "",
            "review_mode": "deterministic", "model": "test"}


@pytest.mark.asyncio
async def test_independent_nodes_in_one_layer_run_in_parallel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEVI_CANVAS_PARALLEL", "4")
    lines = "第一句。第二句。第三句。第四句。第五句。第六句。第七句。第八句。"
    graph = build_koubo_graph(script_text=lines, topic="并行")
    store = InMemoryNodeStore()
    await store.sync_graph("g-par", graph["nodes"], graph["edges"])

    async def slow_executor(node: Any, upstream: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(0.12)
        return {"koubo_step": "x", "output": "x", "content_hash": "h"}

    engine = IncrementalExecutor(store, executor=slow_executor, reviewer=_pass_reviewer)
    started = time.monotonic()
    result = await engine.execute(
        "g-par", graph, options=ExecuteOptions(scope="dirty", parallelism=4)
    )
    elapsed = time.monotonic() - started

    assert result["status"] == "completed"
    # 8 sentence branches (8 tts + 8 evidence + 8 avatar + 8 segment + tail)
    # sequential would be ~2.9 s at 0.12 s/node; four-way parallel must be well
    # under that even on a loaded CI box.
    assert elapsed < 2.2, elapsed


def test_parallelism_can_be_forced_sequential(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEVI_CANVAS_PARALLEL", "9")
    engine = IncrementalExecutor(InMemoryNodeStore(), executor=None)  # type: ignore[arg-type]
    assert engine._parallelism(ExecuteOptions()) == 9
    assert engine._parallelism(ExecuteOptions(parallelism=1)) == 1
