"""L0 史料预处理 —— 原文 → chapter_ir(人物/事件/引语/地点)。见 HEVI-SPEC-01 §1。

关键工程决策:LLM 只负责"抽取"(它擅长的),不负责"算下标"(它不擅长的)。
- 人物提及(mentions)、事件锚句(quote_span)、引语原文(original)都要求 LLM
  逐字复制原文片段,由代码用确定性字符串查找算出真实 [start, end) 下标。
- character_id / event_id / quote_id 由代码顺序分配,LLM 只需在 actors/speaker/
  causes/effects/event_index 里引用"人物名"或"事件在数组里的下标(0 起)",
  彻底避免 LLM 编 ID 编不齐全的老毛病。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from hevi.tongjian.schemas import (
    ChapterIR,
    ChapterMeta,
    CharacterIR,
    EventIR,
    LocationHint,
    QuoteIR,
)

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT_TEMPLATE = """你是古汉语史料结构化专家。把下面这段《{source_name}》原文抽取成结构化 JSON。

原文:
{raw_text}

只输出一个 JSON 对象,不要任何其它文字,格式如下:
{{
  "characters": [
    {{"name": "人物canonical姓名(选史书里最正式的称呼)", "aliases": ["原文中出现过的其它称呼/字/官爵/代称"],
      "role_in_chapter": "protagonist|antagonist|supporting", "faction": "所属势力(无则空字符串)",
      "fate": "本章内此人结局(无则空字符串)",
      "mentions": ["原文中提到此人的一处逐字片段(3-15字,必须是原文连续子串,给1-3处即可)"]}}
  ],
  "events": [
    {{"summary": "一句话事件摘要", "actors": ["涉事人物的name或aliases,必须与上面 characters 列表一致"],
      "location": "事发地点(无则空字符串)", "year": 公元纪年整数(公元前用负数,不确定则null),
      "causes": [依赖的更早事件在本 events 数组里的下标(0起)的整数列表,若为首个事件则空],
      "effects": [导致的更晚事件下标整数列表,若为末尾事件则空],
      "dramatic_weight": 1到5的整数(戏剧性权重,冲突高潮给5),
      "quote_span": "定位此事件的原文逐字片段(5-20字,必须是原文连续子串)"}}
  ],
  "quotes": [
    {{"speaker": "说话人的name或aliases,必须与characters列表一致", "original": "原文逐字引语(必须是原文连续子串,不得改写不得加引号符号)",
      "modern": "白话译文", "event_index": 该引语所属事件在events数组里的下标(整数),
      "emotion": "说话时的情绪(如:狂傲/劝谏/惊恐)"}}
  ],
  "locations": [
    {{"name": "地点名", "type": "城池|封地|战场|宫殿等", "event_indices": [涉及此地点的事件下标整数列表]}}
  ]
}}

硬性规则:
1. mentions / quote_span / original 三类字段的值必须是原文的**逐字连续子串**,一字不差,不得意译、不得添加标点、不得转换繁简体。
2. actors / speaker 只能用 characters 里出现过的 name 或 aliases,不得杜撰未在 characters 列表声明的人名。
3. causes / effects / event_index 是**数组下标**(从 0 开始的整数),不是事件 ID 字符串。
4. 只抽取原文明确写出的内容,不得脑补原文没有的情节或对话。
"""


def _find_span(raw_text: str, snippet: str) -> tuple[int, int] | None:
    """确定性字符串定位:snippet 在 raw_text 里的 [start, end)。找不到 → None。"""
    snippet = (snippet or "").strip()
    if not snippet:
        return None
    idx = raw_text.find(snippet)
    if idx == -1:
        return None
    return (idx, idx + len(snippet))


def _extract_json_obj(content: str | None) -> dict[str, Any]:
    """从 LLM 输出里抽 JSON 对象(容忍 markdown 代码块/前后缀文字)。失败返回空 dict。"""
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


async def extract_chapter_ir(*, source_name: str, raw_text: str, llm: Any = None) -> ChapterIR:
    """原文 → ChapterIR。LLM 结构化抽取草稿,代码定位真实下标 + 分配确定性 ID。

    任何字段解析失败都走"能用的部分正常收,解不出的部分丢弃并记警告"——不因局部
    解析失败让整层抛异常(G0 门再统一审覆盖率/引用闭环是否达标,由上层决定是否重试)。
    """
    if llm is None:
        from obase.provider_registry import ProviderRegistry

        llm = ProviderRegistry.get().llm("default")

    prompt = _EXTRACTION_PROMPT_TEMPLATE.format(source_name=source_name, raw_text=raw_text)
    try:
        draft = await _call_llm_json(llm, prompt)
    except Exception as e:
        logger.warning(
            "chapter_ir 抽取 LLM 调用失败,返回空草稿(G0 门会因覆盖率不达标而重试): %s", e
        )
        draft = {}

    # ── 人物:分配 character_id,mentions → source_spans(代码定位) ──
    characters: list[CharacterIR] = []
    name_to_id: dict[str, str] = {}
    for i, c in enumerate(draft.get("characters", []) or [], start=1):
        name = str(c.get("name") or "").strip()
        if not name:
            continue
        cid = f"C{i:03d}"
        aliases = [str(a).strip() for a in (c.get("aliases") or []) if str(a).strip()]
        for n in (name, *aliases):
            name_to_id[n] = cid
        spans = []
        for m in c.get("mentions") or []:
            span = _find_span(raw_text, str(m))
            if span:
                spans.append(span)
        characters.append(
            CharacterIR(
                character_id=cid,
                canonical_name=name,
                aliases=aliases,
                role_in_chapter=str(c.get("role_in_chapter") or ""),
                faction=(c.get("faction") or None),
                fate=(c.get("fate") or None),
                source_spans=spans,
            )
        )

    # ── 事件:先分配 event_id,causes/effects/actors 二次映射 ──
    raw_events = draft.get("events", []) or []
    event_ids = [f"E{i:03d}" for i in range(1, len(raw_events) + 1)]
    events: list[EventIR] = []
    for i, e in enumerate(raw_events):
        actors = [name_to_id[n] for n in (e.get("actors") or []) if n in name_to_id]
        causes = [
            event_ids[j]
            for j in (e.get("causes") or [])
            if isinstance(j, int) and 0 <= j < len(event_ids)
        ]
        effects = [
            event_ids[j]
            for j in (e.get("effects") or [])
            if isinstance(j, int) and 0 <= j < len(event_ids)
        ]
        span = _find_span(raw_text, str(e.get("quote_span") or "")) or (0, 0)
        year = e.get("year")
        events.append(
            EventIR(
                event_id=event_ids[i],
                summary=str(e.get("summary") or ""),
                actors=actors,
                location=(e.get("location") or None),
                year=(int(year) if isinstance(year, int) else None),
                causes=causes,
                effects=effects,
                dramatic_weight=int(e.get("dramatic_weight") or 3),
                source_span=span,
            )
        )

    # ── 引语:speaker 解析成 character_id;original 必须能在原文精确定位,
    #    定位不到视为疑似幻觉,丢弃并记警告(不静默接受编造引语——史实红线)。
    quotes: list[QuoteIR] = []
    for q in draft.get("quotes", []) or []:
        original = str(q.get("original") or "").strip()
        if not original or _find_span(raw_text, original) is None:
            logger.warning("quote 在原文中定位不到,丢弃(疑似幻觉): %r", original[:30])
            continue
        speaker_name = str(q.get("speaker") or "").strip()
        speaker_id = name_to_id.get(speaker_name, speaker_name)
        ev_idx = q.get("event_index")
        event_id = (
            event_ids[ev_idx] if isinstance(ev_idx, int) and 0 <= ev_idx < len(event_ids) else None
        )
        quotes.append(
            QuoteIR(
                quote_id=f"Q{len(quotes) + 1:03d}",
                speaker=speaker_id,
                original=original,
                modern=str(q.get("modern") or ""),
                event_id=event_id,
                emotion=str(q.get("emotion") or ""),
            )
        )

    # ── 地点 ──
    locations: list[LocationHint] = []
    for i, loc in enumerate(draft.get("locations", []) or [], start=1):
        name = str(loc.get("name") or "").strip()
        if not name:
            continue
        ev_indices = [
            event_ids[j]
            for j in (loc.get("event_indices") or [])
            if isinstance(j, int) and 0 <= j < len(event_ids)
        ]
        locations.append(
            LocationHint(
                scene_hint_id=f"S_HINT_{i:02d}",
                name=name,
                type=str(loc.get("type") or ""),
                events=ev_indices,
            )
        )

    years = [e.year for e in events if e.year is not None]
    meta = ChapterMeta(
        source=source_name,
        year_range=(min(years), max(years)) if years else None,
        char_count=len(raw_text),
    )
    return ChapterIR(
        meta=meta, characters=characters, events=events, quotes=quotes, locations=locations
    )
