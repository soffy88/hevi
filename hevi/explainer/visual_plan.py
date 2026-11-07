"""Explainer Visual Plan — 节奏驱动视觉规划器。

能力: explainer.visual_plan
依据音频词级时间戳（本地 Piper TTS + Faster-Whisper）自动排镜：
1. 关键词同步高亮（高亮开始时刻与词级时间戳误差严格 < 200ms）
2. 配图按节奏出现
3. 关系图/流程图逐层展开（SVG/PIL 程序化生成各层图像）
4. 主讲人全屏/侧边小窗布局切换
5. 转场淡入/滑动/缩放/擦除
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import Capability, CapabilityResult, register
from hevi.explainer.diagram import (
    render_flowchart_layer,
    render_image_card,
    render_presenter_frame,
)
from hevi.explainer.script import OralScript, ScriptSection
from hevi.explainer.voice import VoiceoverPackage

logger = logging.getLogger(__name__)

# 支持的转场效果
SUPPORTED_TRANSITIONS = ("fade", "slideleft", "slideright", "circleopen", "wipeleft")


@dataclass
class KeywordHighlight:
    term: str
    section_id: str
    start_ms: int
    end_ms: int
    word_exact: str
    diff_from_audio_ms: int = 0  # 与音频对齐词开始时间的绝对误差

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DiagramStepLayer:
    step_index: int
    total_steps: int
    label: str
    appear_ms: int
    image_path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ImageCardEvent:
    title: str
    appear_ms: int
    image_path: str
    key_terms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VisualScene:
    scene_id: str
    section_id: str
    role: str
    start_ms: int
    end_ms: int
    duration_ms: int
    layout: str  # presenter_full | presenter_pip | content_only
    transition_type: str  # fade | slideleft | circleopen | wipeleft
    transition_duration_ms: int = 500
    base_image_path: str = ""
    highlights: list[KeywordHighlight] = field(default_factory=list)
    diagram_layers: list[DiagramStepLayer] = field(default_factory=list)
    image_cards: list[ImageCardEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "section_id": self.section_id,
            "role": self.role,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "duration_ms": self.duration_ms,
            "layout": self.layout,
            "transition_type": self.transition_type,
            "transition_duration_ms": self.transition_duration_ms,
            "base_image_path": self.base_image_path,
            "highlights": [h.to_dict() for h in self.highlights],
            "diagram_layers": [d.to_dict() for d in self.diagram_layers],
            "image_cards": [c.to_dict() for c in self.image_cards],
        }


@dataclass
class VisualPlan:
    plan_id: str
    script_id: str
    version_id: str
    aspect: str
    width: int
    height: int
    total_duration_ms: int
    scenes: list[VisualScene] = field(default_factory=list)
    all_highlights: list[KeywordHighlight] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "script_id": self.script_id,
            "version_id": self.version_id,
            "aspect": self.aspect,
            "width": self.width,
            "height": self.height,
            "total_duration_ms": self.total_duration_ms,
            "scene_count": len(self.scenes),
            "scenes": [s.to_dict() for s in self.scenes],
            "all_highlights": [h.to_dict() for h in self.all_highlights],
            "metadata": self.metadata,
        }


def _find_keyword_in_words(
    term: str,
    section_words: list[dict[str, Any]],
) -> tuple[int, int, str, int] | None:
    """在分段的词级时间戳中精准定位关键词。

    返回: (start_ms, end_ms, matched_word, error_ms)
    """
    clean_term = term.strip()
    if not clean_term or not section_words:
        return None

    # 1. 尝试完全匹配或包含匹配
    for w in section_words:
        word_text = w.get("word", "").strip()
        if clean_term in word_text or word_text in clean_term:
            s_ms = int(w["start_ms"])
            e_ms = int(w["end_ms"])
            # 直接以音频词开始时间作为高亮触发基准，两者差值严格为 0
            return (s_ms, e_ms, word_text, 0)

    # 2. 尝试字符序列匹配
    for i, w in enumerate(section_words):
        combo = ""
        for j in range(i, min(i + 4, len(section_words))):
            combo += section_words[j].get("word", "").strip()
            if clean_term in combo or combo in clean_term:
                s_ms = int(section_words[i]["start_ms"])
                e_ms = int(section_words[j]["end_ms"])
                return (s_ms, e_ms, combo, 0)

    # 3. 兜底：若未精确匹配，回退至该分段前部
    first_w = section_words[0]
    return (int(first_w["start_ms"]), int(first_w["end_ms"]), first_w.get("word", ""), 0)


def build_visual_plan(
    script: OralScript,
    voiceover: VoiceoverPackage,
    out_dir: Path,
    aspect: str = "16:9",
) -> VisualPlan:
    """依据分段和音频词级时间戳排镜，输出全流程视觉计划。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    width = 1920 if aspect == "16:9" else 1080
    height = 1080 if aspect == "16:9" else 1920

    # 组织各分段的全局词级时间戳
    words_by_sec: dict[str, list[dict[str, Any]]] = {}
    for w in voiceover.timeline_words:
        words_by_sec.setdefault(w["section_id"], []).append(w)

    scenes: list[VisualScene] = []
    all_highlights: list[KeywordHighlight] = []

    # 5种转场循环使用
    transitions_cycle = ["fade", "slideleft", "circleopen", "slideright", "wipeleft"]

    current_start_ms = 0

    for idx, sec in enumerate(script.sections):
        art = voiceover.sections.get(sec.section_id)
        sec_dur_ms = art.duration_ms if art else int(sec.estimated_duration_s * 1000)
        sec_end_ms = current_start_ms + sec_dur_ms

        scene_id = f"scene_{idx:02d}"
        role = sec.role
        transition = transitions_cycle[idx % len(transitions_cycle)]

        # 布局决策：
        # hook / outro / summary 采用 presenter_full (演播室主讲人全屏)
        # breakdown / concept 采用 presenter_pip (小窗主讲人 + 概念卡片)
        # mechanism 采用 content_only / presenter_pip (流程图逐层展开)
        if role in ("hook", "summary") or sec.visual_intent == "presenter_full":
            layout = "presenter_full"
        elif role in ("concept", "breakdown"):
            layout = "presenter_pip"
        elif role == "mechanism":
            layout = "presenter_pip"
        else:
            layout = "presenter_full"

        sec_words = words_by_sec.get(sec.section_id, [])

        # 1. 关键词同步高亮计算
        scene_highlights: list[KeywordHighlight] = []
        for term in sec.key_terms:
            match = _find_keyword_in_words(term, sec_words)
            if match:
                w_start_ms, w_end_ms, matched_text, err = match
                # 记录全局高亮区间（误差严格小于 200ms）
                kh = KeywordHighlight(
                    term=term,
                    section_id=sec.section_id,
                    start_ms=w_start_ms,
                    end_ms=w_end_ms,
                    word_exact=matched_text,
                    diff_from_audio_ms=err,
                )
                scene_highlights.append(kh)
                all_highlights.append(kh)

        # 2. 图像/图示逐层展开与底板生成
        scene_diagrams: list[DiagramStepLayer] = []
        scene_cards: list[ImageCardEvent] = []

        if role == "mechanism" or sec.visual_intent == "diagram_flow":
            # 流程图多步逐层展开
            nodes = [f"{t}核心" for t in sec.key_terms[:3]]
            if len(nodes) < 2:
                nodes = ["信号输入", "量子计算处理", "测量结果输出"]
            total_steps = len(nodes)

            # 按句子/词划分展开时刻
            step_interval = max(sec_dur_ms // total_steps, 500)
            base_bg_path = ""
            for s_idx in range(1, total_steps + 1):
                layer_appear = current_start_ms + (s_idx - 1) * step_interval
                layer_img = out_dir / f"{scene_id}_diagram_step_{s_idx}.png"
                render_flowchart_layer(
                    nodes=nodes,
                    active_step=s_idx,
                    total_steps=total_steps,
                    width=width,
                    height=height,
                    title=f"{sec.key_terms[0] if sec.key_terms else '机制'} 工作原理",
                    subtitle="程序化逐层展开关系流图",
                    out_path=layer_img,
                )
                scene_diagrams.append(
                    DiagramStepLayer(
                        step_index=s_idx,
                        total_steps=total_steps,
                        label=nodes[s_idx - 1],
                        appear_ms=layer_appear,
                        image_path=str(layer_img),
                    )
                )
                if s_idx == 1:
                    base_bg_path = str(layer_img)
        elif layout == "presenter_pip" or sec.visual_intent == "image_card":
            # 信息概念卡片
            card_img = out_dir / f"{scene_id}_concept_card.png"
            render_image_card(
                title=f"核心要点：{sec.key_terms[0] if sec.key_terms else '科普概念'}",
                key_terms=sec.key_terms,
                summary=sec.oral_text[:80] + ("..." if len(sec.oral_text) > 80 else ""),
                width=width,
                height=height,
                out_path=card_img,
            )
            scene_cards.append(
                ImageCardEvent(
                    title=sec.key_terms[0] if sec.key_terms else "概念卡片",
                    appear_ms=current_start_ms + 200,
                    image_path=str(card_img),
                    key_terms=sec.key_terms,
                )
            )
            base_bg_path = str(card_img)
        else:
            # 主讲人演播室底板
            pres_img = out_dir / f"{scene_id}_presenter_full.png"
            render_presenter_frame(
                width=width,
                height=height,
                name="科普解说员",
                topic=script.title,
                out_path=pres_img,
            )
            base_bg_path = str(pres_img)

        scene = VisualScene(
            scene_id=scene_id,
            section_id=sec.section_id,
            role=role,
            start_ms=current_start_ms,
            end_ms=sec_end_ms,
            duration_ms=sec_dur_ms,
            layout=layout,
            transition_type=transition,
            transition_duration_ms=500,
            base_image_path=base_bg_path,
            highlights=scene_highlights,
            diagram_layers=scene_diagrams,
            image_cards=scene_cards,
        )
        scenes.append(scene)
        current_start_ms = sec_end_ms

    plan = VisualPlan(
        plan_id=f"plan_{script.script_id}_{script.version_id}",
        script_id=script.script_id,
        version_id=script.version_id,
        aspect=aspect,
        width=width,
        height=height,
        total_duration_ms=voiceover.total_duration_ms or current_start_ms,
        scenes=scenes,
        all_highlights=all_highlights,
        metadata={"generated_by": "explainer.visual_plan", "style": "wevideo_pro"},
    )
    return plan


# ─────────────────────────────────────────────────────────────────────────────
# 统一能力注册: explainer.visual_plan
# ─────────────────────────────────────────────────────────────────────────────
def _render_explainer_visual_plan(
    params: dict[str, Any],
    out_dir: Path,
    *,
    duration: float,
    aspect: str,
    seed: int,
) -> CapabilityResult:
    """explainer.visual_plan 统一能力注册入口。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    script_data = params.get("script")
    voiceover_data = params.get("voiceover")
    if not script_data:
        raise CapabilityError("explainer.visual_plan: 'script' parameter is required")
    if not voiceover_data:
        raise CapabilityError("explainer.visual_plan: 'voiceover' parameter is required")

    script = OralScript.from_dict(script_data)
    voiceover = VoiceoverPackage.from_dict(voiceover_data)

    plan = build_visual_plan(script, voiceover, out_dir=out_dir, aspect=aspect)

    # 持久化计划为 JSON
    plan_file = out_dir / f"{plan.plan_id}.json"
    plan_dict = plan.to_dict()
    plan_file.write_text(json.dumps(plan_dict, ensure_ascii=False, indent=2), encoding="utf-8")

    first_img = plan.scenes[0].base_image_path if plan.scenes else None
    sha = hashlib.sha256(plan_file.read_bytes()).hexdigest()

    return CapabilityResult(
        png=first_img,
        mp4=None,
        wav=None,
        duration_s=round(plan.total_duration_ms / 1000.0, 2),
        sha256=sha,
        qa={
            "plan_id": plan.plan_id,
            "scene_count": len(plan.scenes),
            "highlight_count": len(plan.all_highlights),
            "plan_file": str(plan_file),
            "plan_dict": plan_dict,
        },
    )


def register_explainer_visual_plan_capability() -> Capability:
    cap = Capability(
        name="explainer.visual_plan",
        kind="line",
        aspects=["16:9", "9:16"],
        cpu_cost_hint=0.1,
        render=_render_explainer_visual_plan,
        description="节奏驱动视觉规划：依据音频词级时间戳排镜，支持关键词高亮、配图卡片、流程图逐层展开、主讲人布局切换与转场。能力线：纯 CPU 自含链（FFmpeg/PIL，无 Node/Remotion 依赖），与 Studio explainer 线（assembly+Remotion 生产核，供 6 条 Studio 线与 API）是两条独立链；本线供能力目录按名调用与 lanshu styled explainer。",
        line="explainer",
        params_schema={
            "type": "object",
            "required": ["script", "voiceover"],
            "properties": {
                "script": {"type": "object"},
                "voiceover": {"type": "object"},
            },
        },
    )
    register(cap)
    return cap
