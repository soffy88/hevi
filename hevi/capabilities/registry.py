"""Hevi capability registry per CAPABILITY_CONTRACT.md.
Provides register, get, list, resolve for capabilities including qa.kids_gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json

from hevi.quality.kids_gate import kids_gate_workflow, kids_gate_extended
from hevi.kids import manifest_adapter
from hevi.kids import review_sheet as review_sheet_mod
from hevi.kids import render_local
from hevi.kids import annotation_revision


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


# ── K2 新增能力注册 ─────────────────────────────────────────────────


def _render_kids_gate_extended(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    video_path = Path(params.get("video_path", ""))
    srt_path = Path(params.get("srt_path")) if params.get("srt_path") else None
    meta_path = Path(params.get("metadata_path")) if params.get("metadata_path") else None
    manifest_path = params.get("manifest_path")
    manifest = manifest_adapter.load_manifest(manifest_path) if manifest_path else None
    report = kids_gate_extended(video_path, srt_path=srt_path, metadata_path=meta_path, manifest=manifest)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "kids_gate_extended_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        mp4=str(video_path) if video_path.exists() else None,
        duration_s=duration,
        qa=report,
    )


register(Capability(
    name="qa.kids_gate.extended",
    kind="line",
    aspects=["16:9", "9:16"],
    params_schema={"type": "object"},
    cpu_cost_hint=0.2,
    render=_render_kids_gate_extended,
    description="幼儿动漫安全与节奏质检闸门 + §3.6 续作 QC（连续性/调色/转场/口语语言）",
    line="anime",
))


def _render_review_sheet(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    manifest_path = params.get("manifest_path")
    if not manifest_path:
        raise RuntimeError("review_sheet 需要 manifest_path")
    manifest = manifest_adapter.load_manifest(manifest_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = review_sheet_mod.render_both_aspects(manifest, out_dir, base_name=params.get("base_name", "review_sheet"))
    shas = {a: review_sheet_mod.review_sheet_sha256(p) for a, p in paths.items()}
    return CapabilityResult(
        png=str(paths.get(aspect, next(iter(paths.values())))),
        duration_s=duration,
        qa={"paths": {a: str(p) for a, p in paths.items()}, "sha256": shas},
    )


register(Capability(
    name="kids.review_sheet",
    kind="overlay",
    aspects=["16:9", "9:16"],
    params_schema={"type": "object", "required": ["manifest_path"]},
    cpu_cost_hint=0.5,
    render=_render_review_sheet,
    description="分镜审稿表网格 PNG 渲染（每格镜号/时长/台词/机位/景别/缩略图）",
    line="anime",
))


def _render_local_episode(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    manifest_path = params.get("manifest_path")
    if not manifest_path:
        raise RuntimeError("render_local 需要 manifest_path")
    manifest = manifest_adapter.load_manifest(manifest_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    w, h = (720, 1280) if aspect == "9:16" else (1280, 720)
    out = out_dir / "local_episode.mp4"
    info = render_local.render_episode(manifest, out, seed=seed, width=w, height=h)
    return CapabilityResult(
        mp4=str(out), duration_s=info["total_duration"], sha256=info["sha256"], qa=info,
    )


register(Capability(
    name="kids.render_local",
    kind="shot",
    aspects=["16:9", "9:16"],
    params_schema={"type": "object", "required": ["manifest_path"]},
    cpu_cost_hint=2.0,
    render=_render_local_episode,
    description="本地 CPU 渲染试点片（真实 ffmpeg，无付费 API，确定性可复现）",
    line="anime",
))


def _render_annotation_patch(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    """从标注请求构建确定性 ShotSpecPatch（注册点，便于产线按名调用）。"""
    manifest_path = params.get("manifest_path")
    ann = params.get("annotation") or {}
    if not manifest_path:
        raise RuntimeError("annotation_revision 需要 manifest_path")
    manifest = manifest_adapter.load_manifest(manifest_path)
    shot_index = int(ann.get("shot_index", 0))
    marks = [
        annotation_revision.AnnotationMark(
            kind=m["kind"], nx=float(m["nx"]), ny=float(m["ny"]),
            nw=float(m.get("nw", 0.0)), nh=float(m.get("nh", 0.0)),
            direction=m.get("direction"), note=m.get("note"),
        )
        for m in ann.get("marks", [])
    ]
    inp = annotation_revision.AnnotationInput(
        shot_index=shot_index,
        from_revision=int(ann.get("from_revision", 0)),
        marks=marks,
        source_time_ms=[float(t) for t in ann.get("source_time_ms", [])],
        authoritative_source=ann.get("authoritative_source"),
    )
    patch = annotation_revision.build_patch(manifest, inp)
    out_dir.mkdir(parents=True, exist_ok=True)
    patch_path = out_dir / f"patch_S{shot_index}.json"
    patch_path.write_text(json.dumps(patch.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        png=None, duration_s=duration, sha256=patch.sha256(),
        qa={"patch": patch.to_dict(), "path": str(patch_path)},
    )


register(Capability(
    name="kids.annotation_revision",
    kind="line",
    aspects=["16:9", "9:16"],
    params_schema={"type": "object", "required": ["manifest_path"]},
    cpu_cost_hint=0.1,
    render=_render_annotation_patch,
    description="帧标注 → 确定性 ShotSpecPatch（§3.5 映射）",
    line="anime",
))
