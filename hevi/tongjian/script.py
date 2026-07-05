"""L2 剧本 —— constitution + chapter_ir → script.json。见 HEVI-SPEC-01 §3。

史实红线:dialogue 行只能改写自 chapter_ir.quotes,LLM 不得原创台词。生成阶段就地强制——
quote_id 对不上 chapter_ir 里真实存在的引语 → 整行丢弃,不降级成"改成旁白"。这里比 L0
丢弃幻觉引语更严格,因为留着不丢就是让观众听见一句编出来的台词。

line_id 一律由代码顺序分配(LN001/LN002/...),不采信 LLM 自报的 ID——理由与 L0 的
character_id/event_id 分配策略相同:LLM 引用它、不发明它。

G2 是全管线最重要的门(史实门),四项检查:
1. dialogue 语义一致性(LLM 比对台词与原引语)
2. 全文情节/官职/称谓幻觉扫描(LLM 通读全篇 vs chapter_ir 事件列表)
3. forbidden 违禁词扫描(确定性子串匹配 constitution.forbidden + 现代词汇黑名单)
4. 字数与 target_duration 偏差 ≤ 15%(确定性计算,中文口播 ≈4.5 字/秒,留 15% 给停顿/呼吸)

降级:违规行定点重写(只喂该行上下文,不重跑整篇剧本),最多 3 次;仍不过 → 直接删除
该行(相邻旁白已经承担叙事桥接,不必在"防止编造"的门里自己再编一句新旁白)。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from hevi.tongjian.chapter_ir import _call_llm_json, _extract_json_obj
from hevi.tongjian.schemas import ChapterIR, Constitution, GateResult, Script, ScriptLine

logger = logging.getLogger(__name__)

_CHARS_PER_SEC = 4.5
_PAUSE_FACTOR = 0.85
_MAX_DURATION_DEVIATION = 0.15
_MAX_REWRITE_ATTEMPTS = 3
_VALID_LINE_TYPES = {"narration", "dialogue", "commentary"}
_LINE_ID_RE = re.compile(r"(LN\d+)")

# 现代词汇黑名单(起始版,遇到新违规词直接往里加即可,不必等 RFC)。
_MODERN_VOCAB_BLACKLIST = [
    "点赞",
    "关注",
    "打卡",
    "网红",
    "破防",
    "yyds",
    "绝绝子",
    "内卷",
    "躺平",
    "OK",
    "拜拜",
]

_SCRIPT_PROMPT_TEMPLATE = """你是历史解说短片编剧。基于下面的创作宪法和分幕事件/引语,写逐行剧本。

创作宪法:
基调: {tone}
叙事视角: {narrative_stance}
禁忌: {forbidden}

分幕事件与引语:
{act_blocks}

目标字数: 约 {target_chars} 字(对应 {target_duration_sec} 秒口播)

只输出一个 JSON 对象:
{{"lines": [
  {{"act": 1, "type": "narration|dialogue|commentary",
    "speaker": "NARRATOR 或人物 character_id(仅 dialogue 用)",
    "text": "这一行的文本", "event_id": "锚定的 event_id",
    "quote_id": "仅 dialogue 行填,必须是上面列出的引语 quote_id,一字不差",
    "emotion": "情绪", "visual_hint": "画面提示"}}
]}}

硬性规则:
1. type=dialogue 的行,text 必须是对应 quote_id 原引语的白话改写,不得脱离原引语另编台词。
2. 每行必须填 event_id,且必须是上面分幕列出的 event_id 之一。
3. 不得使用禁忌清单里的元素,不得加入原文没有的情节/官职/称谓。
4. 总字数尽量贴近目标字数。
"""


def _build_script_prompt(constitution: Constitution, chapter_ir: ChapterIR) -> str:
    events_by_id = {e.event_id: e for e in chapter_ir.events}
    quotes_by_event: dict[str, list] = {}
    for q in chapter_ir.quotes:
        if q.event_id:
            quotes_by_event.setdefault(q.event_id, []).append(q)

    act_blocks = []
    for act in constitution.act_structure:
        block_lines = [f"幕 {act.act}:{act.title}(情绪:{act.emotion_curve})"]
        for eid in act.events:
            e = events_by_id.get(eid)
            if not e:
                continue
            block_lines.append(f"  {e.event_id}: {e.summary}")
            for q in quotes_by_event.get(eid, []):
                block_lines.append(
                    f"    引语[{q.quote_id}] {q.speaker} 说(原文):{q.original} | 白话:{q.modern}"
                )
        act_blocks.append("\n".join(block_lines))

    target_chars = round(constitution.target_duration_sec * _CHARS_PER_SEC * _PAUSE_FACTOR)
    return _SCRIPT_PROMPT_TEMPLATE.format(
        tone=", ".join(constitution.tone),
        narrative_stance=constitution.narrative_stance,
        forbidden=", ".join(constitution.forbidden),
        act_blocks="\n".join(act_blocks),
        target_chars=target_chars,
        target_duration_sec=constitution.target_duration_sec,
    )


def _coerce_script(draft: dict[str, Any], chapter_ir: ChapterIR) -> Script:
    known_quote_ids = {q.quote_id for q in chapter_ir.quotes}
    known_event_ids = {e.event_id for e in chapter_ir.events}
    lines: list[ScriptLine] = []
    for ln in draft.get("lines") or []:
        line_type = str(ln.get("type") or "narration")
        if line_type not in _VALID_LINE_TYPES:
            line_type = "narration"

        quote_id = ln.get("quote_id")
        quote_id = str(quote_id) if quote_id else None
        if line_type == "dialogue" and quote_id not in known_quote_ids:
            logger.warning("dialogue 行引用了不存在的 quote_id %r,整行丢弃(史实红线)", quote_id)
            continue

        event_id = ln.get("event_id")
        event_id = str(event_id) if event_id and str(event_id) in known_event_ids else None

        lines.append(
            ScriptLine(
                line_id=f"LN{len(lines) + 1:03d}",
                act=int(ln.get("act") or 1),
                type=line_type,
                speaker=str(ln.get("speaker") or "NARRATOR"),
                text=str(ln.get("text") or ""),
                event_id=event_id,
                quote_id=quote_id,
                emotion=str(ln.get("emotion") or ""),
                visual_hint=str(ln.get("visual_hint") or ""),
            )
        )
    return Script(lines=lines)


async def generate_script(
    constitution: Constitution, chapter_ir: ChapterIR, *, llm: Any = None
) -> Script:
    """constitution + chapter_ir → 剧本草稿。LLM 调用失败 → 返回空壳(降级,不阻塞)。"""
    if llm is None:
        from obase.provider_registry import ProviderRegistry

        llm = ProviderRegistry.get().llm("default")

    prompt = _build_script_prompt(constitution, chapter_ir)
    try:
        draft = await _call_llm_json(llm, prompt)
    except Exception as e:
        logger.warning("script 生成 LLM 调用失败,返回空壳: %s", e)
        draft = {}
    return _coerce_script(draft, chapter_ir)


def _check_forbidden_terms(script: Script, constitution: Constitution) -> list[str]:
    banned = [t for t in (*constitution.forbidden, *_MODERN_VOCAB_BLACKLIST) if t]
    errors = []
    for ln in script.lines:
        for term in banned:
            if term in ln.text:
                errors.append(f"剧本行 {ln.line_id} 命中违禁词 {term!r}: {ln.text!r}")
    return errors


def _check_duration(script: Script, constitution: Constitution) -> list[str]:
    total_chars = sum(len(ln.text) for ln in script.lines)
    target_chars = constitution.target_duration_sec * _CHARS_PER_SEC * _PAUSE_FACTOR
    if target_chars <= 0:
        return []
    deviation = abs(total_chars - target_chars) / target_chars
    if deviation > _MAX_DURATION_DEVIATION:
        return [
            f"字数 {total_chars} 与目标字数 {target_chars:.0f}(对应 {constitution.target_duration_sec}s)"
            f"偏差 {deviation:.1%},超过 {_MAX_DURATION_DEVIATION:.0%} 门槛"
        ]
    return []


async def _check_dialogue_consistency(script: Script, chapter_ir: ChapterIR, llm: Any) -> list[str]:
    quotes_by_id = {q.quote_id: q for q in chapter_ir.quotes}
    dialogue_lines = [
        ln for ln in script.lines if ln.type == "dialogue" and ln.quote_id in quotes_by_id
    ]
    if not dialogue_lines:
        return []
    pairs = "\n".join(
        f'{ln.line_id}: 台词="{ln.text}" 对应原引语="{quotes_by_id[ln.quote_id].original}"'
        f"(白话:{quotes_by_id[ln.quote_id].modern})"
        for ln in dialogue_lines
    )
    prompt = (
        "下面是剧本台词行和它们各自对应的原始引语。判断每行台词是否忠实改写自原引语"
        "(语义一致,允许白话化措辞,但不能偏离原意或添加原引语没有的内容)。"
        '只输出 JSON: {"violations": [{"line_id": "...", "reason": "..."}]}'
        "(一致的行不列入 violations)\n\n" + pairs
    )
    try:
        resp = await llm(messages=[{"role": "user", "content": prompt}], max_tokens=1024)
    except Exception as e:
        logger.warning("dialogue 一致性审查 LLM 调用失败,跳过该检查: %s", e)
        return []
    content = resp.get("content") if hasattr(resp, "get") else str(resp)
    verdict = _extract_json_obj(content)
    return [
        f"台词行 {v.get('line_id')} 与原引语语义不一致: {v.get('reason', '')}"
        for v in (verdict.get("violations") or [])
        if v.get("line_id")
    ]


async def _check_hallucinated_content(script: Script, chapter_ir: ChapterIR, llm: Any) -> list[str]:
    known_events = "\n".join(f"{e.event_id}: {e.summary}" for e in chapter_ir.events)
    script_lines = "\n".join(f"{ln.line_id}[{ln.type}]: {ln.text}" for ln in script.lines)
    prompt = (
        "下面是史料事件列表和一份剧本逐行文本。逐行检查剧本是否出现了事件列表里没有的情节、"
        "官职、称谓或人物关系,即编造的内容。"
        '只输出 JSON: {"violations": [{"line_id": "...", "reason": "..."}]}'
        "(没问题的行不列入 violations)\n\n"
        f"事件列表:\n{known_events}\n\n剧本:\n{script_lines}"
    )
    try:
        resp = await llm(messages=[{"role": "user", "content": prompt}], max_tokens=1024)
    except Exception as e:
        logger.warning("剧本幻觉扫描 LLM 调用失败,跳过该检查: %s", e)
        return []
    content = resp.get("content") if hasattr(resp, "get") else str(resp)
    verdict = _extract_json_obj(content)
    return [
        f"剧本行 {v.get('line_id')} 疑似包含原文没有的情节/官职/称谓: {v.get('reason', '')}"
        for v in (verdict.get("violations") or [])
        if v.get("line_id")
    ]


async def gate_script(
    script: Script, chapter_ir: ChapterIR, constitution: Constitution, *, llm: Any = None
) -> GateResult:
    """G2 门(史实门)。"""
    if llm is None:
        from obase.provider_registry import ProviderRegistry

        llm = ProviderRegistry.get().llm("default")

    errors: list[str] = []
    errors.extend(_check_forbidden_terms(script, constitution))
    errors.extend(_check_duration(script, constitution))
    errors.extend(await _check_dialogue_consistency(script, chapter_ir, llm))
    errors.extend(await _check_hallucinated_content(script, chapter_ir, llm))

    dialogue_lines = [ln for ln in script.lines if ln.type == "dialogue"]
    missing_quote = [ln.line_id for ln in dialogue_lines if not ln.quote_id]
    if missing_quote:
        # 生成阶段已经把无 quote_id 的 dialogue 行丢弃了,这里只是双重保险。
        errors.append(f"dialogue 行缺少 quote_id: {missing_quote}")
    coverage = (
        ((len(dialogue_lines) - len(missing_quote)) / len(dialogue_lines))
        if dialogue_lines
        else 1.0
    )

    return GateResult(passed=not errors, coverage=coverage, errors=errors)


def _violations_by_line(errors: list[str]) -> dict[str, list[str]]:
    """从 GateResult.errors 里挖出形如 "...行 LN00X..." 的 line_id,归并成 {line_id: [reasons]}。
    抓不到具体 line_id 的错误(如全篇字数偏差)不做定点重写,只能靠后续人工/上层处理。
    """
    grouped: dict[str, list[str]] = {}
    for err in errors:
        m = _LINE_ID_RE.search(err)
        if m:
            grouped.setdefault(m.group(1), []).append(err)
    return grouped


async def _rewrite_line(
    line: ScriptLine, violation_reason: str, chapter_ir: ChapterIR, llm: Any
) -> ScriptLine:
    """定点重写单行:只喂这一行的上下文,不重跑整篇剧本(省 token)。"""
    event = next((e for e in chapter_ir.events if e.event_id == line.event_id), None)
    quote = (
        next((q for q in chapter_ir.quotes if q.quote_id == line.quote_id), None)
        if line.quote_id
        else None
    )
    context = f"事件: {event.summary if event else '(未知)'}"
    if quote:
        context += f"\n原引语: {quote.original}(白话:{quote.modern})"
    prompt = (
        f"下面这行剧本被审查判定违规,原因:{violation_reason}\n"
        f"原行: type={line.type} speaker={line.speaker} text={line.text!r}\n"
        f"{context}\n"
        "请只重写 text 字段以消除违规,保持 type/speaker/event_id/quote_id 不变,"
        "dialogue 行不得脱离原引语另编台词。"
        '只输出 JSON: {"text": "重写后的文本"}'
    )
    try:
        resp = await llm(messages=[{"role": "user", "content": prompt}], max_tokens=300)
        content = resp.get("content") if hasattr(resp, "get") else str(resp)
        verdict = _extract_json_obj(content)
        new_text = verdict.get("text")
        if new_text:
            return line.model_copy(update={"text": str(new_text)})
    except Exception as e:
        logger.warning("定点重写行 %s 失败: %s", line.line_id, e)
    return line


async def build_script(
    constitution: Constitution, chapter_ir: ChapterIR, *, llm: Any = None
) -> tuple[Script, GateResult]:
    """L2 主入口:生成 → G2 门 → 违规行定点重写(最多 3 次)→ 仍不过则删除该行。"""
    if llm is None:
        from obase.provider_registry import ProviderRegistry

        llm = ProviderRegistry.get().llm("default")

    script = await generate_script(constitution, chapter_ir, llm=llm)
    result = await gate_script(script, chapter_ir, constitution, llm=llm)

    lines_by_id = {ln.line_id: ln for ln in script.lines}
    for _ in range(_MAX_REWRITE_ATTEMPTS):
        if result.passed:
            break
        grouped = _violations_by_line(result.errors)
        if not grouped:
            break  # 违规是全篇级别的(如总字数偏差),定点重写救不了
        for line_id, reasons in grouped.items():
            line = lines_by_id.get(line_id)
            if line is None:
                continue
            lines_by_id[line_id] = await _rewrite_line(line, "; ".join(reasons), chapter_ir, llm)
        script = Script(lines=[lines_by_id[lid] for lid in lines_by_id])
        result = await gate_script(script, chapter_ir, constitution, llm=llm)

    if not result.passed:
        grouped = _violations_by_line(result.errors)
        if grouped:
            for line_id in grouped:
                lines_by_id.pop(line_id, None)
            script = Script(lines=[lines_by_id[lid] for lid in lines_by_id])
            result = await gate_script(script, chapter_ir, constitution, llm=llm)

    return script, result
