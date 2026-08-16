"""golden_formula —— 黄金公式分镜拆解器 (教材讲解视频动画版)。

把课文按 [景别/运镜]+[主体+动作+表情]+[氛围/光线] 切成 3-5s 分镜矩阵,
每镜带 narration(解说) —— 直接喂 HTML/CSS 动画渲染。

deepseek 中文键兼容 + reasoning 兜底 (P0/P1 实证)。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

MIN_BEAT_S, MAX_BEAT_S = 3.0, 5.0


class GoldenBeat(dict[str, Any]):
    """兼容 dict 消费者与属性式动画编排器的分镜对象。"""

    def __init__(self, **values: Any) -> None:
        super().__init__(values)

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    @property
    def shot_prompt(self) -> str:
        camera = f"{self.get('shot_size', 'medium')}, {self.get('movement', 'static')}"
        body = ", ".join(str(self.get(k) or '') for k in ('subject', 'action', 'emotion_expression') if self.get(k))
        env = "、".join(str(self.get(k) or '') for k in ('atmosphere', 'lighting') if self.get(k))
        return ", ".join(x for x in (camera, body, env) if x)

    def to_dict(self) -> dict[str, Any]:
        return dict(self)

_DECOMPOSE_SYSTEM = """你是初中历史教材讲解视频的分镜导演。把课文切成 3-5 秒镜头, 每镜严格填充:
[景别/运镜] + [主体/画面] + [氛围/光线] + [解说旁白]。

铁律:
1. 每镜 3-5s, 覆盖课文核心知识点;
2. 情绪必须视觉化 (不写抽象词);
3. 景别从 wide/full/medium/medium_close/close/extreme_close 选;
4. 运镜从 static/pan/tilt/push_in/pull_out/tracking 选;
5. 只输出 JSON 数组。

输出格式 (JSON 数组):
[{"shot_size":"medium","movement":"static","subject":"北京人",
  "action":"在周口店龙骨山使用打制石器","emotion_expression":"专注劳作",
  "atmosphere":"远古森林","lighting":"自然光线",
  "duration_s":4.0,"narration":"北京人生活在距今约70万-20万年前的周口店龙骨山。"}]
"""


async def decompose_story_to_golden_beats(
    story: str, llm: Any, *, max_beats: int = 8
) -> list[GoldenBeat]:
    """LLM 按黄金公式切分教材课文 → 分镜矩阵。"""
    user = f"课文内容:\n{story}\n\n最多 {max_beats} 镜, 每镜 3-5s, 输出 JSON 数组。"
    messages = [{"role": "system", "content": _DECOMPOSE_SYSTEM},
                {"role": "user", "content": user}]
    try:
        import inspect
        out = llm(messages=messages)
        if inspect.isawaitable(out):
            out = await out
    except Exception as e:
        logger.warning("黄金公式 LLM 失败: %s", e)
        return []
    content = _extract_content(out)
    return parse_golden_beats(content, max_beats=max_beats)


def golden_beats_to_shot_prompts(beats: list[Any]) -> list[str]:
    """GoldenBeat 列表 → 黄金公式 shot_prompt 列表(每镜一条)。"""
    return [b.shot_prompt if hasattr(b, "shot_prompt") else str(b) for b in beats]


def _extract_content(out: Any) -> str:
    if isinstance(out, str):
        return out
    if isinstance(out, dict):
        content = out.get("content", "")
        if not content:
            choices = (out.get("output") or {}).get("choices") or []
            msg = (choices[0].get("message") or {}) if choices else {}
            content = msg.get("content") or msg.get("reasoning_content") or ""
        return str(content)
    return str(out)


def parse_golden_beats(raw: str, *, max_beats: int = 8) -> list[GoldenBeat]:
    """解析 LLM 输出 → GoldenBeat dict 列表。兼容中文键 + markdown fence。"""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE).strip()
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        logger.warning("黄金公式解析失败: 无 JSON 数组")
        return []
    try:
        data = json.loads(m.group())
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    beats: list[GoldenBeat] = []
    for item in data[:max_beats]:
        if not isinstance(item, dict):
            continue
        # 中英文键兼容
        def v(*keys: str, _item: dict[str, Any] = item) -> str:
            return next(
                (str(_item.get(k)) for k in keys if _item.get(k) is not None), ""
            )

        dur_raw = str(v("duration_s", "duration", "时长") or "4")
        dur_raw = dur_raw.replace("s", "").replace("秒", "").strip()
        dur = float(dur_raw or 4.0)
        dur = max(MIN_BEAT_S, min(MAX_BEAT_S, dur))
        scene_text = str(v("画面", "action"))
        narration = str(v("narration", "旁白", "解说") or "")
        beats.append(GoldenBeat(
            shot_size=str(v("shot_size", "景别") or "medium"),
            movement=str(v("movement", "运镜") or "static"),
            subject=str(v("subject", "主体") or ""),
            action=str(v("action", "动作") or scene_text or ""),
            emotion_expression=str(v("emotion_expression", "表情", "情绪") or ""),
            atmosphere=str(v("atmosphere", "氛围") or ""),
            lighting=str(v("lighting", "光线") or ""),
            duration_s=dur,
            narration=narration,
        ))
    return beats
