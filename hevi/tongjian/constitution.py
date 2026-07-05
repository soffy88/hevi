"""L1 立意 —— chapter_ir → constitution.json("创作宪法")。见 HEVI-SPEC-01 §2。

产物不是一句主题,而是下游所有层都要注入的创作宪法,风格一致性全靠它。spec 给的降级
策略是"生成 3 版 → LLM-as-judge 按史实覆盖+戏剧性打分取最优"——在全自动模式下,这不是
失败兜底,而是标准操作(用 best-of-N 代替人工挑选)。所以 `build_constitution()` 默认就
跑 3 个候选 + judge,不是"先试 1 个,失败了才生成 3 个"。

G1 的三项硬检查(event_id 引用闭环 / 关键事件不丢 / 时长与事件数匹配)全部是确定性代码,
不需要 LLM——只有"生成候选"和"judge 选优"这两步用 LLM。
"""

from __future__ import annotations

import logging
from typing import Any

from hevi.tongjian.chapter_ir import _call_llm_json, _extract_json_obj
from hevi.tongjian.schemas import Act, ChapterIR, Constitution, GateResult, VisualStyle

logger = logging.getLogger(__name__)

_MIN_SEC_PER_EVENT = 10
_MAX_SEC_PER_EVENT = 45

_CONSTITUTION_PROMPT_TEMPLATE = """你是历史短片的创作宪法(creative brief)撰写者。基于下面的事件列表,
为一部历史解说短片写"创作宪法"——它会被下游所有环节(剧本/分镜/画面/配乐)当作风格圣经使用。

事件列表(event_id: 摘要 [戏剧性权重 1-5]):
{event_lines}

只输出一个 JSON 对象,格式如下:
{{
  "thesis": "一句话立意(此章讲的是什么道理/主题)",
  "logline": "一句话故事梗概",
  "narrative_stance": "叙事视角(如:上帝视角旁白+史评穿插)",
  "tone": ["基调关键词", "..."],
  "visual_style": {{
    "art_direction": "美术方向描述",
    "palette": ["#hex色值", "..."],
    "aspect_ratio": "16:9",
    "negative_style": ["要避免的视觉风格", "..."]
  }},
  "act_structure": [
    {{"act": 1, "title": "幕标题", "events": ["event_id", "..."], "emotion_curve": "情绪曲线描述"}}
  ],
  "forbidden": ["现代梗", "戏说腔", "未出现于原文的情节"],
  "target_duration_sec": 整数(成片目标时长秒数),
  "bgm_mood_arc": ["配乐情绪走向关键词", "..."]
}}

硬性规则:
1. act_structure 里的 events 只能引用上面事件列表里出现过的 event_id,一字不差,不得杜撰。
2. 戏剧性权重 >= 4 的事件必须被收录进某一幕,不能遗漏。
3. target_duration_sec 应与所收录事件总数匹配,平均每个事件 {min_sec}-{max_sec} 秒。
"""


def _build_prompt(chapter_ir: ChapterIR) -> str:
    event_lines = "\n".join(
        f"{e.event_id}: {e.summary} [{e.dramatic_weight}]" for e in chapter_ir.events
    )
    return _CONSTITUTION_PROMPT_TEMPLATE.format(
        event_lines=event_lines, min_sec=_MIN_SEC_PER_EVENT, max_sec=_MAX_SEC_PER_EVENT
    )


def _coerce_constitution(draft: dict[str, Any]) -> Constitution:
    vs = draft.get("visual_style") or {}
    visual_style = VisualStyle(
        art_direction=str(vs.get("art_direction") or ""),
        palette=[str(p) for p in (vs.get("palette") or [])],
        aspect_ratio=str(vs.get("aspect_ratio") or "16:9"),
        negative_style=[str(s) for s in (vs.get("negative_style") or [])],
    )
    acts = []
    for i, a in enumerate(draft.get("act_structure") or [], start=1):
        acts.append(
            Act(
                act=int(a.get("act") or i),
                title=str(a.get("title") or ""),
                events=[str(eid) for eid in (a.get("events") or [])],
                emotion_curve=str(a.get("emotion_curve") or ""),
            )
        )
    return Constitution(
        thesis=str(draft.get("thesis") or ""),
        logline=str(draft.get("logline") or ""),
        narrative_stance=str(draft.get("narrative_stance") or ""),
        tone=[str(t) for t in (draft.get("tone") or [])],
        visual_style=visual_style,
        act_structure=acts,
        forbidden=[str(f) for f in (draft.get("forbidden") or [])],
        target_duration_sec=int(draft.get("target_duration_sec") or 180),
        bgm_mood_arc=[str(b) for b in (draft.get("bgm_mood_arc") or [])],
    )


async def generate_constitution(chapter_ir: ChapterIR, *, llm: Any = None) -> Constitution:
    """chapter_ir → 单个候选 constitution。LLM 调用失败 → 返回空壳(降级,不阻塞)。"""
    if llm is None:
        from obase.provider_registry import ProviderRegistry

        llm = ProviderRegistry.get().llm("default")

    prompt = _build_prompt(chapter_ir)
    try:
        draft = await _call_llm_json(llm, prompt)
    except Exception as e:
        logger.warning("constitution 生成 LLM 调用失败,返回空壳: %s", e)
        draft = {}
    return _coerce_constitution(draft)


def gate_constitution(constitution: Constitution, chapter_ir: ChapterIR) -> GateResult:
    """G1 门。全部确定性检查,不需要 LLM。"""
    known_event_ids = {e.event_id for e in chapter_ir.events}
    referenced = [eid for act in constitution.act_structure for eid in act.events]
    referenced_set = set(referenced)
    errors: list[str] = []

    unknown = sorted(referenced_set - known_event_ids)
    if unknown:
        errors.append(f"act_structure 引用了不存在的 event_id: {unknown}")

    critical_ids = {e.event_id for e in chapter_ir.events if e.dramatic_weight >= 4}
    missing_critical = sorted(critical_ids - referenced_set)
    if missing_critical:
        errors.append(f"戏剧性权重>=4 的关键事件未被任何一幕收录: {missing_critical}")

    covered_events = referenced_set & known_event_ids
    n_events = len(covered_events)
    if n_events > 0:
        per_event = constitution.target_duration_sec / n_events
        if not (_MIN_SEC_PER_EVENT <= per_event <= _MAX_SEC_PER_EVENT):
            errors.append(
                f"target_duration_sec={constitution.target_duration_sec} 与事件数 {n_events} 不匹配"
                f"(每事件 {per_event:.1f}s,应在 [{_MIN_SEC_PER_EVENT},{_MAX_SEC_PER_EVENT}])"
            )

    coverage = (len(critical_ids & referenced_set) / len(critical_ids)) if critical_ids else 1.0
    return GateResult(passed=not errors, coverage=coverage, errors=errors)


async def _judge_best(candidates: list[Constitution], chapter_ir: ChapterIR, llm: Any) -> int:
    """LLM-as-judge:按"史实覆盖+戏剧性"在候选间打分选优。judge 调用失败 →
    退化成按 gate 硬检查结果(先看是否通过,再看 coverage)确定性排序,而不是抛异常。
    """
    if len(candidates) == 1:
        return 0

    lines = []
    for i, c in enumerate(candidates):
        n_acts = len(c.act_structure)
        n_events = len({eid for act in c.act_structure for eid in act.events})
        lines.append(
            f"{i}: thesis={c.thesis!r} logline={c.logline!r} 幕数={n_acts} 覆盖事件数={n_events}"
        )
    prompt = (
        "下面是同一批历史事件写出的几版创作宪法候选,按「史实覆盖完整度 + 戏剧性」打分,"
        '选出最优的一个。只输出 JSON: {"best_index": 整数}\n\n' + "\n".join(lines)
    )
    try:
        resp = await llm(messages=[{"role": "user", "content": prompt}], max_tokens=100)
        content = resp.get("content") if hasattr(resp, "get") else str(resp)
        verdict = _extract_json_obj(content)
        idx = verdict.get("best_index")
        if isinstance(idx, int) and 0 <= idx < len(candidates):
            return idx
    except Exception as e:
        logger.warning("constitution judge LLM 调用失败,退化为按 gate 结果排序: %s", e)

    scored = sorted(
        range(len(candidates)),
        key=lambda i: (
            not gate_constitution(candidates[i], chapter_ir).passed,
            -_coverage(candidates[i], chapter_ir),
        ),
    )
    return scored[0]


def _coverage(constitution: Constitution, chapter_ir: ChapterIR) -> float:
    return gate_constitution(constitution, chapter_ir).coverage


async def build_constitution(
    chapter_ir: ChapterIR, *, llm: Any = None, n: int = 3
) -> tuple[Constitution, GateResult]:
    """L1 主入口:生成 n 个候选,LLM-as-judge 选优,返回 (最优候选, G1 门结果)。"""
    if llm is None:
        from obase.provider_registry import ProviderRegistry

        llm = ProviderRegistry.get().llm("default")

    candidates = [await generate_constitution(chapter_ir, llm=llm) for _ in range(n)]
    best_idx = await _judge_best(candidates, chapter_ir, llm)
    best = candidates[best_idx]
    return best, gate_constitution(best, chapter_ir)
