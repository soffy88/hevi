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
import re
from typing import Any

from hevi.tongjian.chapter_ir import _extract_json_obj
from hevi.tongjian.schemas import ChapterIR, CharacterIR, GateResult, ShotList

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


# ── T1 版权 lint(SPEC-005 §1.3)—— 只拉原文,拒收已知译本特征的文本 ─────────
# 确定性子串/密度匹配,零 LLM 成本。不是穷尽性版权检测,只挡最明显的两类:显式译注标记、
# 现代白话虚词密度显著高于文言虚词密度(公版原文/点校本正文应以文言虚词为主)。

_TRANSLATION_MARKER_RE = re.compile(r"(译文|白话文|今译|【注】|\[注\]|译\s*[:：]|翻译\s*[:：])")
_MODERN_PARTICLES = ("的", "了", "着", "呢", "吗", "啊", "呀", "地")
_CLASSICAL_PARTICLES = ("之", "乎", "者", "也", "矣", "焉", "哉", "耳", "其", "以")
_MIN_LEN_FOR_DENSITY_CHECK = 200
_MODERN_TO_CLASSICAL_RATIO_THRESHOLD = 2.0
_MIN_CLASSICAL_DENSITY = 0.005


def lint_copyright(raw_text: str) -> GateResult:
    """T1:命中已知译本特征 → 拒收。"""
    errors: list[str] = []

    m = _TRANSLATION_MARKER_RE.search(raw_text)
    if m:
        errors.append(f"命中译注标记 {m.group(0)!r},疑似译本/注本文字而非原文")

    if len(raw_text) >= _MIN_LEN_FOR_DENSITY_CHECK:
        modern_count = sum(raw_text.count(p) for p in _MODERN_PARTICLES)
        classical_count = sum(raw_text.count(p) for p in _CLASSICAL_PARTICLES)
        classical_density = classical_count / len(raw_text)
        if (
            classical_density < _MIN_CLASSICAL_DENSITY
            and modern_count > classical_count * _MODERN_TO_CLASSICAL_RATIO_THRESHOLD
        ):
            errors.append(
                f"现代白话虚词密度({modern_count})显著高于文言虚词密度({classical_count}),"
                "疑似白话译文而非原文"
            )

    return GateResult(passed=not errors, errors=errors)


# ── narration 考据对勘门(SPEC-005-V2,2026-07-24 商鞅立木首跑实证缺口)──────────────
# G2 史实门查禁词/对白语义一致/事件级幻觉/quote_id,**不查 narration 里的地名/数字精度**——
# 商鞅立木首跑撞见 narration 编"咸阳"(应栎阳)+"一丈"(原文三丈),两处都溜过 G2。这道门与
# chapter_ir 原文对勘:narration 里出现的数字/地名/忌讳器物,原文明载的必须一致(冲突→error),
# 原文没有的标 speculation(→warning,需人确认年代)。不做全考据引擎,纯字符串对勘,~零成本。
_NUM_UNIT_RE = re.compile(
    r"([一二三四五六七八九十百千两半]+)(丈|尺|寸|里|步|金|斤|石|人|年|月|日|世|万)"
)
# 地名候选:1-3 汉字 + 常见地名后缀(阳/京/城/都/关/郡/县/邑/陵/丘/口)
_PLACE_RE = re.compile(r"([一-鿿]{1,3}(?:阳|京|城|都|关|郡|县|邑|陵|丘|口))")
# 明显晚于先秦的忌讳器物/制度(粗粒度锚,战国场景 narration 里出现即疑穿帮)
_ANACHRONISM_TERMS = (
    "马镫",
    "纸",
    "椅子",
    "椅",
    "桌子",
    "板凳",
    "棉花",
    "棉布",
    "火药",
    "瓷器",
    "科举",
    "轿子",
    "眼镜",
    "钟表",
)


def lint_narration_source_parity(script: Any, raw_text: str) -> GateResult:
    """narration 与 chapter_ir 原文对勘(SPEC-005-V2)。查三类:①数字(原文明载的量词数字冲突
    →error,如原文三丈 vs narration 一丈);②地名(narration 地名原文未载→warning speculation,
    如咸阳);③忌讳器物(明显年代错误→warning)。只看 type==narration 的行。`raw_text`=该段源
    原文(同 lint_copyright 约定)。纯确定性字符串对勘,不调 LLM。"""
    narr = "".join(getattr(ln, "text", "") for ln in script.lines if ln.type == "narration")
    errors: list[str] = []
    warnings: list[str] = []

    # ① 数字对勘:原文里每个量词的数字集合;narration 同量词出现不同数字 → 冲突
    src_by_unit: dict[str, set[str]] = {}
    for num, unit in _NUM_UNIT_RE.findall(raw_text):
        src_by_unit.setdefault(unit, set()).add(num)
    for num, unit in _NUM_UNIT_RE.findall(narr):
        if unit in src_by_unit and num not in src_by_unit[unit]:
            src_nums = "/".join(sorted(src_by_unit[unit]))
            errors.append(f"narration 数字「{num}{unit}」与原文「{src_nums}{unit}」冲突")

    # ② 地名对勘:narration 里的地名,原文未载 → speculation(需人确认年代一致)
    warnings.extend(
        f"narration 地名「{place}」原文未载,系推测,需人确认与该事件年代一致"
        for place in dict.fromkeys(_PLACE_RE.findall(narr))  # 去重保序
        if place not in raw_text
    )

    # ③ 忌讳器物:明显晚于时代的物件/制度出现在 narration
    warnings.extend(
        f"narration 出现疑似年代错误器物/制度「{term}」,需人确认"
        for term in _ANACHRONISM_TERMS
        if term in narr and term not in raw_text
    )

    return GateResult(passed=not errors, errors=errors, warnings=warnings)


# ── T2 画面节奏 lint(SPEC-005 §2.2)—— 单画面时长过长/过短 → 警告 ───────────

_MIN_SHOT_DURATION_S = 5.0
_MAX_SHOT_DURATION_S = 25.0


def lint_shot_pacing(shotlist: ShotList) -> GateResult:
    """T2:单 shot 时长 >25s 或 <5s → warning(不阻断,呼应"流水线永不卡死")。"""
    warnings: list[str] = []
    for shot in shotlist.shots:
        duration_s = (shot.t_end_ms - shot.t_start_ms) / 1000
        if duration_s > _MAX_SHOT_DURATION_S:
            warnings.append(
                f"{shot.shot_id} 画面时长 {duration_s:.1f}s 超过 {_MAX_SHOT_DURATION_S}s"
            )
        elif 0 < duration_s < _MIN_SHOT_DURATION_S:
            warnings.append(
                f"{shot.shot_id} 画面时长 {duration_s:.1f}s 低于 {_MIN_SHOT_DURATION_S}s"
            )
    return GateResult(passed=True, warnings=warnings)
