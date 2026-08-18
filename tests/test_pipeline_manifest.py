"""pipeline manifest 测试 —— YAML 化 + checkpoint 断点续跑(差距 A2)。

覆盖: YAML 解析/校验(重名/空)/fn 白名单/不可调用/异步契约/obase.Pipeline 构造/
断点续跑(PauseRequested → resume 从暂停阶段重跑)/BudgetExceeded 熔断/重试。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from obase import FS, PauseRequested, StageContractViolation
from obase.exceptions import BudgetExceeded

from hevi.pipeline.manifest import (
    PipelineManifest,
    build_pipeline,
    load_manifest,
    parse_manifest,
    resolve_stage_fn,
    run_with_checkpoint,
)

logger = logging.getLogger(__name__)

_GOOD_YAML = """
name: quick_video
stages:
  - name: script
    fn: hevi.pipeline._test_stages:stage_script
    input_keys: [topic]
    output_keys: [script]
  - name: assemble
    fn: hevi.pipeline._test_stages:stage_assemble
    input_keys: [script]
    output_keys: [video_path]
"""


def _manifest(tmp_path: Path, yaml_text: str) -> Path:
    p = tmp_path / "manifest.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    return p


def test_parse_manifest_ok():
    m = parse_manifest(_GOOD_YAML)
    assert m.name == "quick_video"
    assert [s.name for s in m.stages] == ["script", "assemble"]
    assert m.stages[0].input_keys == ["topic"]


def test_parse_manifest_requires_stages():
    with pytest.raises(ValidationError):
        parse_manifest("name: x\nstages: []")


def test_parse_manifest_duplicate_stage_names():
    dup = _GOOD_YAML.replace("script", "same").replace("assemble", "same", 1)
    with pytest.raises(ValidationError):
        parse_manifest(dup)


def test_parse_manifest_not_mapping():
    with pytest.raises(ValueError):
        parse_manifest("- a\n- b")


def test_load_manifest_from_file(tmp_path: Path):
    path = _manifest(tmp_path, _GOOD_YAML)
    m = load_manifest(path)
    assert m.name == "quick_video"


def test_resolve_stage_fn_allowlist():
    with pytest.raises(ValueError, match="allowlist"):
        resolve_stage_fn("os.system:system")
    with pytest.raises(ValueError, match="allowlist"):
        resolve_stage_fn("hevi_evil.hack:run")
    with pytest.raises(ValueError, match="module:function"):
        resolve_stage_fn("no_colon_here")


def test_resolve_stage_fn_import_error():
    with pytest.raises(ValueError, match="cannot import"):
        resolve_stage_fn("hevi.nonexistent_module_xyz:run")


def test_resolve_stage_fn_not_callable():
    with pytest.raises(ValueError, match="not callable"):
        resolve_stage_fn("hevi.pipeline.manifest:NOT_A_FUNCTION")


def test_resolve_stage_fn_not_async():
    with pytest.raises(ValueError, match="async"):
        resolve_stage_fn("hevi.pipeline.manifest:load_manifest")


def test_build_pipeline_contract():
    m = parse_manifest(_GOOD_YAML)
    pipeline = build_pipeline(m)
    assert pipeline.name == "quick_video"
    assert len(pipeline.stages) == 2
    # stage func 是异步且返回 dict(obase Stage 契约)
    for stage in pipeline.stages:
        import inspect
        assert inspect.iscoroutinefunction(stage.func)


def test_run_pipeline_end_to_end():
    from obase import PauseRequested as _PR  # noqa: F401 (re-export 语义)

    async def main():
        m = parse_manifest(_GOOD_YAML)
        state = await run_with_checkpoint(m, {"topic": "sunset"})
        assert state.state == "completed"
        assert state.data["script"]["topic"] == "sunset"
        assert state.data["video_path"].endswith(".mp4")
        # input_keys 过滤: assemble 只收到 script
        assert "video_path" in state.data

    asyncio.run(main())


def test_run_pipeline_resume_after_pause(tmp_path: Path):
    """PauseRequested 阶段暂停后, 同 run_id resume 从暂停阶段重跑。"""

    async def main():
        from hevi.pipeline import _test_stages as ts

        ts.PAUSE_ONCE = {"pause_stage": True}
        manifest_yaml = """
name: paused_pipeline
stages:
  - name: first
    fn: hevi.pipeline._test_stages:stage_first
    output_keys: [first]
  - name: pause_stage
    fn: hevi.pipeline._test_stages:stage_pause_once
    output_keys: [paused]
  - name: last
    fn: hevi.pipeline._test_stages:stage_last
    output_keys: [done]
"""
        m = parse_manifest(manifest_yaml)
        run_id = "run-0001"
        s1 = await run_with_checkpoint(m, {"seed": 1}, run_id=run_id)
        assert s1.state == "paused"
        assert s1.paused_at_stage == "pause_stage"
        # resume: 从暂停阶段重跑, 前序阶段不重跑
        ts.PAUSE_ONCE = {"pause_stage": False}
        s2 = await run_with_checkpoint(m, run_id=run_id, resume=True)
        assert s2.state == "completed"
        assert s2.data["done"] is True
        # 前序 first 只跑过一次(未重跑)
        assert ts.CALLS["first"] == 1
        assert ts.CALLS["pause_stage"] == 2

    asyncio.run(main())


def test_run_pipeline_budget_exceeded():
    async def main():
        manifest_yaml = """
name: budget_pipeline
stages:
  - name: spend
    fn: hevi.pipeline._test_stages:stage_budget_exceed
    output_keys: [x]
"""
        m = parse_manifest(manifest_yaml)
        state = await run_with_checkpoint(m, {})
        assert state.state == "failed"
        assert any(e["type"] == "BudgetExceeded" for e in state.errors)

    asyncio.run(main())


def test_run_pipeline_retry_then_success():
    async def main():
        from hevi.pipeline import _test_stages as ts

        ts.FLAKY_ATTEMPTS = {"flaky": 3}  # 前两次失败, 第三次成功
        manifest_yaml = """
name: retry_pipeline
stages:
  - name: flaky
    fn: hevi.pipeline._test_stages:stage_flaky
    max_retries: 3
    retry_delay: 0.01
    output_keys: [ok]
"""
        m = parse_manifest(manifest_yaml)
        state = await run_with_checkpoint(m, {})
        assert state.state == "completed"
        assert state.data["ok"] is True
        assert ts.CALLS["flaky"] == 3

    asyncio.run(main())


def test_run_pipeline_stage_contract_violation_reraises():
    async def main():
        manifest_yaml = """
name: contract_pipeline
stages:
  - name: bad
    fn: hevi.pipeline._test_stages:stage_contract_violation
    output_keys: [x]
"""
        m = parse_manifest(manifest_yaml)
        with pytest.raises(StageContractViolation):
            await run_with_checkpoint(m, {})

    asyncio.run(main())
