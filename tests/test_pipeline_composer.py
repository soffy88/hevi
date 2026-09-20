"""P3: generic oservi.PipelineComposerEngine behavior tests.

These tests assert only GENERIC mechanism behavior — no HEVI business semantics.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from oservi import PipelineComposerEngine, StepSpec


def _ok(**payload):
    async def _tx(config, input_data, output_dir, *, on_step=None):
        return {"status": "completed", "result": {**payload, "ran": True}}

    _tx.__module__ = "omodul.test"
    return _tx


def _fail(code="TEST_FAIL"):
    async def _tx(config, input_data, output_dir, *, on_step=None):
        return {"status": "failed", "error": {"code": code, "message": "boom", "retryable": False}}

    _tx.__module__ = "omodul.test"
    return _tx


def _boom():
    async def _tx(config, input_data, output_dir, *, on_step=None):
        raise RuntimeError("programmer error")

    _tx.__module__ = "omodul.test"
    return _tx


@pytest.mark.asyncio
async def test_sequential_success(tmp_path: Path) -> None:
    engine = PipelineComposerEngine(
        steps=[
            StepSpec("a", _ok(value=1)),
            StepSpec("b", _ok(value=2), depends_on=("a",)),
        ],
        trigger={"on_demand": True},
        config={},
        name="seq",
    )
    out = await engine.run(input_data={}, output_dir=tmp_path)
    assert out["status"] == "completed"
    assert out["order"] == ["a", "b"]
    assert out["steps"]["a"]["status"] == "completed"
    assert out["steps"]["b"]["status"] == "completed"


@pytest.mark.asyncio
async def test_dependent_failure_propagation(tmp_path: Path) -> None:
    engine = PipelineComposerEngine(
        steps=[
            StepSpec("a", _fail()),
            StepSpec("b", _ok(), depends_on=("a",)),
        ],
        trigger={"on_demand": True},
        config={},
        name="fail",
    )
    out = await engine.run(input_data={}, output_dir=tmp_path)
    assert out["status"] == "failed"
    assert out["steps"]["a"]["status"] == "failed"
    assert out["steps"]["b"]["status"] == "skipped"


@pytest.mark.asyncio
async def test_optional_failure_does_not_block(tmp_path: Path) -> None:
    engine = PipelineComposerEngine(
        steps=[
            StepSpec("a", _fail(), optional=True),
            StepSpec("b", _ok(), depends_on=("a",)),
        ],
        trigger={"on_demand": True},
        config={},
        name="optional",
    )
    out = await engine.run(input_data={}, output_dir=tmp_path)
    # b still runs because a was optional
    assert out["steps"]["a"]["status"] == "failed"
    assert out["steps"]["b"]["status"] == "completed"


@pytest.mark.asyncio
async def test_fan_out_and_fan_in(tmp_path: Path) -> None:
    engine = PipelineComposerEngine(
        steps=[
            StepSpec("branch_a", _ok(branch="a"), mode="fan_out"),
            StepSpec("branch_b", _ok(branch="b"), mode="fan_out"),
            StepSpec("join", _ok(join=True), depends_on=("branch_a", "branch_b"), mode="fan_in"),
        ],
        trigger={"on_demand": True},
        config={},
        name="fanout",
    )
    out = await engine.run(input_data={}, output_dir=tmp_path)
    assert out["status"] == "completed"
    assert out["steps"]["branch_a"]["status"] == "completed"
    assert out["steps"]["branch_b"]["status"] == "completed"
    assert out["steps"]["join"]["status"] == "completed"


@pytest.mark.asyncio
async def test_fan_out_partial_failure(tmp_path: Path) -> None:
    engine = PipelineComposerEngine(
        steps=[
            StepSpec("branch_a", _ok(), mode="fan_out"),
            StepSpec("branch_b", _fail(), mode="fan_out"),
            StepSpec("join", _ok(), depends_on=("branch_a", "branch_b"), mode="fan_in"),
        ],
        trigger={"on_demand": True},
        config={},
        name="partial",
    )
    out = await engine.run(input_data={}, output_dir=tmp_path)
    assert out["status"] == "failed"
    assert out["steps"]["branch_a"]["status"] == "completed"
    assert out["steps"]["branch_b"]["status"] == "failed"
    assert out["steps"]["join"]["status"] == "skipped"


@pytest.mark.asyncio
async def test_fan_in_deterministic_ordering(tmp_path: Path) -> None:
    engine = PipelineComposerEngine(
        steps=[
            StepSpec("b", _ok(), mode="fan_out", priority=1),
            StepSpec("a", _ok(), mode="fan_out", priority=0),
            StepSpec("join", _ok(), depends_on=("a", "b"), mode="fan_in"),
        ],
        trigger={"on_demand": True},
        config={},
        name="order",
    )
    out1 = await engine.run(input_data={}, output_dir=tmp_path)
    out2 = await engine.run(input_data={}, output_dir=tmp_path)
    assert out1["order"] == out2["order"]


@pytest.mark.asyncio
async def test_cancellation_propagation(tmp_path: Path) -> None:
    engine = PipelineComposerEngine(
        steps=[StepSpec("a", _ok()), StepSpec("b", _ok(), depends_on=("a",))],
        trigger={"on_demand": True},
        config={},
        name="cancel",
    )
    engine.cancel()
    out = await engine.run(input_data={}, output_dir=tmp_path)
    assert out["status"] == "cancelled"
    assert all(s["status"] == "cancelled" for s in out["steps"].values())


@pytest.mark.asyncio
async def test_reuse_existing_decision(tmp_path: Path) -> None:
    calls: list[str] = []

    async def tx(config, input_data, output_dir, *, on_step=None):
        calls.append("ran")
        return {"status": "completed", "result": {"ran": True}}

    tx.__module__ = "omodul.test"

    def decision_fn(*, step_id, dependency_results, config):
        if step_id == "a":
            return {"decision": "reuse_existing", "result": {"cached": True}}
        return "run"

    engine = PipelineComposerEngine(
        steps=[StepSpec("a", tx), StepSpec("b", tx, depends_on=("a",))],
        decision_fn=decision_fn,
        trigger={"on_demand": True},
        config={},
        name="reuse",
    )
    out = await engine.run(input_data={}, output_dir=tmp_path)
    assert out["steps"]["a"]["status"] == "reused"
    assert out["steps"]["a"]["result"] == {"cached": True}
    assert calls == ["ran"]  # only b actually executed


@pytest.mark.asyncio
async def test_skip_decision(tmp_path: Path) -> None:
    def decision_fn(*, step_id, dependency_results, config):
        return "skip" if step_id == "a" else "run"

    engine = PipelineComposerEngine(
        steps=[StepSpec("a", _ok())],
        decision_fn=decision_fn,
        trigger={"on_demand": True},
        config={},
        name="skip",
    )
    out = await engine.run(input_data={}, output_dir=tmp_path)
    assert out["steps"]["a"]["status"] == "skipped"


@pytest.mark.asyncio
async def test_unknown_transaction_dependency(tmp_path: Path) -> None:
    engine = PipelineComposerEngine(
        steps=[StepSpec("a", _ok(), depends_on=("ghost",))],
        trigger={"on_demand": True},
        config={},
        name="unknown",
    )
    with pytest.raises(ValueError, match="unknown step"):
        await engine.run(input_data={}, output_dir=tmp_path)


@pytest.mark.asyncio
async def test_cycle_detection(tmp_path: Path) -> None:
    engine = PipelineComposerEngine(
        steps=[
            StepSpec("a", _ok(), depends_on=("b",)),
            StepSpec("b", _ok(), depends_on=("a",)),
        ],
        trigger={"on_demand": True},
        config={},
        name="cycle",
    )
    with pytest.raises(ValueError, match="cycle"):
        await engine.run(input_data={}, output_dir=tmp_path)


@pytest.mark.asyncio
async def test_generic_result_passthrough(tmp_path: Path) -> None:
    """oservi passes transaction-specific result through unchanged."""
    async def tx(config, input_data, output_dir, *, on_step=None):
        return {
            "status": "completed",
            "error": None,
            "_enabled_pillars": ["fingerprint", "cost"],
            "result": {"drift_score": 0.02, "clip_path": "/tmp/x.mp4"},
            "fingerprint": "abc",
            "decision_trail": {"x": 1},
            "cost": 1.5,
            "report": None,
        }

    tx.__module__ = "omodul.test"
    engine = PipelineComposerEngine(
        steps=[StepSpec("v2v", tx)],
        trigger={"on_demand": True},
        config={},
        name="passthrough",
    )
    out = await engine.run(input_data={}, output_dir=tmp_path)
    result = out["steps"]["v2v"]["result"]
    assert result["status"] == "completed"
    assert result["result"]["drift_score"] == 0.02
    assert result["cost"] == 1.5


@pytest.mark.asyncio
async def test_step_exception_is_generic_failure(tmp_path: Path) -> None:
    engine = PipelineComposerEngine(
        steps=[StepSpec("a", _boom())],
        trigger={"on_demand": True},
        config={},
        name="exception",
    )
    out = await engine.run(input_data={}, output_dir=tmp_path)
    assert out["status"] == "failed"
    assert out["steps"]["a"]["error"]["code"] == "STEP_EXCEPTION"


@pytest.mark.asyncio
async def test_on_step_callback_receives_envelope(tmp_path: Path) -> None:
    events: list[dict] = []

    engine = PipelineComposerEngine(
        steps=[StepSpec("a", _ok()), StepSpec("b", _ok(), depends_on=("a",))],
        trigger={"on_demand": True},
        config={},
        name="cb",
    )
    await engine.run(input_data={}, output_dir=tmp_path, on_step=events.append)
    assert len(events) == 2
    assert {e["step_id"] for e in events} == {"a", "b"}


@pytest.mark.asyncio
async def test_no_business_state_in_engine(tmp_path: Path) -> None:
    """oservi engine exposes no HEVI business attributes."""
    engine = PipelineComposerEngine(
        steps=[StepSpec("a", _ok())],
        trigger={"on_demand": True},
        config={},
        name="pure",
    )
    forbidden = (
        "project_id", "user_id", "artifact", "presentation",
        "repair_incident", "production_run", "provider_call_record",
    )
    for name in forbidden:
        assert not hasattr(engine, name)
