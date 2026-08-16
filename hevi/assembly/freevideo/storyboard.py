"""freevideo:storyboard —— 内容 → 分镜计划(FramePlan 列表)。

确定性优先:文本输入按句成镜(复用 story_to_animation_workflow 的分句规则),
JSON 输入接受显式分镜。不依赖 LLM/云端 —— 零成本通道的骨架。

FramePlan.kind 见 templates.FRAME_KINDS:
  title / typewriter / bar / big_number / cards / quote / timeline / scene
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from hevi.assembly.freevideo.templates import FRAME_KINDS
from hevi.assembly.story_to_animation_workflow import segment_story

#: 文本自动分镜时,中间镜头的 kind 轮换表(首/末固定 title,bar/timeline 只在
#: 显式给 data 时使用 —— 文本没有数值就不硬造图表)。
_AUTO_MID: tuple[str, ...] = ("typewriter", "scene", "quote", "cards", "scene", "big_number")

#: 允许的 data 类型模板(需要结构化数据)。
_DATA_KINDS: frozenset[str] = frozenset({"bar", "big_number", "cards", "timeline"})


@dataclass
class FramePlan:
    """一镜:动画模板 kind + 文案 + 可选数据 + 可选背景视频(B-roll) + 时长。"""

    kind: str
    title: str = ""
    body: str = ""
    data: Any = None
    broll: str | None = None  # 背景视频路径(真生成 B-roll 混排)
    duration: float = 4.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "title": self.title,
            "body": self.body,
            "duration": self.duration,
            "broll": self.broll,
            "data": self.data,
        }


def _validate_kind(kind: str) -> str:
    if kind not in FRAME_KINDS:
        raise ValueError(
            f"unknown frame kind {kind!r}; expected one of {', '.join(FRAME_KINDS)}"
        )
    return kind


def plan_from_text(
    text: str,
    *,
    title: str = "",
    frame_duration: float = 4.0,
    kind: str | None = None,
) -> list[FramePlan]:
    """中文文本 → 分镜:首镜 title,末镜 title(收束),中间按轮换表自动选模板。

    Args:
        kind: 指定单一模板(全部镜头用同一模板);None 时自动轮换。
    """
    sentences = segment_story(text)
    # LLM 诗化旁白常无句号(短行分隔):按换行补充分句。
    if len(sentences) <= 1 and "\n" in text:
        sentences = [s.strip() for s in text.splitlines() if s.strip()]
    if not sentences:
        raise ValueError("text 为空,无法分镜")
    plans: list[FramePlan] = []
    n = len(sentences)

    # 首镜:大标题(用第一个句子 + 总标题)
    plans.append(
        FramePlan(
            kind=kind if kind else "title",
            title=title or sentences[0][:16],
            body=sentences[0],
            duration=frame_duration,
        )
    )
    if n == 1:
        return plans

    # 中间镜(仅当至少 3 句);首镜已用句 0,末镜用最后一句
    mid = sentences[1:-1] if n > 2 else []
    for i, s in enumerate(mid):
        k = kind if kind else _AUTO_MID[i % len(_AUTO_MID)]
        plans.append(
            FramePlan(kind=k, title=title or f"第 {i + 2} 镜", body=s, duration=frame_duration)
        )

    # 末镜:收束(指定 kind 时同用,否则大标题)
    last = sentences[-1]
    plans.append(
        FramePlan(kind=kind if kind else "title", title=title or last[:16], body=last, duration=frame_duration)
    )
    return plans


def plan_from_json(raw: str | list[dict[str, Any]] | dict[str, Any]) -> list[FramePlan]:
    """结构化分镜 JSON → FramePlan 列表。

    Accepts:
      [{"kind","title","body","data","duration"}, ...]
      或 {"title","frames":[...]}
    data 里的 kind 若落在 _DATA_KINDS 且无 data,自动尝试从 body 抽取。
    """
    obj = json.loads(raw) if isinstance(raw, str) else raw
    frames = obj.get("frames") if isinstance(obj, dict) else obj
    if not isinstance(frames, list) or not frames:
        raise ValueError("JSON 分镜需为 {frames:[...]} 或 [...]; 不能为空")

    plans: list[FramePlan] = []
    default_title = obj.get("title", "") if isinstance(obj, dict) else ""
    for i, f in enumerate(frames):
        if not isinstance(f, dict):
            raise ValueError(f"frames[{i}] 不是对象")
        kind = _validate_kind(str(f.get("kind") or "quote"))
        title = str(f.get("title") or default_title or f"镜 {i + 1}")
        body = str(f.get("body") or f.get("text") or "")
        duration = float(f.get("duration") or f.get("duration_sec") or 4.0)
        plans.append(
            FramePlan(
                kind=kind,
                title=title,
                body=body,
                data=f.get("data"),
                broll=str(f["broll"]) if f.get("broll") else None,
                duration=max(2.0, duration),
            )
        )
    return plans


__all__ = ["FramePlan", "plan_from_json", "plan_from_text"]
