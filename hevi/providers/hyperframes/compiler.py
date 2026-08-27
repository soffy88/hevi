"""HyperFrames 构图编译 —— cues/时间线 → HTML(data-* 时码) + DESIGN.md。

合同对齐 OpenMontage / HyperFrames v0.7: class=clip + data-start/data-duration。
不依赖 hyperframes npm 包;CLI 不可用时 provider 用同一份 HTML 抽卡回退。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from typing import Any


@dataclass
class HyperClip:
    start_s: float
    duration_s: float
    text: str
    kind: str = "title"  # title | card | quote | end


@dataclass
class HyperComposition:
    title: str
    width: int = 1920
    height: int = 1080
    fps: int = 30
    clips: list[HyperClip] = field(default_factory=list)
    css_vars: dict[str, str] = field(default_factory=dict)
    design_md: str = ""

    @property
    def duration_s(self) -> float:
        if not self.clips:
            return 0.0
        return max(c.start_s + c.duration_s for c in self.clips)


def clips_from_payload(payload: dict[str, Any]) -> list[HyperClip]:
    """从 edit_plan / cues / 纯文本抽出 clips。"""
    cuts = []
    plan = payload.get("edit_plan")
    if isinstance(plan, dict):
        cuts = list(plan.get("cuts") or [])
    if not cuts and isinstance(payload.get("cues"), list):
        cuts = list(payload["cues"])
    if not cuts:
        lines = payload.get("script_lines") or []
        cursor = 0.0
        clips: list[HyperClip] = []
        title = str(payload.get("title") or payload.get("topic") or "HEVI")
        clips.append(HyperClip(0.0, 2.4, title, kind="title"))
        cursor = 2.4
        for i, line in enumerate(lines[:8]):
            text = str(line.get("text") or line) if isinstance(line, dict) else str(line)
            if not text.strip():
                continue
            dur = max(2.2, min(6.0, len(text) / 10.0))
            kind = "end" if i == len(lines) - 1 else "card"
            clips.append(HyperClip(cursor, dur, text.strip(), kind=kind))
            cursor += dur
        if len(clips) == 1:
            clips.append(HyperClip(cursor, 2.0, title, kind="end"))
        return clips

    clips = []
    cursor = 0.0
    for i, cut in enumerate(cuts):
        if not isinstance(cut, dict):
            continue
        if str(cut.get("action") or "keep") == "drop":
            continue
        text = str(cut.get("text") or cut.get("label") or cut.get("title") or "").strip()
        if not text:
            continue
        raw_start = cut.get("start_s")
        raw_duration = cut.get("duration_s")
        start = float(raw_start) if isinstance(raw_start, (int, float, str)) else cursor
        dur = float(raw_duration) if isinstance(raw_duration, (int, float, str)) else 3.0
        kind = "title" if i == 0 else "card"
        clips.append(HyperClip(start, max(dur, 0.8), text, kind=kind))
        cursor = start + max(dur, 0.8)
    return clips


def compile_composition(payload: dict[str, Any]) -> HyperComposition:
    from hevi.providers.hyperframes.style import style_bridge

    title = str(payload.get("title") or payload.get("topic") or "HEVI")
    css_vars, design_md = style_bridge(payload.get("playbook"), payload.get("edit_decisions"))
    width = int(payload.get("width") or 1920)
    height = int(payload.get("height") or 1080)
    fps = int(payload.get("fps") or 30)
    constraint_note = ""
    raw_graph = payload.get("constraint_graph")
    if raw_graph:
        # Every provider-facing path that receives a canonical graph goes
        # through the same compiler.  The rendered composition keeps the
        # coverage summary in DESIGN.md so a dashboard can audit consumption.
        from hevi.constraints import ConstraintGraph, ProviderCapabilities, compile_graph

        graph = (
            raw_graph
            if isinstance(raw_graph, ConstraintGraph)
            else ConstraintGraph.model_validate(raw_graph)
        )
        compiled = compile_graph(
            graph,
            ProviderCapabilities(provider_id="hyperframes"),
        )
        constraint_note = (
            "\n\n## CONSTRAINT_COVERAGE\n"
            f"compiled={graph.coverage.compiled_constraints} "
            f"consumed={graph.coverage.adapter_consumed_constraints} "
            f"unsupported={graph.coverage.unsupported_constraints} "
            f"silent_drops={graph.coverage.silent_drops}\n"
            f"unsupported_ids={','.join(item.id for item in compiled.unsupported)}"
        )
        design_md = f"{design_md}{constraint_note}"
    return HyperComposition(
        title=title,
        width=width,
        height=height,
        fps=fps,
        clips=clips_from_payload(payload),
        css_vars=css_vars,
        design_md=design_md,
    )


def render_html(comp: HyperComposition) -> str:
    """渲成 hyperframes CLI 可直接渲染的项目 index.html。

    根元素带 data-composition-id + data-duration + data-width/height。
    data-no-timeline 跳过 CLI 对 GSAP 时间线的 45s 轮询等待(纯 CSS/clip 构图
    不需要 window.__timelines)。
    """
    vars_css = "\n".join(f"    {k}: {v};" for k, v in comp.css_vars.items())
    clips_html = []
    for i, clip in enumerate(comp.clips, start=1):
        tag = "h1" if clip.kind == "title" else "p"
        clips_html.append(
            "    "
            f'<section class="clip clip-{escape(clip.kind)}" '
            f'data-start="{clip.start_s:.2f}" '
            f'data-duration="{clip.duration_s:.2f}" '
            f'data-track-index="{i}">'
            f"<{tag}>{escape(clip.text)}</{tag}></section>"
        )
    empty = (
        '    <section class="clip" data-start="0" data-duration="3">'
        "<h1>HEVI</h1></section>"
    )
    body = "\n".join(clips_html) or empty
    total_s = comp.duration_s or 3.0
    return (
        "<!doctype html>\n<html lang=\"zh-CN\">\n<head>\n"
        f'  <meta charset="utf-8"/>\n  <title>{escape(comp.title)}</title>\n'
        "  <style>\n"
        f"    :root {{\n{vars_css}\n    }}\n"
        "    html,body{margin:0;height:100%;background:var(--color-bg);"
        "color:var(--color-fg);"
        "font-family:var(--font-heading),sans-serif;overflow:hidden}\n"
        "    .clip{position:absolute;inset:0;display:flex;"
        "align-items:center;justify-content:center;"
        "padding:8vw;text-align:center}\n"
        "    h1{font-size:clamp(32px,6vw,84px);letter-spacing:.04em;margin:0}\n"
        "    p{font-size:clamp(22px,3.4vw,48px);line-height:1.35;margin:0;max-width:20em}\n"
        "  </style>\n</head>\n<body>\n"
        "  <div id=\"root\" "
        f'data-composition-id="main" data-start="0" '
        f'data-duration="{total_s:.2f}" '
        f'data-width="{comp.width}" data-height="{comp.height}" '
        'data-no-timeline>\n'
        f"{body}\n"
        "  </div>\n"
        "</body>\n</html>\n"
    )
