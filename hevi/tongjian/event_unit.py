"""选段(chunking)—— 一卷原文 → EventUnit 候选。见 SPEC-005 §1.1。

一卷《资治通鉴》动辄上万字、横跨数年,一卷 ≠ 一集。这一层在 L0(chapter_ir)之前:先把
一卷切成若干「起承转合完整」的事件单元(一集候选),单元内再把段落按 §1.1 判据标成
narration(讲解)/ drama(演绎)。

与 chapter_ir.py 同一套工程决策:LLM 只负责"抽取/判断",不负责"算下标"——segment 的
source_text 要求 LLM 逐字复制原文片段,代码用确定性字符串查找核验;核验不过(疑似幻觉/
改写)的段落丢弃并记警告,不静默接受编造文本(版权/史实红线,呼应 chapter_ir 对 quote
的处理)。

只产出候选(AI 提候选那一半);"人确认"不建审核 UI——返回的 list[EventUnit] 是可读可编辑
的 pydantic 对象,人工 review 后把确认结果传入下一步即可。
"""

from __future__ import annotations

import logging
from typing import Any

from hevi.tongjian.chapter_ir import _call_llm_json, _find_span
from hevi.tongjian.schemas import EventUnit, Segment

logger = logging.getLogger(__name__)

_VALID_SEGMENT_TYPES = {"narration", "drama"}
_CHARS_PER_SEC_CLASSICAL = 3.0  # 粗略估算(文言字密度高于白话),仅供选段阶段排期参考;
# 真实时长以 narration_script.py 生成的白话讲解稿字数为准。

_EXTRACTION_PROMPT_TEMPLATE = """你是《资治通鉴》选段编辑。把下面这段《{source_name}》原文切成若干
「起承转合完整」的事件单元(每个单元适合独立成一集),单元内再把段落按下面判据标类型:

- 有对白/冲突/决策瞬间/具体动作 → drama(演绎段)
- 背景/铺垫/制度说明/后果/司马光评论 → narration(讲解段)

示例(另一段古文,只演示格式,不要照抄示例内容到你的答案里):
原文:「陳勝自立為將軍,吳廣為都尉。攻大澤鄉,收而攻蘄。蘄下,乃令符離人葛嬰將兵徇蘄以東。」
输出:{{"event_units": [{{"title": "陈胜起兵", "era": "秦末", "year": -209,
  "summary": "陈胜吴广自立为将,攻取大泽乡与蕲县",
  "segments": [
    {{"type": "narration", "text": "陳勝自立為將軍,吳廣為都尉。"}},
    {{"type": "drama", "text": "攻大澤鄉,收而攻蘄。蘄下,乃令符離人葛嬰將兵徇蘄以東。"}}
  ]}}]}}

现在请对下面的原文作答,只输出一个 JSON 对象(格式同上例),不要输出示例内容、不要输出任何
解释或指令复述:

原文:
{raw_text}

硬性规则:
1. segments[].text 必须是"原文"部分的**逐字连续子串**,一字不差,按原文先后顺序排列,
   覆盖原文全部内容。
2. text 只能来自"原文",绝不能包含本提示词里的指令文字、示例文字或你自己的解释。
3. 若"原文"只讲一件连贯的事,只输出 1 个 event_unit,不要拆成多个。
4. 只切分标类型,不改写、不翻译、不评论。
"""


def _coerce_segments(raw_segments: list[dict[str, Any]], raw_text: str) -> list[Segment]:
    segments: list[Segment] = []
    for i, seg in enumerate(raw_segments):
        text = str(seg.get("text") or "").strip()
        if not text or _find_span(raw_text, text) is None:
            logger.warning("segment 在原文中定位不到,丢弃(疑似幻觉/改写): %r", text[:30])
            continue
        seg_type = str(seg.get("type") or "narration")
        if seg_type not in _VALID_SEGMENT_TYPES:
            seg_type = "narration"
        segments.append(
            Segment(
                type=seg_type,
                source_text=text,
                est_duration_s=round(len(text) / _CHARS_PER_SEC_CLASSICAL),
                order=i,
            )
        )
    return segments


async def extract_event_units(
    *, source_name: str, raw_text: str, llm: Any = None
) -> list[EventUnit]:
    """一卷原文 → EventUnit 候选列表。LLM 调用失败 → 返回空列表(降级,不阻塞)。"""
    if llm is None:
        from obase.provider_registry import ProviderRegistry

        llm = ProviderRegistry.get().llm("default")

    prompt = _EXTRACTION_PROMPT_TEMPLATE.format(source_name=source_name, raw_text=raw_text)
    try:
        # 小参数本地模型(如 llama3.2:3B)在宽松 max_tokens 下容易复读跑飞,拖到截断都
        # 拼不出合法 JSON;temperature 调低让输出更贴着示例格式走,而不是自由发挥。
        draft = await _call_llm_json(llm, prompt, max_tokens=1200, temperature=0.2)
    except Exception as e:
        logger.warning("event_unit 选段 LLM 调用失败,返回空列表: %s", e)
        draft = {}

    event_units: list[EventUnit] = []
    for i, eu in enumerate(draft.get("event_units", []) or [], start=1):
        segments = _coerce_segments(eu.get("segments") or [], raw_text)
        if not segments:
            continue
        year = eu.get("year")
        event_units.append(
            EventUnit(
                event_unit_id=f"EU{i:03d}",
                source_ref=source_name,
                title=str(eu.get("title") or ""),
                era=str(eu.get("era") or ""),
                year=(int(year) if isinstance(year, int) else None),
                summary=str(eu.get("summary") or ""),
                segments=segments,
            )
        )
    return event_units
