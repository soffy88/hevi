"""E0 选题 → storyboard —— LLM 一次性生成 6 段固定结构的解说文案 + 分镜参数。

6 种 sceneType 是从"沉没成本"首个真实交付的分镜固化下来的模板(见 hevi-remotion/src/
scenes/*.tsx),不是任意结构——hook(钩子)→ definition(定义)→ cards(举例卡片)→
reason(原因说理)→ method(方法编号)→ outro(结尾金句+引导)。

质量取决于 ProviderRegistry.llm("default") 当前指向哪个 provider:DashScope 欠费期间会
落到本地小模型,结构化输出可能不如云端稳——这是已知的、有记录的限制([[e2e-local-llm-
json-blocker]]),不是这层代码的 bug,gate_storyboard 只做结构校验,不做文案质量把关。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from hevi.explainer.schemas import GateResult, Storyboard, StoryboardSegment, validate_props

logger = logging.getLogger(__name__)

_SCENE_ORDER = ["hook", "definition", "cards", "reason", "method", "outro"]

_STORYBOARD_PROMPT_TEMPLATE = """你是中文自媒体短视频解说文案编剧。给定一个选题,写一期
85-95 秒左右的解说短视频文案,严格分成 6 段固定结构,每段配一段口语化旁白(自然、可朗读,
不要书面语堆砌)和对应的画面参数。

选题: {topic}

6 段结构固定如下,顺序不能变、sceneType 不能改:

1. sceneType="hook"(钩子,开场吸引注意力,举一个具体反常识的例子)
   props: {{"title": "选题核心词(2-6字,会被做成大字标题)",
            "subtitle": "一句短警示语(如\\"正在坑你!\\")",
            "items": [{{"emoji":"单个emoji","label":"物品名","cost":"可选,如¥5000"}}, ...1-2个]}}

2. sceneType="definition"(给出清晰定义)
   props: {{"question": "什么是XX？",
            "formulaHead": "核心词",
            "formulaLines": ["= 定义第一部分","定义第二部分"],
            "sinkEmojis": ["emoji1","emoji2"],
            "splitLeft": {{"emoji":"emoji","title":"4字左右","sub":"6-10字"}},
            "splitRight": {{"emoji":"emoji","title":"4字左右","sub":"6-10字"}}}}

3. sceneType="cards"(2-3 个具体生活化例子,带点幽默)
   props: {{"header": "小标题(6-10字)",
            "cards": [{{"emoji":"emoji","title":"2-4字场景名","desc":"两行短语,用\\n分隔"}}, ...2-3个]}}

4. sceneType="reason"(说理:为什么会这样)
   props: {{"question": "为什么...？",
            "brainLine": "大脑相关的一句话(可用大括号强调词,如"讨厌"浪费"的感觉")",
            "bubbleText": "一句反转/点破的话",
            "leftLabel": {{"title":"4-6字(错误做法)","sub":"= 6字左右后果"}},
            "rightLabel": {{"title":"4-6字(正确做法)","sub":"= 6字左右后果"}}}}

5. sceneType="method"(2-3 条实用方法,编号)
   props: {{"header": "实用方法X招",
            "points": [{{"num":"1","title":"方法一句话(可以是问句)","sub":"补充/示例,8-16字"}}, ...2-3个]}}

6. sceneType="outro"(结尾金句 + 引导关注)
   props: {{"setupLine1":"过渡句1","setupLine2":"过渡句2",
            "quoteLine1":"金句第一句(核心词)","quoteLine2":"金句第二句",
            "ctaEmojis":["👍","⭐","🔔"],"ctaText":"点赞 · 收藏 · 关注","byline":"我们下期见 ～"}}

硬性规则:
1. 每段 "keywords" 数组里的每个词,必须是该段 "narration" 文本里逐字能找到的原文子串
   (会被程序做子串高亮,匹配不上就白写)。
2. 引号一律用中文弯引号"" ,不要用直引号",避免破坏 JSON。
3. narration 是要读出来的旁白,长度参考:hook~60字、definition~45字、cards~65字、
   reason~55字、method~85字、outro~50字(总共约 350-370 字,配合正常语速约 85-95 秒)。
4. 只输出一个 JSON 对象,不要 markdown 代码块,不要任何解释文字:
{{"topic": "{topic}", "segments": [
  {{"id":"hook","sceneType":"hook","narration":"...","keywords":["..."],"props":{{...}}}},
  {{"id":"definition","sceneType":"definition","narration":"...","keywords":["..."],"props":{{...}}}},
  {{"id":"examples","sceneType":"cards","narration":"...","keywords":["..."],"props":{{...}}}},
  {{"id":"reason","sceneType":"reason","narration":"...","keywords":["..."],"props":{{...}}}},
  {{"id":"method","sceneType":"method","narration":"...","keywords":["..."],"props":{{...}}}},
  {{"id":"outro","sceneType":"outro","narration":"...","keywords":["..."],"props":{{...}}}}
]}}"""


def _extract_json_obj(content: str | None) -> dict[str, Any]:
    if not content:
        return {}
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


async def _call_llm_json(llm: Any, prompt: str) -> dict[str, Any]:
    resp = await llm(messages=[{"role": "user", "content": prompt}], max_tokens=4096)
    content = resp.get("content") if hasattr(resp, "get") else str(resp)
    return _extract_json_obj(content)


async def generate_storyboard(topic: str, *, llm: Any = None) -> Storyboard:
    """选题 → Storyboard(未配音)。LLM 调用/解析失败的段会被跳过,交给 gate_storyboard 判定。"""
    if llm is None:
        from obase.provider_registry import ProviderRegistry

        llm = ProviderRegistry.get().llm("default")

    prompt = _STORYBOARD_PROMPT_TEMPLATE.format(topic=topic)
    try:
        draft = await _call_llm_json(llm, prompt)
    except Exception as e:
        logger.warning("explainer storyboard 生成 LLM 调用失败,返回空壳: %s", e)
        draft = {}

    segments: list[StoryboardSegment] = []
    for item in draft.get("segments") or []:
        scene_type = str(item.get("sceneType") or "")
        if scene_type not in _SCENE_ORDER:
            logger.warning("explainer storyboard: 未知 sceneType %r,跳过该段", scene_type)
            continue
        narration = str(item.get("narration") or "").strip()
        if not narration:
            logger.warning("explainer storyboard: 段 %s narration 为空,跳过", item.get("id"))
            continue
        try:
            props = validate_props(scene_type, item.get("props") or {})
        except Exception as e:
            logger.warning("explainer storyboard: 段 %s props 校验失败,跳过: %s", item.get("id"), e)
            continue

        raw_keywords = [str(k) for k in (item.get("keywords") or [])]
        keywords = [k for k in raw_keywords if k and k in narration]
        dropped = set(raw_keywords) - set(keywords)
        if dropped:
            logger.warning(
                "explainer storyboard: 段 %s 关键词未在原文命中,已丢弃: %s", item.get("id"), dropped
            )

        segments.append(
            StoryboardSegment(
                id=str(item.get("id") or scene_type),
                scene_type=scene_type,  # type: ignore[arg-type]
                narration=narration,
                keywords=keywords,
                props=props,
            )
        )

    return Storyboard(topic=topic, segments=segments)


def gate_storyboard(storyboard: Storyboard) -> GateResult:
    """G0 门:6 段齐全、顺序正确、每段都有旁白 —— 结构校验,不评判文案质量好坏。"""
    errors: list[str] = []
    warnings: list[str] = []

    got_types = [seg.scene_type for seg in storyboard.segments]
    if got_types != _SCENE_ORDER:
        errors.append(f"6 段结构不完整或顺序错误,期望 {_SCENE_ORDER},实际 {got_types}")

    for seg in storyboard.segments:
        if len(seg.narration) < 6:
            errors.append(f"段 {seg.id} 旁白过短({len(seg.narration)} 字),疑似生成失败")
        if not seg.keywords:
            warnings.append(f"段 {seg.id} 没有可高亮的关键词(字幕将不做高亮)")

    total_chars = sum(len(seg.narration) for seg in storyboard.segments)
    if not (200 <= total_chars <= 550):
        warnings.append(
            f"总字数 {total_chars} 偏离预期区间(200-550字,对应约60-140秒),成片时长可能跑偏"
        )

    coverage = len(storyboard.segments) / len(_SCENE_ORDER)
    return GateResult(passed=not errors, coverage=coverage, errors=errors, warnings=warnings)
