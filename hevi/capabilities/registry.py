"""Hevi capability registry per CAPABILITY_CONTRACT.md.
Provides register, get, list, resolve for capabilities including qa.kids_gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json

from hevi.quality.kids_gate import kids_gate_workflow

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

import hevi.capabilities.anatomy_explainer
