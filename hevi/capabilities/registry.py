"""Hevi capability registry per CAPABILITY_CONTRACT.md.
Provides register, get, list, resolve for capabilities including qa.kids_gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json

from hevi.quality.kids_gate import kids_gate_workflow
from hevi.director_lens.brief import autofill, DirectorBrief
from hevi.director_lens.gate import director_check_workflow
from hevi.director_lens.render import render_comparison_package
from hevi.director_lens.review import generate_review_html

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


# ── Director Lens Capabilities ──

def _render_director_brief(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    prompt = params.get("prompt", "小球学弹跳")
    line = params.get("line", "explainer")
    brief = autofill(prompt, line=line, duration_s=duration, aspect=aspect, seed=seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{brief.id}.json"
    brief.save(p)
    return CapabilityResult(
        mp4=None,
        duration_s=duration,
        qa={"brief_id": brief.id, "path": str(p), "status": "success"}
    )


register(Capability(
    name="director_brief",
    kind="shot",
    aspects=["16:9", "9:16", "1:1"],
    params_schema={"type": "object"},
    cpu_cost_hint=0.05,
    render=_render_director_brief,
    description="线路无关的 DirectorBrief 生成与自动补全",
    line="director"
))


def _render_director_check(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    brief_path = params.get("brief_path")
    if brief_path and Path(brief_path).exists():
        brief = DirectorBrief.load(brief_path)
    else:
        brief = autofill(params.get("prompt", "小球学弹跳"), line=params.get("line", "explainer"), duration_s=duration, aspect=aspect, seed=seed)
    report = director_check_workflow(brief, video_path=params.get("video_path"))
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "director_check_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=duration,
        qa=report
    )


register(Capability(
    name="director_check",
    kind="line",
    aspects=["16:9", "9:16", "1:1"],
    params_schema={"type": "object"},
    cpu_cost_hint=0.1,
    render=_render_director_check,
    description="全线通用的出片前自检闸门 (PPT同步/静止冻结/拍点对齐/声画对齐等)",
    line="director"
))


def _render_motion_director(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    prompt = params.get("prompt", "小球学弹跳")
    line = params.get("line", "explainer")
    brief = autofill(prompt, line=line, duration_s=duration, aspect=aspect, seed=seed)
    comparison = render_comparison_package(brief, out_dir)
    html_path = generate_review_html(brief, comparison, out_dir / f"{brief.id}_review.html")
    return CapabilityResult(
        mp4=comparison["director_version"]["mp4"],
        duration_s=duration,
        sha256=comparison["director_version"]["sha256"],
        qa={"comparison": comparison, "review_html": str(html_path)}
    )


register(Capability(
    name="motion_director",
    kind="shot",
    aspects=["16:9", "9:16", "1:1"],
    params_schema={"type": "object"},
    cpu_cost_hint=0.5,
    render=_render_motion_director,
    description="动效导演层完整渲染 pipeline (导演版 vs 基线版 + 逐帧审片 HTML)",
    line="director"
))

