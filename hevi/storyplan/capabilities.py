"""Hevi 能力注册表（遵循 CAPABILITY_CONTRACT.md）与 StoryPlan 能力注册。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json

from hevi.storyplan.autofill import autofill_story_plan
from hevi.storyplan.check import run_story_check
from hevi.storyplan.take_select import select_best_take, TakeCandidate


@dataclass
class CapabilityResult:
    mp4: str | None = None
    png: str | None = None
    wav: str | None = None
    duration_s: float = 0.0
    sha256: str = ""
    qa: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class Capability:
    name: str
    kind: str
    aspects: list[str]
    params_schema: dict[str, Any]
    cpu_cost_hint: float
    render: Any
    description: str = ""
    line: str = "storyplan"

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """严格校验输入参数，非法参数抛出 ValueError 拒绝。"""
        if not isinstance(params, dict):
            raise ValueError("params must be a dictionary")
        if self.name == "story_plan":
            topic = params.get("topic")
            if topic is not None and not isinstance(topic, str):
                raise ValueError("topic must be a string")
        elif self.name == "story_check":
            plan = params.get("plan")
            if plan is not None and not isinstance(plan, dict):
                raise ValueError("plan must be a dictionary")
        elif self.name == "take_select":
            cands = params.get("candidates")
            if cands is not None:
                if not isinstance(cands, list):
                    raise ValueError("candidates must be a list")
                for c in cands:
                    if not isinstance(c, dict) or "take_id" not in c or "video_path" not in c:
                        raise ValueError("each candidate must be a dict with take_id and video_path")
        return params


_REGISTRY: dict[str, Capability] = {}


def register(cap: Capability) -> Capability:
    _REGISTRY[cap.name] = cap
    return cap


def get(name: str) -> Capability:
    cap = _REGISTRY.get(name)
    if not cap:
        raise RuntimeError(f"Unknown capability: {name}")
    return cap


def resolve(name: str) -> Capability:
    return get(name)


def list_capabilities(kind: str | None = None, aspect: str | None = None) -> list[Capability]:
    out = []
    for c in _REGISTRY.values():
        if kind and c.kind != kind:
            continue
        if aspect and aspect not in c.aspects:
            continue
        out.append(c)
    return out


list = list_capabilities


# ── 注册 StoryPlan 相关核心能力 ──────────────────────────────────────

def _render_story_plan(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    topic = str(params.get("topic", "小水滴去哪儿了"))
    plan = autofill_story_plan(topic, aspect=aspect)
    out_json = out_dir / "story_plan.json"
    out_json.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=plan.duration_sec,
        qa={"status": "succeeded"},
        payload=plan.model_dump(),
    )


def _render_story_check(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    plan_data = params.get("plan")
    if isinstance(plan_data, dict):
        from hevi.storyplan.model import StoryPlan
        plan = StoryPlan(**plan_data)
    else:
        plan = autofill_story_plan("小水滴去哪儿了", aspect=aspect)
    report = run_story_check(plan)
    return CapabilityResult(
        duration_s=plan.duration_sec,
        qa={"passed": report.passed},
        payload=report.model_dump(),
    )


def _render_take_select(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    cands_raw = params.get("candidates", [{"take_id": "t1", "video_path": "dummy.mp4", "duration_sec": 5.0}])
    cands = [TakeCandidate(**c) for c in cands_raw]
    criteria = str(params.get("acceptance_criteria", "验收点通过"))
    best, all_res = select_best_take(cands, criteria)
    return CapabilityResult(
        duration_s=duration,
        qa={"selected": best.take_id},
        payload={"best": best.model_dump(), "all": [r.model_dump() for r in all_res]},
    )


register(
    Capability(
        name="story_plan",
        kind="shot",
        aspects=["16:9", "9:16", "1:1"],
        params_schema={"type": "object", "properties": {"topic": {"type": "string"}}},
        cpu_cost_hint=0.1,
        render=_render_story_plan,
        description="一句话自动补全叙事/分镜/时间线三层结构 StoryPlan",
    )
)

register(
    Capability(
        name="story_check",
        kind="shot",
        aspects=["16:9", "9:16", "1:1"],
        params_schema={"type": "object", "properties": {"plan": {"type": "object"}}},
        cpu_cost_hint=0.1,
        render=_render_story_check,
        description="StoryPlan 结构自检门 (钩子、声画对齐、冗余、六项必填、闭环、幼儿安全)",
    )
)

register(
    Capability(
        name="take_select",
        kind="shot",
        aspects=["16:9", "9:16", "1:1"],
        params_schema={"type": "object", "properties": {"candidates": {"type": "array"}}},
        cpu_cost_hint=0.1,
        render=_render_take_select,
        description="选段器 take_select：多候选 take 按帧评分与子区间选中",
    )
)

def _render_storyplan_critique_local(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    from hevi.storyplan.critique import render_storyplan_critique
    res = render_storyplan_critique(params, out_dir, duration=duration, aspect=aspect, seed=seed)
    return CapabilityResult(
        mp4=str(res.mp4) if res.mp4 else None,
        png=str(res.png) if res.png else None,
        wav=str(res.wav) if res.wav else None,
        duration_s=res.duration_s,
        sha256=res.sha256,
        qa=res.qa,
        payload=res.payload if hasattr(res, "payload") else {},
    )

register(
    Capability(
        name="storyplan.critique",
        kind="shot",
        aspects=["16:9", "9:16", "1:1"],
        params_schema={"type": "object", "properties": {"plan": {"type": "object"}, "topic": {"type": "string"}, "auto_revise": {"type": "boolean"}}},
        cpu_cost_hint=0.2,
        render=_render_storyplan_critique_local,
        description="剧本自审轮：挑剔观众+动画导演双重视角批判与自动修订",
    )
)
