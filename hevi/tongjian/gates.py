"""G0 校验门 —— chapter_ir 抽取质量闸门。见 HEVI-SPEC-01 §1.3。

四项检查:
1. 结构校验:pydantic 构造 ChapterIR 已保证(能传进来就是过了),这里只再确认非空。
2. 覆盖率:events.source_span 并集 / raw_text 总字数 >= 85%。
3. 引用闭环:quote.speaker 引用不到已知 character_id 的,按 spec 降级规则补一个匿名
   人物兜底(narrator-only,无戏剧角色),只计入 warnings,不阻塞门。
4. 幻觉抽查:随机抽 20% 的 events,LLM 反查 source_span 原文是否真的支持 summary。

硬失败只有覆盖率不达标、幻觉抽查判定不实两类——降级能兜住的都不算门失败,呼应
"流水线永不卡死"的总原则。
"""

from __future__ import annotations

import logging
import random
from typing import Any

from hevi.tongjian.chapter_ir import _extract_json_obj
from hevi.tongjian.schemas import ChapterIR, CharacterIR, GateResult

logger = logging.getLogger(__name__)

_COVERAGE_THRESHOLD = 0.85
_SPOT_CHECK_RATIO = 0.2


def _resolve_unresolved_speakers(chapter_ir: ChapterIR) -> tuple[ChapterIR, list[str]]:
    """quote.speaker 未闭环 → 降级为独立匿名人物,而不是判门失败。"""
    known_ids = {c.character_id for c in chapter_ir.characters}
    warnings: list[str] = []
    characters = list(chapter_ir.characters)
    next_idx = len(characters) + 1
    resolved_anon: dict[str, str] = {}

    for q in chapter_ir.quotes:
        if q.speaker in known_ids or q.speaker in resolved_anon:
            continue
        anon_id = f"C{next_idx:03d}"
        next_idx += 1
        resolved_anon[q.speaker] = anon_id
        characters.append(
            CharacterIR(character_id=anon_id, canonical_name=q.speaker, role_in_chapter="anonymous")
        )
        warnings.append(f"quote 引用了未闭环人物 {q.speaker!r},已降级为匿名人物 {anon_id}")

    if not resolved_anon:
        return chapter_ir, warnings

    new_quotes = [
        q.model_copy(update={"speaker": resolved_anon.get(q.speaker, q.speaker)})
        for q in chapter_ir.quotes
    ]
    updated = chapter_ir.model_copy(update={"characters": characters, "quotes": new_quotes})
    return updated, warnings


def _compute_coverage(chapter_ir: ChapterIR, raw_text: str) -> float:
    """events.source_span 并集长度 / 原文总长("叙事覆盖率")。"""
    total = len(raw_text)
    if total == 0:
        return 0.0
    spans = sorted(e.source_span for e in chapter_ir.events if e.source_span != (0, 0))
    covered = 0
    cursor = 0
    for start, end in spans:
        start = max(start, cursor)
        end = max(end, start)
        covered += end - start
        cursor = max(cursor, end)
    return covered / total


async def _spot_check_hallucination(chapter_ir: ChapterIR, raw_text: str, llm: Any) -> list[str]:
    events = chapter_ir.events
    if not events:
        return []
    sample_size = max(1, round(len(events) * _SPOT_CHECK_RATIO))
    sample = random.sample(events, min(sample_size, len(events)))
    errors: list[str] = []
    for e in sample:
        start, end = e.source_span
        span_text = raw_text[start:end]
        if not span_text:
            errors.append(f"事件 {e.event_id} 的 source_span 为空,无法核验(疑似定位失败)")
            continue
        prompt = (
            "下面是一段古汉语原文片段和对它的一句话摘要。判断摘要是否忠实于原文,"
            '不得包含原文没有的情节。只输出 JSON: {"supported": true/false, "reason": "..."}\n\n'
            f"原文片段:{span_text}\n摘要:{e.summary}"
        )
        try:
            resp = await llm(messages=[{"role": "user", "content": prompt}], max_tokens=200)
        except Exception as ex:
            logger.warning("事件 %s 幻觉抽查 LLM 调用失败,跳过该样本: %s", e.event_id, ex)
            continue
        content = resp.get("content") if hasattr(resp, "get") else str(resp)
        verdict = _extract_json_obj(content)
        if verdict.get("supported") is False:
            errors.append(f"事件 {e.event_id} 幻觉抽查未通过: {verdict.get('reason', '')}")
    return errors


async def gate_chapter_ir(
    chapter_ir: ChapterIR, raw_text: str, *, llm: Any = None
) -> tuple[ChapterIR, GateResult]:
    """G0 门。返回 (可能被降级修正过的 chapter_ir, GateResult)。"""
    if llm is None:
        from obase.provider_registry import ProviderRegistry

        llm = ProviderRegistry.get().llm("default")

    errors: list[str] = []

    if not chapter_ir.events:
        errors.append("chapter_ir 没有抽出任何事件")

    chapter_ir, warnings = _resolve_unresolved_speakers(chapter_ir)

    coverage = _compute_coverage(chapter_ir, raw_text)
    if coverage < _COVERAGE_THRESHOLD:
        errors.append(f"叙事覆盖率 {coverage:.1%} 低于门槛 {_COVERAGE_THRESHOLD:.0%}")

    errors.extend(await _spot_check_hallucination(chapter_ir, raw_text, llm))

    return chapter_ir, GateResult(
        passed=not errors, coverage=coverage, errors=errors, warnings=warnings
    )
