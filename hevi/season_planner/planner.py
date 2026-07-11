"""剧集规划器 —— StoryGraph → SeasonPlan(切集 + 节拍分配 + 执行前自我批判)。见 SPEC-001 §3。

范式复用 tongjian L1(见 `hevi/tongjian/constitution.py`):LLM 只做创作性判断("怎么切集、
每集叫什么、情绪弧如何"),代码做确定性组装(characters_present/locations/beats 从 StoryGraph
派生)+ 确定性自我批判门(SPEC §3.4:集数可行 / 每集节拍完整 / 角色不断裂 / 事件全覆盖)。

- `generate_season_plan()` —— 单个候选(LLM 切分 + 代码组装)
- `gate_season_plan()`     —— G_SEASON 门,全确定性,不需 LLM(即 SPEC §3.4 的执行前自我批判)
- `build_season_plan()`    —— 主入口:best-of-N 候选 + LLM-as-judge 选优 + 门

LLM 显式选 qwen_cloud(非欠费云端);judge/生成失败均降级不抛异常,与 tongjian 一致。
复用 tongjian 的 `_call_llm_json`/`_extract_json_obj`(跨模块共享确定性 helper 约定)与
`GateResult`(统一门形状)。
"""

from __future__ import annotations

import logging
from typing import Any

from hevi.season_planner.schemas import (
    ContinuityConstraint,
    EpisodePlan,
    SeasonPlan,
    SubjectRef,
)
from hevi.storygraph.schemas import StoryGraph
from hevi.tongjian.chapter_ir import _call_llm_json, _extract_json_obj
from hevi.tongjian.schemas import GateResult

logger = logging.getLogger(__name__)

# 每集事件数的合理区间(集数是否撑得起原文体量的确定性判据,SPEC §3.4)。
_MIN_EVENTS_PER_EP = 1
_MAX_EVENTS_PER_EP = 12
# 角色断裂容忍度:同一角色两次出场之间最多允许缺席多少集(主角凭空消失三集 → 断裂)。
_MAX_ABSENCE_GAP = 2

_PLAN_PROMPT_TEMPLATE = """你是短剧/漫剧的剧集规划师。下面是一部作品的事件时间线(按顺序),
把它切成正好 {target_episodes} 集连续的短剧,每集是一段有起伏的完整戏。

事件时间线(event_id: 摘要 [戏剧性权重1-5] 节拍=beat_type 出场=角色):
{event_lines}

只输出一个 JSON 对象,不要任何其它文字,格式如下:
{{
  "episodes": [
    {{"ep_number": 1, "title": "本集标题",
      "event_ids": ["按时间顺序分配给本集的 event_id,一字不差", "..."],
      "target_emotion_arc": "本集情感目标(开场→高潮→收束的一句话描述)"}}
  ]
}}

硬性规则:
1. 必须正好切成 {target_episodes} 集,ep_number 从 1 连续编号。
2. 每个 event_id 必须且只能分配给一集,不得遗漏、不得重复、不得杜撰时间线里没有的 event_id。
3. 分集要保持时间顺序:靠前的事件在靠前的集,不得打乱因果。
4. 每集都应包含至少一个有冲突/转折/高潮的事件(戏剧性权重高的),不要出现一整集全是铺垫或过场。
"""


def _event_lines(story: StoryGraph) -> str:
    id_to_name = {c.char_id: c.name for c in story.characters}
    lines = []
    for e in story.events:
        actors = "、".join(id_to_name.get(a, a) for a in e.actors) or "—"
        beat = e.beat_type or "—"
        lines.append(f"{e.event_id}: {e.summary} [{e.dramatic_weight}] 节拍={beat} 出场={actors}")
    return "\n".join(lines)


def _assemble_episode(
    *, ep_number: int, title: str, event_ids: list[str], emotion_arc: str, story: StoryGraph
) -> EpisodePlan:
    """从 LLM 分给本集的 event_ids 出发,确定性组装角色/场景/节拍(不信 LLM 自己填这些)。"""
    ev_by_id = {e.event_id: e for e in story.events}
    loc_by_event: dict[str, list[str]] = {}
    for loc in story.locations:
        for eid in loc.events:
            loc_by_event.setdefault(eid, []).append(loc.name)

    valid_ids = [eid for eid in event_ids if eid in ev_by_id]
    chars: list[str] = []
    locations: list[str] = []
    beats: list[str] = []
    for eid in valid_ids:
        e = ev_by_id[eid]
        for a in e.actors:
            if a not in chars:
                chars.append(a)
        for name in loc_by_event.get(eid, []):
            if name not in locations:
                locations.append(name)
        if e.beat_type:
            beats.append(e.beat_type)
    return EpisodePlan(
        ep_number=ep_number,
        title=title,
        event_ids=valid_ids,
        beats=beats,
        characters_present=chars,
        locations=locations,
        target_emotion_arc=emotion_arc,
    )


def _build_continuity(episodes: list[EpisodePlan], story: StoryGraph) -> list[ContinuityConstraint]:
    """逐角色记录在哪几集出场(阶段 1 轻量版跨集约束)。"""
    present: dict[str, list[int]] = {}
    for ep in episodes:
        for cid in ep.characters_present:
            present.setdefault(cid, []).append(ep.ep_number)
    known = {c.char_id for c in story.characters}
    return [
        ContinuityConstraint(char_id=cid, present_in_episodes=sorted(eps))
        for cid, eps in present.items()
        if cid in known
    ]


def _coerce_season_plan(
    draft: dict[str, Any], story: StoryGraph, target_episodes: int
) -> SeasonPlan:
    episodes: list[EpisodePlan] = []
    for i, ep in enumerate(draft.get("episodes") or [], start=1):
        episodes.append(
            _assemble_episode(
                ep_number=int(ep.get("ep_number") or i),
                title=str(ep.get("title") or ""),
                event_ids=[str(eid) for eid in (ep.get("event_ids") or [])],
                emotion_arc=str(ep.get("target_emotion_arc") or ""),
                story=story,
            )
        )
    subject_refs = [
        SubjectRef(char_id=c.char_id, subject_id=c.subject_id, name=c.name)
        for c in story.characters
    ]
    return SeasonPlan(
        story_source=story.meta.source,
        target_episodes=target_episodes,
        subject_refs=subject_refs,
        episodes=episodes,
        continuity_constraints=_build_continuity(episodes, story),
    )


async def generate_season_plan(
    story: StoryGraph, *, target_episodes: int, llm: Any = None
) -> SeasonPlan:
    """StoryGraph → 单个候选 SeasonPlan。LLM 调用失败 → 返回空壳(降级,不阻塞)。"""
    if llm is None:
        from obase.provider_registry import ProviderRegistry

        llm = ProviderRegistry.get().llm("qwen_cloud")

    prompt = _PLAN_PROMPT_TEMPLATE.format(
        target_episodes=target_episodes, event_lines=_event_lines(story)
    )
    try:
        draft = await _call_llm_json(llm, prompt)
    except Exception as e:
        logger.warning("season_plan 生成 LLM 调用失败,返回空壳: %s", e)
        draft = {}
    return _coerce_season_plan(draft, story, target_episodes)


def gate_season_plan(plan: SeasonPlan, story: StoryGraph) -> GateResult:
    """G_SEASON 门 = SPEC §3.4 执行前自我批判。全部确定性检查,零生成成本。"""
    known_event_ids = {e.event_id for e in story.events}
    errors: list[str] = []
    warnings: list[str] = []

    # ① 集数正确
    if len(plan.episodes) != plan.target_episodes:
        errors.append(f"实际集数 {len(plan.episodes)} 与目标 {plan.target_episodes} 不符")

    # ② 事件全覆盖、无重复、无杜撰(时间线完整切分)
    assigned: list[str] = [eid for ep in plan.episodes for eid in ep.event_ids]
    assigned_set = set(assigned)
    if len(assigned) != len(assigned_set):
        dups = sorted({eid for eid in assigned if assigned.count(eid) > 1})
        errors.append(f"事件被分配到多集(重复): {dups}")
    missing = sorted(known_event_ids - assigned_set)
    if missing:
        errors.append(f"事件未被任何一集覆盖(遗漏): {missing}")
    unknown = sorted(assigned_set - known_event_ids)
    if unknown:
        errors.append(f"分集引用了时间线里不存在的 event_id: {unknown}")

    # ③ 每集节拍完整:不能一整集全是铺垫/过场(至少一个冲突/转折/高潮 或 高权重事件)
    weight_by_id = {e.event_id: e.dramatic_weight for e in story.events}
    beat_by_id = {e.event_id: e.beat_type for e in story.events}
    strong_beats = {"冲突", "转折", "高潮"}
    for ep in plan.episodes:
        has_conflict = any(
            beat_by_id.get(eid) in strong_beats or weight_by_id.get(eid, 0) >= 4
            for eid in ep.event_ids
        )
        if ep.event_ids and not has_conflict:
            errors.append(f"第 {ep.ep_number} 集全是铺垫/过场,无冲突或高潮")
        if not ep.event_ids:
            errors.append(f"第 {ep.ep_number} 集没有分到任何事件")

    # ④ 集数是否撑得起原文体量(每集事件数落在合理区间)
    if plan.episodes:
        avg = len(known_event_ids) / len(plan.episodes)
        if avg < _MIN_EVENTS_PER_EP:
            errors.append(f"集数偏多:平均每集仅 {avg:.1f} 个事件,撑不起一集戏")
        elif avg > _MAX_EVENTS_PER_EP:
            warnings.append(f"集数偏少:平均每集 {avg:.1f} 个事件,单集可能过载")

    # ⑤ 角色不断裂:同一角色两次出场之间缺席不得超过 _MAX_ABSENCE_GAP 集
    for cc in plan.continuity_constraints:
        eps = cc.present_in_episodes
        for a, b in zip(eps, eps[1:]):
            gap = b - a - 1
            if gap > _MAX_ABSENCE_GAP:
                errors.append(
                    f"角色 {cc.char_id} 在第 {a} 集后消失 {gap} 集才于第 {b} 集重现(角色断裂)"
                )
                break

    coverage = (
        (len(assigned_set & known_event_ids) / len(known_event_ids)) if known_event_ids else 1.0
    )
    return GateResult(passed=not errors, coverage=coverage, errors=errors, warnings=warnings)


async def _judge_best(candidates: list[SeasonPlan], story: StoryGraph, llm: Any) -> int:
    """LLM-as-judge:按"切分是否均衡+每集戏剧完整度"选优。失败 → 退化为按门结果确定性排序。"""
    if len(candidates) == 1:
        return 0

    lines = []
    for i, c in enumerate(candidates):
        sizes = [len(ep.event_ids) for ep in c.episodes]
        lines.append(
            f"{i}: 集数={len(c.episodes)} 各集事件数={sizes} 标题={[ep.title for ep in c.episodes]}"
        )
    prompt = (
        "下面是同一条事件时间线切出的几版分集候选,按「切分均衡度 + 每集戏剧完整度 + 标题吸引力」"
        '打分,选最优的一个。只输出 JSON: {"best_index": 整数}\n\n' + "\n".join(lines)
    )
    try:
        resp = await llm(messages=[{"role": "user", "content": prompt}], max_tokens=100)
        content = resp.get("content") if hasattr(resp, "get") else str(resp)
        verdict = _extract_json_obj(content)
        idx = verdict.get("best_index")
        if isinstance(idx, int) and 0 <= idx < len(candidates):
            return idx
    except Exception as e:
        logger.warning("season_plan judge LLM 调用失败,退化为按门结果排序: %s", e)

    scored = sorted(
        range(len(candidates)),
        key=lambda i: (
            not gate_season_plan(candidates[i], story).passed,
            -gate_season_plan(candidates[i], story).coverage,
        ),
    )
    return scored[0]


async def build_season_plan(
    story: StoryGraph, *, target_episodes: int, llm: Any = None, n: int = 3
) -> tuple[SeasonPlan, GateResult]:
    """剧集规划主入口:生成 n 个候选,LLM-as-judge 选优,返回 (最优候选, G_SEASON 门结果)。"""
    if llm is None:
        from obase.provider_registry import ProviderRegistry

        llm = ProviderRegistry.get().llm("qwen_cloud")

    candidates = [
        await generate_season_plan(story, target_episodes=target_episodes, llm=llm)
        for _ in range(n)
    ]
    best_idx = await _judge_best(candidates, story, llm)
    best = candidates[best_idx]
    return best, gate_season_plan(best, story)
