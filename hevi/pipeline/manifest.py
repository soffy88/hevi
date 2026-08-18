"""pipeline_manifest —— 流水线 YAML manifest + checkpoint 断点续跑(3O obase 编排, 差距 A2)。

对标 OpenMontage 的 YAML pipeline manifest + checkpoint, 补 hevi 差距: 现有
longvideo_manifest 是**代码内**声明式 steps, 无 manifest 文件、无跨阶段 checkpoint。

落点: 直接复用 obase.orchestrator(Stage/RunState/run_pipeline) —— 其已支持
PauseRequested 暂停 + resume 断点续跑 + BudgetExceeded 熔断 + max_retries 重试。
本模块只补三件事:
  1. `PipelineManifest`(pydantic): YAML 文件 → 结构校验(flat stage 列表)
  2. `resolve_stage_fn(ref)`: "module:function" → 异步可调用(白名单校验, 见下)
  3. `build_pipeline` / `run_with_checkpoint`: manifest → obase.Pipeline → 执行
     (run_id 固定时可 resume 续跑, 与 RunState 落盘位置一致)

白名单(安全): manifest 文件可被项目外部编辑, 故 fn 引用只允许 hevi.* / omodul /
oskill / obase / oprim 模块; 白名单外的引用直接拒绝(manifest 校验失败)。

示例 manifest (yaml)::

    name: quick_video
    checkpoint_dir: .hevi_runs          # 缺省 obase.FS.working_dir
    stages:
      - name: script
        fn: hevi.quick.script_stage:run
        input_keys: [topic]
        output_keys: [script]
      - name: material
        fn: hevi.quick.material_stage:run
        input_keys: [script]
        output_keys: [materials]
      - name: assemble
        fn: hevi.quick.assemble_stage:run
        input_keys: [script, materials]
        output_keys: [video_path]
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any, Callable

import yaml
from pydantic import BaseModel, Field, field_validator

from obase import Pipeline, RunState, Stage, run_pipeline

logger = logging.getLogger(__name__)

# fn 引用白名单: 仅允许 3O 域与 hevi 域(manifest 可被外部编辑, 防止任意代码执行)。
_ALLOWED_MODULES = ("hevi.", "omodul.", "oskill.", "obase.", "oprim.")


class StageSpec(BaseModel):
    name: str
    fn: str  # "module:function"
    max_retries: int = 0
    retry_delay: float = 1.0
    input_keys: list[str] | None = None
    output_keys: list[str] | None = None


class PipelineManifest(BaseModel):
    """YAML manifest 的结构化视图。"""

    name: str
    checkpoint_dir: str | None = None
    stages: list[StageSpec] = Field(min_length=1)

    @field_validator("stages")
    @classmethod
    def _unique_stage_names(cls, v: list[StageSpec]) -> list[StageSpec]:
        names = [s.name for s in v]
        if len(names) != len(set(names)):
            raise ValueError("stage names must be unique")
        return v


# ---------------------------------------------------------------------------
# 加载/校验(纯函数, 可单测)
# ---------------------------------------------------------------------------


def parse_manifest(text: str) -> PipelineManifest:
    """YAML 文本 → PipelineManifest(校验失败抛 pydantic ValidationError)。"""
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("manifest must be a mapping")
    return PipelineManifest(**data)


def load_manifest(path: Path) -> PipelineManifest:
    return parse_manifest(path.read_text(encoding="utf-8"))


def resolve_stage_fn(ref: str) -> Callable[..., Any]:
    """解析 "module:function" → 可调用。白名单外/不可调用/非异步 → ValueError。"""
    if ":" not in ref:
        raise ValueError(f"fn ref must be 'module:function', got {ref!r}")
    module_name, func_name = ref.rsplit(":", 1)
    if not module_name.startswith(_ALLOWED_MODULES):
        raise ValueError(
            f"fn ref module {module_name!r} not in allowlist "
            f"{_ALLOWED_MODULES}"
        )
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ValueError(f"cannot import module {module_name!r}: {exc}") from exc
    fn = getattr(module, func_name, None)
    if not callable(fn):
        raise ValueError(f"{ref!r} is not callable")
    if not hasattr(fn, "__await__") and not _is_async(fn):
        raise ValueError(f"{ref!r} is not an async callable (obase Stage requires coroutine)")
    return fn


def _is_async(fn: Callable[..., Any]) -> bool:
    import inspect

    return inspect.iscoroutinefunction(fn)


# ---------------------------------------------------------------------------
# 构造与执行
# ---------------------------------------------------------------------------


def build_pipeline(manifest: PipelineManifest) -> Pipeline:
    """manifest → obase.Pipeline(每个 stage 包装为 (data, ctx) -> dict 契约)。"""
    stages: list[Stage] = []
    for spec in manifest.stages:
        fn = resolve_stage_fn(spec.fn)
        stages.append(
            Stage(
                name=spec.name,
                func=fn,
                max_retries=spec.max_retries,
                retry_delay=spec.retry_delay,
                input_keys=spec.input_keys,
                output_keys=spec.output_keys,
            )
        )
    return Pipeline(name=manifest.name, stages=stages)


async def run_with_checkpoint(
    manifest: PipelineManifest,
    initial_data: dict[str, Any] | None = None,
    *,
    run_id: str | None = None,
    resume: bool = False,
    trail: Any = None,
    cost: Any = None,
) -> RunState:
    """执行 manifest 流水线, 支持同 run_id 断点续跑(resume=True)。

    语义与 obase.run_pipeline 一致: PauseRequested → paused(续跑从暂停阶段重跑);
    BudgetExceeded → failed; StageContractViolation → 上抛; 其余异常按 max_retries 重试。
    """
    pipeline = build_pipeline(manifest)
    return await run_pipeline(
        pipeline,
        initial_data=initial_data,
        run_id=run_id,
        resume=resume,
        trail=trail,
        cost=cost,
    )


__all__ = [
    "PipelineManifest",
    "StageSpec",
    "build_pipeline",
    "load_manifest",
    "parse_manifest",
    "resolve_stage_fn",
    "run_with_checkpoint",
]
