"""pipeline manifest 测试辅助 stages(3O obase Stage 契约: (data, ctx) -> dict)。

仅供 tests/test_pipeline_manifest.py 使用; 位于 hevi.* 白名单内(manifest fn 引用可解析)。
"""

from __future__ import annotations

from typing import Any

from obase import PauseRequested
from obase.exceptions import BudgetExceeded, StageContractViolation

# 跨测试可变的全局状态(测试内 reset)。
CALLS: dict[str, int] = {}
PAUSE_ONCE: dict[str, bool] = {}
FLAKY_ATTEMPTS: dict[str, int] = {}


def _bump(name: str) -> None:
    CALLS[name] = CALLS.get(name, 0) + 1


async def stage_script(data: dict[str, Any], ctx: Any) -> dict[str, Any]:
    _bump("script")
    return {"script": {"topic": data.get("topic", ""), "lines": ["hello"]}}


async def stage_assemble(data: dict[str, Any], ctx: Any) -> dict[str, Any]:
    _bump("assemble")
    assert "script" in data, "input_keys 过滤应只传 script"
    return {"video_path": "/tmp/out.mp4"}


async def stage_first(data: dict[str, Any], ctx: Any) -> dict[str, Any]:
    _bump("first")
    return {"first": data.get("seed", 0) + 1}


async def stage_pause_once(data: dict[str, Any], ctx: Any) -> dict[str, Any]:
    _bump("pause_stage")
    if PAUSE_ONCE.get("pause_stage"):
        raise PauseRequested("pause for review", resume_data={"paused": True})
    return {"paused": True}


async def stage_last(data: dict[str, Any], ctx: Any) -> dict[str, Any]:
    _bump("last")
    assert data.get("first") == 2, "前序阶段不应重跑(seed=1 → first=2)"
    return {"done": True}


async def stage_budget_exceed(data: dict[str, Any], ctx: Any) -> dict[str, Any]:
    raise BudgetExceeded("run over budget")


async def stage_flaky(data: dict[str, Any], ctx: Any) -> dict[str, Any]:
    _bump("flaky")
    need = FLAKY_ATTEMPTS.get("flaky", 0)
    if CALLS["flaky"] < need:
        raise RuntimeError("transient failure")
    return {"ok": True}


async def stage_contract_violation(data: dict[str, Any], ctx: Any) -> dict[str, Any]:
    raise StageContractViolation("contract broken")
