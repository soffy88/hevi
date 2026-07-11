"""B0 故事解析 —— 小说手稿 → StoryGraph(人物/事件/对白/地点)。见 SPEC-001 §2。

复用 tongjian L0 已验证的抽取范式(见 `hevi/tongjian/chapter_ir.py`):
- LLM 只负责"抽取"(它擅长的),不负责"算下标"(它不擅长的)。
- 人物提及、事件锚句、对白原文都要求 LLM 逐字复制手稿片段,由代码用确定性字符串
  查找算出真实 [start, end) 下标,并顺序分配 char_id/event_id/quote_id。
- 直接复用 tongjian 的 `_find_span`/`_call_llm_json` —— 这几个纯确定性 helper 在本仓库
  已是跨模块共享约定(constitution.py 亦从 chapter_ir 导入),不另造一份。

与 tongjian L0 的差异只在 prompt(古汉语史料 → 通用小说)与产出 schema(去 year、加
beat_type/description)。阶段 1 不抽 relationships/arcs(留给阶段 2 关系守护)。
"""

from __future__ import annotations

import logging
from typing import Any

from hevi.storygraph.schemas import (
    StoryCharacter,
    StoryEvent,
    StoryGraph,
    StoryLocation,
    StoryMeta,
    StoryQuote,
)
from hevi.tongjian.chapter_ir import _call_llm_json, _find_span

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT_TEMPLATE = """你是小说文本结构化专家。把下面这段《{source_name}》手稿抽取成结构化 JSON,供影视化改编使用。

手稿:
{raw_text}

只输出一个 JSON 对象,不要任何其它文字,格式如下:
{{
  "characters": [
    {{"name": "人物canonical姓名(选文中最正式/最常用的称呼)", "aliases": ["文中出现过的其它称呼/字/绰号/代称"],
      "description": "外貌与性格的可视化特征(供角色建模,如:身量高瘦、玄衣、冷峻寡言;文中无则空字符串)",
      "role": "protagonist|antagonist|supporting", "faction": "所属势力/门派/家族(无则空字符串)",
      "mentions": ["手稿中提到此人的一处逐字片段(3-15字,必须是手稿连续子串,给1-3处即可)"]}}
  ],
  "events": [
    {{"summary": "一句话事件摘要", "actors": ["涉事人物的name或aliases,必须与上面 characters 列表一致"],
      "location": "事发地点(无则空字符串)", "time_hint": "时间线索(如:三年后/翌日清晨;无则空字符串)",
      "causes": [依赖的更早事件在本 events 数组里的下标(0起)的整数列表,若为首个事件则空],
      "effects": [导致的更晚事件下标整数列表,若为末尾事件则空],
      "beat_type": "铺垫|冲突|转折|高潮|收束|过场",
      "dramatic_weight": 1到5的整数(戏剧性权重,冲突高潮给5),
      "quote_span": "定位此事件的手稿逐字片段(5-20字,必须是手稿连续子串)"}}
  ],
  "quotes": [
    {{"speaker": "说话人的name或aliases,必须与characters列表一致", "original": "手稿逐字对白(必须是手稿连续子串,不得改写不得增删标点)",
      "modern": "口语化改写参考", "event_index": 该对白所属事件在events数组里的下标(整数),
      "emotion": "说话时的情绪(如:讥诮/恳求/惊惧)"}}
  ],
  "locations": [
    {{"name": "地点名", "type": "城市|宅邸|学校|战场等", "event_indices": [涉及此地点的事件下标整数列表]}}
  ]
}}

硬性规则:
1. mentions / quote_span / original 三类字段的值必须是手稿的**逐字连续子串**,一字不差,不得意译、不得增删标点。
2. actors / speaker 只能用 characters 里出现过的 name 或 aliases,不得杜撰未在 characters 列表声明的人名。
3. causes / effects / event_index 是**数组下标**(从 0 开始的整数),不是事件 ID 字符串。
4. 只抽取手稿明确写出的内容,不得脑补手稿没有的情节或对话。
"""


async def extract_story_graph(*, source_name: str, raw_text: str, llm: Any = None) -> StoryGraph:
    """小说手稿 → StoryGraph。LLM 结构化抽取草稿,代码定位真实下标 + 分配确定性 ID。

    降级策略同 tongjian L0:任何字段解析失败走"能用的部分正常收,解不出的部分丢弃并记
    警告",不因局部失败让整层抛异常。relationships/arcs 阶段 1 留空。
    """
    if llm is None:
        from obase.provider_registry import ProviderRegistry

        # 逐层显式选 qwen_cloud(非欠费云端,见 registry:187);"default" 仍是欠费公共端点。
        llm = ProviderRegistry.get().llm("qwen_cloud")

    prompt = _EXTRACTION_PROMPT_TEMPLATE.format(source_name=source_name, raw_text=raw_text)
    try:
        draft = await _call_llm_json(llm, prompt)
    except Exception as e:
        logger.warning(
            "story_graph 抽取 LLM 调用失败,返回空草稿(上层门会因覆盖率不达标而重试): %s", e
        )
        draft = {}

    # ── 人物:分配 char_id,mentions → source_spans(代码定位),first_appearance = 最早 span ──
    characters: list[StoryCharacter] = []
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
        first_appearance = min(spans, key=lambda s: s[0]) if spans else None
        characters.append(
            StoryCharacter(
                char_id=cid,
                name=name,
                aliases=aliases,
                description=str(c.get("description") or ""),
                role=str(c.get("role") or ""),
                faction=(c.get("faction") or None),
                first_appearance=first_appearance,
                source_spans=spans,
            )
        )

    # ── 事件:先分配 event_id,causes/effects/actors 二次映射 ──
    raw_events = draft.get("events", []) or []
    event_ids = [f"E{i:03d}" for i in range(1, len(raw_events) + 1)]
    events: list[StoryEvent] = []
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
        events.append(
            StoryEvent(
                event_id=event_ids[i],
                summary=str(e.get("summary") or ""),
                actors=actors,
                location=(e.get("location") or None),
                time_hint=str(e.get("time_hint") or ""),
                causes=causes,
                effects=effects,
                beat_type=str(e.get("beat_type") or ""),
                dramatic_weight=int(e.get("dramatic_weight") or 3),
                source_span=span,
            )
        )

    # ── 对白:speaker 解析成 char_id;original 必须能在手稿精确定位,
    #    定位不到视为疑似幻觉,丢弃并记警告(不静默接受编造对白——叙事红线)。
    quotes: list[StoryQuote] = []
    for q in draft.get("quotes", []) or []:
        original = str(q.get("original") or "").strip()
        if not original or _find_span(raw_text, original) is None:
            logger.warning("quote 在手稿中定位不到,丢弃(疑似幻觉): %r", original[:30])
            continue
        speaker_name = str(q.get("speaker") or "").strip()
        speaker_id = name_to_id.get(speaker_name, speaker_name)
        ev_idx = q.get("event_index")
        event_id = (
            event_ids[ev_idx] if isinstance(ev_idx, int) and 0 <= ev_idx < len(event_ids) else None
        )
        quotes.append(
            StoryQuote(
                quote_id=f"Q{len(quotes) + 1:03d}",
                speaker=speaker_id,
                original=original,
                modern=str(q.get("modern") or ""),
                event_id=event_id,
                emotion=str(q.get("emotion") or ""),
            )
        )

    # ── 地点 ──
    locations: list[StoryLocation] = []
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
            StoryLocation(
                location_id=f"L{i:03d}",
                name=name,
                type=str(loc.get("type") or ""),
                events=ev_indices,
            )
        )

    meta = StoryMeta(source=source_name, char_count=len(raw_text))
    return StoryGraph(
        meta=meta, characters=characters, events=events, quotes=quotes, locations=locations
    )
