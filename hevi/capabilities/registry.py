"""Hevi capability registry per CAPABILITY_CONTRACT.md.
Provides register, get, list, resolve for capabilities including qa.kids_gate,
kids.story_gate and kids.consistency_manifest.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema

from hevi.quality.kids_gate import kids_gate_workflow
from hevi.kids.story_gate import kids_story_gate, gate_json
from hevi.kids.consistency_manifest import validate_manifest, canonical_json


class CapabilityError(RuntimeError):
    """能力参数非法或渲染失败时抛出的明确异常。"""
    pass


@dataclass
class CapabilityResult:
    mp4: str | None = None
    png: str | None = None
    wav: str | None = None
    duration_s: float = 0.0
    sha256: str = ""
    qa: dict[str, Any] = field(default_factory=dict)


@dataclass
class Capability:
    name: str
    kind: str
    aspects: list[str]
    params_schema: dict[str, Any]
    cpu_cost_hint: float
    render: Any
    description: str = ""
    line: str = ""

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            jsonschema.validate(instance=params, schema=self.params_schema)
        except jsonschema.ValidationError as exc:
            raise CapabilityError(f"Capability '{self.name}' params validation failed: {exc.message} at {list(exc.path)}") from exc
        return params


_REGISTRY: dict[str, Capability] = {}


def register(cap: Capability) -> Capability:
    # 包装 render 函数，使其在执行前自动校验参数
    orig_render = cap.render
    def wrapped_render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
        cap.validate_params(params)
        return orig_render(params, out_dir, duration=duration, aspect=aspect, seed=seed)
    cap.render = wrapped_render
    _REGISTRY[cap.name] = cap
    return cap


def get(name: str) -> Capability:
    cap = _REGISTRY.get(name)
    if not cap:
        raise CapabilityError(f"Unknown capability: {name}")
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


# Register qa.kids_gate
def _render_kids_gate(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    video_path = Path(params.get("video_path", ""))
    srt_path = Path(params.get("srt_path")) if params.get("srt_path") else None
    meta_path = Path(params.get("metadata_path")) if params.get("metadata_path") else None
    
    report = kids_gate_workflow(video_path, srt_path=srt_path, metadata_path=meta_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "kids_gate_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    
    return CapabilityResult(
        mp4=str(video_path) if video_path.exists() else None,
        duration_s=duration,
        qa=report
    )


register(Capability(
    name="qa.kids_gate",
    kind="line",
    aspects=["16:9", "9:16"],
    params_schema={"type": "object"},
    cpu_cost_hint=0.1,
    render=_render_kids_gate,
    description="幼儿动漫安全与节奏质检闸门",
    line="anime"
))


# Register kids.story_gate
_STORY_GATE_PARAMS = {
    "type": "object",
    "properties": {
        "story": {
            "type": "object",
            "properties": {
                "logline": {"type": "string"},
                "theme": {"type": "string"},
                "spoken_language": {"type": "string"},
                "fixed_characters": {"type": "array", "items": {"type": "string"}},
                "beats": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string"},
                            "text": {"type": "string"},
                            "emotion": {"type": "string"},
                            "transition": {"type": "string"},
                        },
                        "required": ["kind", "text"],
                    },
                },
            },
            "required": ["beats"],
        },
    },
    "required": ["story"],
}


def _render_kids_story_gate(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    from pydantic import ValidationError

    story = params.get("story", {})
    try:
        report = kids_story_gate(story)
        qa = report.to_dict()
    except ValidationError as exc:
        qa = {"status": "FAIL", "findings": [], "metrics": {}, "error": str(exc)}
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "kids_story_gate_report.json"
    report_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(duration_s=duration, qa=qa)


register(Capability(
    name="kids.story_gate",
    kind="line",
    aspects=["16:9", "9:16"],
    params_schema=_STORY_GATE_PARAMS,
    cpu_cost_hint=0.0,
    render=_render_kids_story_gate,
    description="幼儿故事闸门：6 节拍结构 + 因果转场比 + 单主题 + 固定角色一致性",
    line="anime",
))


# Register kids.consistency_manifest (schema + validation)
_MANIFEST_PARAMS = {
    "type": "object",
    "properties": {
        "manifest": {"type": "object"},
    },
    "required": ["manifest"],
}


def _render_kids_consistency_manifest(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    from pydantic import ValidationError

    manifest = params.get("manifest", {})
    try:
        report = validate_manifest(manifest)
        qa = report.to_dict()
    except ValidationError as exc:
        qa = {"status": "FAIL", "findings": [], "errors": [str(exc)], "error": str(exc)}
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "kids_consistency_manifest_report.json"
    report_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(duration_s=duration, qa=qa)


register(Capability(
    name="kids.consistency_manifest",
    kind="line",
    aspects=["16:9", "9:16"],
    params_schema=_MANIFEST_PARAMS,
    cpu_cost_hint=0.0,
    render=_render_kids_consistency_manifest,
    description="幼儿一致性清单：schema 校验 + 与 ShotSpec 双向绑定",
    line="anime",
))
