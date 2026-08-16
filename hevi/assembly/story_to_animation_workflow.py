"""手绘日记漫画工作流 —— 中文故事/有序图片 → 手绘动画制作计划(3O 内化 Round 3c)。

来源: gnipbao/story-to-handdrawn-video —— 这是当初 Phase C 计划里列了但未建的一环
(`oskill.story_to_animation`)。其渲染器(Remotion)契约已内化为 RENDER-CONTRACT.md +
remotion_render_workflow;这里补**故事侧编排**:故事文本/有序图片 → 分句成 beat →
三种模式(plan/preview/full)→ 分镜计划(文字→黑白→彩色 三段揭示 或 卷页翻书),
渲染交 remotion(确定性部分全可测)。

规则(来源 story-to-handdrawn SKILL.md + DESIGN.md):
  - 中文故事按句成 beat(保持一句一拍;长句在自然叙事转折处分)
  - 直切模式揭示顺序 `文字 → 黑白线稿 → 彩色插画`,每层从左到右
  - 卷页模式:保留未触碰母版,静态展示后从右下角卷起(纸背淡化原页纹理)
  - contain 不 cover;字幕上安全区;默认静音画面轨(配音后期)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: 创作模式(与 run_story_video.py 的 plan/preview/full 对齐)。
STORY_MODES: tuple[str, ...] = ("plan", "preview", "full")
#: 过渡模式。
STORY_TRANSITIONS: tuple[str, ...] = ("cut", "page-flip")

#: 中文分句:句号/问号/感叹号/省略号 为自然边界(全角+半角,保留原文措辞)。
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？…!?])")


@dataclass
class StoryConfig:
    """故事动画配置。"""

    out_path: Path
    mode: str = "plan"  # plan | preview | full
    transition: str = "cut"  # cut | page-flip
    fps: int = 30
    width: int = 1080
    height: int = 1440  # 3:4 竖屏(来源默认画布)
    page_duration_s: float = 4.4
    transition_sec: float = 0.7
    title: str = ""


@dataclass
class StoryInput:
    """输入:故事文本 或 有序图片路径(二选一)。"""

    text: str = ""
    images: list[Path] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class StoryBeat:
    """一个 beat(一拍):一段故事文本 + 落位信息。"""

    index: int
    text: str
    mode: str  # text | bw_full | color
    page_index: int = -1  # 图片输入时的页码;文本输入 -1


@dataclass
class StoryPlan:
    """故事动画分镜计划。"""

    beats: list[StoryBeat]
    transition: str
    composition_hint: str
    canvas: tuple[int, int, int]  # w,h,fps

    def to_dict(self) -> dict[str, Any]:
        return {
            "beats": [
                {"index": b.index, "text": b.text, "mode": b.mode, "page_index": b.page_index}
                for b in self.beats
            ],
            "transition": self.transition,
            "composition_hint": self.composition_hint,
            "canvas": list(self.canvas),
        }


def segment_story(text: str) -> list[str]:
    """中文分句:按句号/问号/感叹号/省略号切,保留原文措辞,一句一拍(来源纪律)。"""
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(text) if p.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def build_story_plan(config: StoryConfig, input_data: StoryInput) -> StoryPlan:
    """确定性分镜:文本 → 每句一拍;图片 → 每图一拍。

    - cut 模式:每 beat 三态揭示 `text → bw_full → color`(阶段由渲染器驱动)。
    - page-flip 模式:每 beat 单页,保留母版,右下角卷页转场。
    """
    if config.mode not in STORY_MODES:
        raise ValueError(f"unknown mode {config.mode!r}; expected one of {STORY_MODES}")
    if config.transition not in STORY_TRANSITIONS:
        raise ValueError(f"unknown transition {config.transition!r}")

    beats: list[StoryBeat] = []
    if input_data.images:
        for i, img in enumerate(input_data.images):
            beats.append(StoryBeat(index=i + 1, text=img.name, mode="page", page_index=i))
        hint = (
            f"uploaded-images({len(beats)} pages), transition={config.transition}, "
            "保留未触碰母版,contain 不 cover"
        )
    else:
        sentences = segment_story(input_data.text)
        for i, sentence in enumerate(sentences):
            beats.append(StoryBeat(index=i + 1, text=sentence, mode="reveal"))
        hint = (
            f"story-text({len(beats)} beats), transition={config.transition}, "
            "直切三态揭示 text→bw→color 或卷页,静音画面轨"
        )

    return StoryPlan(
        beats=beats,
        transition=config.transition,
        composition_hint=hint,
        canvas=(config.width, config.height, config.fps),
    )


async def story_to_animation_workflow(
    config: StoryConfig,
    input_data: StoryInput,
    output_dir: Path,
    *,
    on_step: Any = None,
) -> dict[str, Any]:
    """标准 omodul:分镜计划 → report;渲染交 remotion_render_workflow(可选)。"""
    _enabled_pillars = {"report", "cost", "decision_trail"}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    def _step(stage: str, pct: float) -> None:
        if callable(on_step):
            on_step({"stage": stage, "pct": pct})

    try:
        if not input_data.text.strip() and not input_data.images:
            return {"status": "failed", "error": "需要故事文本或有序图片"}
        _step("validate", 15.0)
        plan = build_story_plan(config, input_data)
        _step("storyboard", 60.0)

        report = {
            "status": "completed",
            "mode": config.mode,
            "plan": plan.to_dict(),
            "render_note": (
                "渲染: hevi.assembly.remotion_render_workflow + hevi-remotion 手绘组合;"
                "preview 档 720x960 快速预览,full 档 1080x1440"
            ),
        }
        report_path = output_dir / "story_plan.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {"status": "completed", "report_path": str(report_path), **report}
    except Exception as e:
        logger.exception("story_to_animation_workflow failed")
        return {"status": "failed", "error": str(e)}
