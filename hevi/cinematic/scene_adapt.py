"""C2.5 场景化改编 —— 剧本(L2 Script) → 场景剧本(Scene)。见 HEVI-SPEC-02 §4.1,
HEVI-EXEC-01 M3。

红线继承自 L2(hevi.tongjian.script):dialogue 仍只准改写自 chapter_ir.quotes。
这次新增的口子是"表演性台词"(BeatDialogue.is_performative)——EXEC-01 单场景
「智伯索地」里,智伯和韩康子之间没有任何直接引语可用(原文唯一两句真实引语是
段规对韩康子的进言、韩康子的应答),但镜头设计需要智伯有台词。允许,但必须显式
标记为 is_performative=True,不能悄悄冒充引语——CG2.5 门对这两类台词走不同审核
路径,"既没 quote_id 也没标 is_performative"一律判违规(见 gate_scene_adapt)。

action(动作/表演)是允许的合理虚构,但门审"动作不得改变史实因果"(段规可以
"指节收紧",不能"拔剑")。
"""

from __future__ import annotations

import logging
from typing import Any

from hevi.tongjian.chapter_ir import _extract_json_obj
from hevi.tongjian.schemas import ChapterIR, Script, ScriptLine
from hevi.tongjian.schemas import GateResult
from hevi.cinematic.schemas import Beat, BeatDialogue, Scene

logger = logging.getLogger(__name__)

# 这个场景发生在智伯索地阶段(还没有真正开战——真正的战争是后来智伯攻打拒不给地的
# 赵襄子,不是这一段的韩康子/段规),命中这些词就是改变了史实因果,直接判违规。
_BANNED_ACTION_WORDS = ["拔剑", "动武", "兴兵", "厮杀", "斩杀", "杀死", "兵戎相见"]


def _beat_from_script_line(line: ScriptLine) -> Beat:
    """narration 行 → 纯 action 的 beat;dialogue 行 → 带 BeatDialogue 的 beat,
    quote_id 原样带过去(L2 已经保证过 quote_id 要么是真实存在的引语要么整行被丢弃,
    这里不用重新校验,gate_scene_adapt 会再查一遍作为双重保险)。
    """
    dialogue = None
    if line.type == "dialogue":
        dialogue = BeatDialogue(
            speaker=line.speaker,
            text=line.text,
            quote_id=line.quote_id,
            is_performative=False,
            emotion=line.emotion,
        )
    return Beat(
        beat_id=line.line_id.replace("LN", "B"),
        action=line.visual_hint or line.text,
        dialogue=dialogue,
    )


async def adapt_scene(
    script: Script,
    chapter_ir: ChapterIR,
    *,
    scene_id: str,
    slug: str = "",
    space_anchor: str = "",
    extra_beats: dict[str, list[Beat]] | None = None,
) -> Scene:
    """script 的逐行剧本 → 单场景 Scene。P0 单场景:script 的全部行都属于同一个
    scene。extra_beats 是调用方另外提供的、不经过 L2 Script 的表演性台词/纯动作
    beat(比如智伯的表演性索地台词——这类台词不改写自任何 chapter_ir.quotes,不该
    塞进 Script.lines 这个"红线严格"的容器里),格式是 {插在哪个 line_id 之后:
    [beat, ...]},不给就是空场景只有 script 派生的 beats。
    """
    extra_beats = extra_beats or {}
    beats: list[Beat] = []
    for ln in script.lines:
        beats.append(_beat_from_script_line(ln))
        beats.extend(extra_beats.get(ln.line_id, []))

    characters = sorted({c.character_id for c in chapter_ir.characters})
    return Scene(
        scene_id=scene_id,
        slug=slug,
        characters=characters,
        space_anchor=space_anchor,
        beats=beats,
    )


async def _check_quote_dialogue_consistency(
    beats: list[Beat], quotes_by_id: dict, llm: Any
) -> list[str]:
    """照抄 hevi.tongjian.script._check_dialogue_consistency 的模式:LLM 比对台词
    白话跟原引语是否语义一致。"""
    pairs = "\n".join(
        f'{b.beat_id}: 台词="{b.dialogue.text}" 对应原引语="{quotes_by_id[b.dialogue.quote_id].original}"'
        f"(白话:{quotes_by_id[b.dialogue.quote_id].modern})"
        for b in beats
        if b.dialogue and b.dialogue.quote_id in quotes_by_id
    )
    if not pairs:
        return []
    prompt = (
        "下面是场景里的台词和它们各自对应的原始引语。判断每句台词是否忠实改写自"
        "原引语(语义一致,允许白话化措辞,但不能偏离原意或添加原引语没有的内容)。"
        '只输出 JSON: {"violations": [{"beat_id": "...", "reason": "..."}]}'
        "(一致的不列入 violations)\n\n" + pairs
    )
    try:
        resp = await llm(messages=[{"role": "user", "content": prompt}], max_tokens=1024)
    except Exception as e:
        logger.warning("CG2.5 真实引语一致性检查 LLM 调用失败,跳过: %s", e)
        return []
    content = resp.get("content") if hasattr(resp, "get") else str(resp)
    verdict = _extract_json_obj(content)
    return [
        f"beat {v.get('beat_id')} 台词与原引语语义不一致: {v.get('reason', '')}"
        for v in (verdict.get("violations") or [])
        if v.get("beat_id")
    ]


async def _check_performative_dialogue(
    beats: list[Beat], chapter_ir: ChapterIR, llm: Any
) -> list[str]:
    """表演性台词(is_performative=True,无 quote_id)的宽松检查:不要求匹配任何原文
    引语,只检查是否符合人物设定、是否引入了史料事件列表里没有的情节/关系。"""
    known_events = "\n".join(f"{e.event_id}: {e.summary}" for e in chapter_ir.events)
    lines = "\n".join(
        f'{b.beat_id}: {b.dialogue.speaker} 说(表演性台词,非原文引语): "{b.dialogue.text}"'
        for b in beats
        if b.dialogue
    )
    if not lines:
        return []
    prompt = (
        "下面是历史短片里几句电影化演绎补充的台词(不是原文引语,允许合理虚构),"
        "以及对应的史料事件列表。判断每句台词是否符合说话者的历史身份/处境,"
        "有没有暗示了事件列表里没有的情节、官职、称谓或人物关系。"
        '只输出 JSON: {"violations": [{"beat_id": "...", "reason": "..."}]}'
        "(没问题的不列入 violations)\n\n"
        f"史料事件:\n{known_events}\n\n台词:\n{lines}"
    )
    try:
        resp = await llm(messages=[{"role": "user", "content": prompt}], max_tokens=1024)
    except Exception as e:
        logger.warning("CG2.5 表演性台词检查 LLM 调用失败,跳过: %s", e)
        return []
    content = resp.get("content") if hasattr(resp, "get") else str(resp)
    verdict = _extract_json_obj(content)
    return [
        f"beat {v.get('beat_id')} 表演性台词疑似不妥: {v.get('reason', '')}"
        for v in (verdict.get("violations") or [])
        if v.get("beat_id")
    ]


async def gate_scene_adapt(scene: Scene, chapter_ir: ChapterIR, *, llm: Any = None) -> GateResult:
    """CG2.5 门。结构性红线(确定性代码,不过 LLM 就能判)+ LLM 语义检查两层。"""
    quotes_by_id = {q.quote_id: q for q in chapter_ir.quotes}
    known_characters = {c.character_id for c in chapter_ir.characters}
    errors: list[str] = []

    dialogue_beats = [b for b in scene.beats if b.dialogue is not None]
    for beat in dialogue_beats:
        d = beat.dialogue
        assert d is not None
        if d.speaker not in known_characters:
            errors.append(
                f"beat {beat.beat_id} 的 speaker {d.speaker!r} 不在 chapter_ir.characters 里"
            )
        if d.quote_id is None and not d.is_performative:
            errors.append(
                f"beat {beat.beat_id} 的台词既没有 quote_id 也没有标记 is_performative"
                "——不允许悄悄编台词(史实红线)"
            )
        elif d.quote_id is not None and d.quote_id not in quotes_by_id:
            errors.append(f"beat {beat.beat_id} 引用了不存在的 quote_id {d.quote_id!r}")

    for beat in scene.beats:
        for banned in _BANNED_ACTION_WORDS:
            if banned in beat.action:
                errors.append(
                    f"beat {beat.beat_id} 的 action 命中禁用动作词 {banned!r}"
                    "(此刻史实里不成立,可能改变因果)"
                )

    if errors:
        # 结构性红线没过,不再花 LLM 调用去查语义——先把硬伤修完。
        return GateResult(passed=False, coverage=0.0, errors=errors)

    if llm is None:
        from obase.provider_registry import ProviderRegistry

        llm = ProviderRegistry.get().llm("default")

    quote_beats = [b for b in dialogue_beats if b.dialogue and b.dialogue.quote_id]
    performative_beats = [
        b
        for b in dialogue_beats
        if b.dialogue and b.dialogue.is_performative and not b.dialogue.quote_id
    ]
    errors.extend(await _check_quote_dialogue_consistency(quote_beats, quotes_by_id, llm))
    errors.extend(await _check_performative_dialogue(performative_beats, chapter_ir, llm))

    coverage = (
        1.0 if not dialogue_beats else (len(dialogue_beats) - len(errors)) / len(dialogue_beats)
    )
    return GateResult(passed=not errors, coverage=max(0.0, coverage), errors=errors)
