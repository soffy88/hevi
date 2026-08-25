"""Step 3 派发层 —— SeasonPlan → Series + 逐集 VideoTask。见 SPEC-001 §3.2 / §7 阶段 1。

冻结决策:短剧 = Series 的一种用法(season_id = series_id),下游生成全链复用。本层不改
`SeriesService`,只做适配:
  ① 把 SeasonPlan 落成一个 Series(角色组 / StylePack / 规格锁,全季共用)。
  ② 每个 EpisodePlan 合成一段"剧情 brief"文本当 topic,调现有 `create_episode()` 建 inheriting
     VideoTask —— 逐集分镜/生成/一致性/裁决全部走现有管线。

关键降维:EpisodePlan 是富结构(节拍/角色/场景/情感弧),现有 Director 入口吃的是叙事文本
(topic)。`episode_brief()` 把结构降维成 Director 能storyboard 的一段本集剧情简报。跨集身份
一致(G1)靠 Series 的 subject_ids —— 由调用方在 Subject 建好后通过 subject_id_map 绑定。
"""

from __future__ import annotations

import logging
from typing import Any

from hevi.production.delivery_promise import (
    PromiseType,
    classify_from_brief,
)
from hevi.season_planner.schemas import EpisodePlan, SeasonPlan
from hevi.storygraph.schemas import StoryGraph

logger = logging.getLogger(__name__)


# spec 里 delivery_promise 字符串 → PromiseType 的兼容映射(与成片侧 delivery_gate
# 的 "motion"/"any" 取值对齐)。不在映射内的按字面值回退 classify_from_brief。
_PROMISE_STR_TO_TYPE: dict[str, PromiseType] = {
    "motion": PromiseType.MOTION_LED,
    "any": PromiseType.HYBRID,
    "motion_led": PromiseType.MOTION_LED,
    "source_led": PromiseType.SOURCE_LED,
    "data_explainer": PromiseType.DATA_EXPLAINER,
    "teacher_explainer": PromiseType.TEACHER_EXPLAINER,
    "screen_demo": PromiseType.SCREEN_DEMO,
    "avatar_presenter": PromiseType.AVATAR_PRESENTER,
    "hybrid": PromiseType.HYBRID,
    "localization": PromiseType.LOCALIZATION,
}


def resolve_delivery_promise(
    spec: dict[str, Any] | None,
    *,
    has_source_media: bool = False,
) -> tuple[Any, list[str]]:
    """排产前门: 把 spec 里的交付承诺升格为结构化 DeliveryPromise。

    优先级:
      1. spec["delivery_promise"] 已是 dict → DeliveryPromise.from_dict 透传。
      2. spec["delivery_promise"] 是字符串 → 映射 PromiseType 后 classify。
      3. spec["pipeline_type"] → classify_from_brief 推断。
      4. 都缺 → 默认 HYBRID。

    返回 (promise, gate_notes)。gate_notes 只记不拦 —— 排产骨架/dry-run 也可跑。
    承诺若要求真实视频(motion_led / avatar_presenter)但没给 video_provider,
    或要求素材(source_led)却没检测到素材, 都记 note 供调用方看板展示。
    """
    spec = spec or {}
    notes: list[str] = []

    raw = spec.get("delivery_promise")
    if isinstance(raw, dict):
        promise = classify_from_brief(
            str(spec.get("pipeline_type") or ""), {}
        )
        promise = type(promise).from_dict(raw)
    elif isinstance(raw, str) and raw in _PROMISE_STR_TO_TYPE:
        promise = classify_from_brief(
            str(spec.get("pipeline_type") or ""),
            {"promise_type": _PROMISE_STR_TO_TYPE[raw].value},
        )
        # classify_from_brief 只看管线名与意图键, 手动覆盖 promise_type:
        from hevi.production.delivery_promise import DeliveryPromise

        promise = DeliveryPromise(
            promise_type=_PROMISE_STR_TO_TYPE[raw],
            motion_required=_PROMISE_STR_TO_TYPE[raw]
            in (PromiseType.MOTION_LED, PromiseType.AVATAR_PRESENTER),
            source_required=bool(
                spec.get("has_footage")
                or spec.get("pipeline_type") in ("source_led", "podcast-repurpose", "clip-factory")
            ),
            tone_mode=str(spec.get("tone") or "corporate"),
            quality_floor=str(spec.get("quality_profile") or spec.get("quality") or "presentable"),
        )
    else:
        promise = classify_from_brief(
            str(spec.get("pipeline_type") or ""),
            {
                "motion_required": spec.get("motion_required"),
                "has_footage": spec.get("has_footage"),
                "tone": spec.get("tone"),
                "quality": spec.get("quality_profile") or spec.get("quality"),
            },
        )

    # 前置约束检查(只记不拦)
    if (
        promise.promise_type in (PromiseType.MOTION_LED, PromiseType.AVATAR_PRESENTER)
        and not spec.get("video_provider")
    ):
        notes.append(
            f"承诺 {promise.promise_type.value} 需要真实视频生成, 但 spec 未给 video_provider"
        )
    if promise.source_required and not has_source_media:
        notes.append(
            f"承诺 {promise.promise_type.value} 依赖用户素材, 但未检测到素材文件"
        )

    return promise, notes


def episode_brief(ep: EpisodePlan, story: StoryGraph) -> str:
    """把一集的 EpisodePlan 降维成现有 Director 能消费的本集剧情简报(topic 文本)。

    只用 StoryGraph 里已确定性组装的内容(事件摘要 + 本集台词),不新增创作 —— 台词沿用
    原文对白(叙事红线:短剧台词只准改写自 story.quotes)。
    """
    ev_by_id = {e.event_id: e for e in story.events}
    name_by_id = {c.char_id: c.name for c in story.characters}
    desc_by_id = {c.char_id: c.description for c in story.characters}

    parts: list[str] = []
    if ep.title:
        parts.append(f"【第{ep.ep_number}集 · {ep.title}】")
    if ep.target_emotion_arc:
        parts.append(f"情感基调:{ep.target_emotion_arc}")

    if ep.characters_present:
        who = "、".join(
            f"{name_by_id.get(cid, cid)}({desc_by_id[cid]})"
            if desc_by_id.get(cid)
            else name_by_id.get(cid, cid)
            for cid in ep.characters_present
        )
        parts.append(f"出场角色:{who}")

    # 剧情:按本集事件顺序列摘要 + 节拍
    plot_lines = []
    for eid in ep.event_ids:
        e = ev_by_id.get(eid)
        if e is None:
            continue
        beat = f"[{e.beat_type}]" if e.beat_type else ""
        plot_lines.append(f"{beat}{e.summary}")
    if plot_lines:
        parts.append("剧情:" + " → ".join(plot_lines))

    # 关键台词:本集事件下的原文对白(供 Director 保留人物声口)
    ep_event_ids = set(ep.event_ids)
    quotes = [q for q in story.quotes if q.event_id in ep_event_ids]
    if quotes:
        quote_lines = [
            f"{name_by_id.get(q.speaker, q.speaker)}:「{q.modern or q.original}」" for q in quotes
        ]
        parts.append("关键台词:" + " ".join(quote_lines))

    return "\n".join(parts)


async def dispatch_season(
    plan: SeasonPlan,
    story: StoryGraph,
    *,
    series_service: Any,
    task_service: Any = None,
    subject_id_map: dict[str, str] | None = None,
    subject_ref_paths: dict[str, str] | None = None,
    style_pack_id: str | None = None,
    spec: dict[str, Any] | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """SeasonPlan → 建 Series + 逐集建 VideoTask。返回 {series_id, episodes:[task...]}。

    subject_id_map: char_id → subject_id(调用方在 Subject 建好后传入,决定 Series 角色组,
    跨集身份一致的锚)。缺省则 Series 无角色锁(Director 走 t2v,适合骨架/dry-run)。
    """
    # 全季角色组:优先用传入的绑定,回退 SeasonPlan.subject_refs 里已回填的 subject_id。
    sid_map = dict(subject_id_map or {})
    subject_ids: list[str] = []
    for ref in plan.subject_refs:
        sid = sid_map.get(ref.char_id) or ref.subject_id
        if sid and sid not in subject_ids:
            subject_ids.append(sid)

    # 排产前门: 升格交付承诺(字符串 → 结构化 DeliveryPromise), 只记 note 不拦。
    promise, gate_notes = resolve_delivery_promise(
        spec,
        has_source_media=bool(subject_ref_paths or subject_ids),
    )
    promise_dict = promise.to_dict()

    series = await series_service.create_series(
        name=plan.story_source or "未命名短剧",
        subject_ids=subject_ids,
        style_pack_id=style_pack_id or plan.stylepack_ref,
        spec=spec or {},
        user_id=user_id,
    )
    series_id = str(series["id"])
    # season = series:回填 plan.season_id(内存对象,便于调用方拿到绑定)
    plan.season_id = series_id

    # SPEC-001 §5:跨集角色关系一致性守护(Tier0)要在生成后核对本集台词跟 StoryGraph
    # 关系状态是否矛盾,但 task_service/run_task 侧拿不到 StoryGraph 对象——同 episode_plan
    # 的做法,把它需要的那一小份(relationships + characters 的 name/aliases)也塞进
    # config_json,零建表、零迁移。全季共用同一份,每集都塞一份(JSONB,代价可忽略)。
    story_relationships = [r.model_dump() for r in story.relationships]
    story_characters = [
        {"char_id": c.char_id, "name": c.name, "aliases": c.aliases} for c in story.characters
    ]

    episodes: list[dict[str, Any]] = []
    for ep in plan.episodes:
        brief = episode_brief(ep, story)
        # 把本集节拍结构塞进 task.config_json["episode_plan"](经 overrides round-trip),
        # 供剧集看板做幕级视图 —— 零建表、零迁移(config_json 是 JSONB)。
        task = await series_service.create_episode(
            series_id,
            topic=brief,
            task_service=task_service,
            overrides={
                "episode_plan": ep.model_dump(),
                "story_relationships": story_relationships,
                "story_characters": story_characters,
                "shortdrama_story": story.model_dump(mode="json"),
                "shortdrama_subject_id_map": dict(subject_id_map or {}),
                "shortdrama_subject_ref_paths": dict(subject_ref_paths or {}),
                **(
                    {"locked_director": spec.get("locked_director")}
                    if isinstance(spec, dict) and spec.get("locked_director")
                    else {}
                ),
                **(
                    {"delivery_promise": spec.get("delivery_promise")}
                    if isinstance(spec, dict) and spec.get("delivery_promise")
                    else {}
                ),
                # 结构化承诺(提案侧合同) —— 下游合成阶段可用 promise.validate_cuts
                # 校验切点合规; 字符串 delivery_promise 保留给成片侧 delivery_gate。
                "delivery_promise_spec": promise_dict,
            },
        )
        episodes.append(task)

    logger.info(
        "dispatch_season: series=%s episodes=%d promise=%s notes=%d",
        series_id, len(episodes), promise.promise_type.value, len(gate_notes),
    )
    return {
        "series_id": series_id,
        "episodes": episodes,
        "delivery_promise": promise_dict,
        "gate_notes": gate_notes,
    }
