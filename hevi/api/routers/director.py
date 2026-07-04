"""Director API —— L4 导演层入口:自然语言 + 结构化片表单 → 可行性预览 / 直接产集。设计 §3 L4。

  - POST /director/plan     NL → {intent, plan, shot_prompts, graph}(预览,不建任务)。
  - POST /director/episodes NL + 8 层片表单 → 可行性门 → 建任务 → 后台出片(含 L3 体检返工)。

结构化字段(画幅/风格/画质/角色/provider…)全部透传进 config_json,逐字段驱动 orchestrate。
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from obase.persistence import PgPool
from pydantic import BaseModel

from hevi.auth.dependencies import get_current_user
from hevi.canvas.executor_service import ExecutorService
from hevi.canvas.graph_repository import GraphRepository
from hevi.canvas.graph_service import GraphService
from hevi.cost.circuit_breaker import CostLimitExceeded
from hevi.credits.account_service import AccountService
from hevi.credits.billing_service import BillingService
from hevi.credits.repository import CreditRepository
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.director.graph_render import render_graph_episode
from hevi.director.intent import parse_intent
from hevi.director.planner import plan_from_text
from hevi.director.producer import produce
from hevi.subjects.repository import SubjectRepository
from hevi.subjects.subject_service import SubjectService
from hevi.tasks.repository import TaskRepository
from hevi.tasks.task_service import TaskService
from hevi.video.presets import EXECUTION_PRESETS
from hevi.video.quality_profile import get_quality_profile, resolve_resolution

router = APIRouter(prefix="/director", tags=["director"])


async def get_pg_pool() -> PgPool:
    return await get_hevi_pg_pool()


async def get_task_service(
    pool: Annotated[PgPool, Depends(get_pg_pool)],
) -> TaskService:
    return TaskService(TaskRepository(pool), BillingService(AccountService(CreditRepository(pool))))


class PlanRequest(BaseModel):
    text: str
    num_shots: int = 4
    character_reference: str | None = None


class EpisodeRequest(BaseModel):
    text: str
    # ① 立意
    duration_archetype: str | None = None  # 覆盖 LLM 猜的时长档
    aspect_ratio: str = "9:16"  # 9:16 竖 / 16:9 横 / 1:1 方
    mood: str | None = None  # 情绪基调(独立于 style_preset)
    genre: str | None = None  # 题材类型(剧情/科普/广告/vlog…)
    narrative_hook: str | None = None  # 叙事钩子:开场 3 秒抓手
    # ② 角色
    character_subject_ids: list[str] = []  # 多角色绑定;首个用于 i2v 跨镜锁脸,其余仅入人设描述
    subject_id: str | None = None  # 兼容单角色写法(优先于 character_subject_ids[0])
    avatar_portrait: str | None = None  # 数字人肖像
    num_characters: int | None = None
    # ③ 场景
    scene_notes: str | None = None  # 场景设定(地点/室内外/时间)
    props: str | None = None  # 关键道具/陈设
    # ④ 视觉风格
    style_preset: str | None = None  # 20 预设之一
    prompt_style: str | None = None
    prompt_lighting: str | None = None
    prompt_camera: str | None = None
    prompt_color_grade: str | None = None
    # ⑤ 分镜
    transition: str = "fade"
    per_shot_routing: bool = False
    # ⑥ 音频
    language: str = "zh"
    audio_provider: str | None = None
    bgm: str | None = None  # 背景音乐情绪(→ assets/audio/bgm/<mood>/)或文件路径
    sfx: str | None = None  # 音效名(前缀匹配 assets/audio/sfx/)或文件路径
    voice_rate: str | None = None  # 旁白语速,仅 edge_tts 生效,如 "+15%"
    voice_pitch: str | None = None  # 旁白音高,仅 edge_tts 生效,如 "+2Hz"
    voice_name: str | None = None  # 旁白音色(见 edge_tts_custom.CURATED_VOICES),仅 edge_tts 生效
    # ⑦ 成片规格
    quality_profile: str = "standard"
    subtitle_style: str = "default"  # default/bold_yellow/large_white/compact
    bilingual_language: str | None = None  # 双语字幕目标语种(如 "en")
    intro_clip: str | None = None  # 片头视频文件路径
    outro_clip: str | None = None  # 片尾视频文件路径
    # ⑧ 生产
    preset: str | None = None  # economy/balanced/fast(provider/quality 底,显式字段覆盖)
    video_provider: str | None = None  # None → auto 成本路由
    budget_usd: float | None = None
    auto_rework_rounds: int | None = None


@router.post("/plan")
async def director_plan(
    body: PlanRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """预览:剧情文本 → 意图 + 可行性 plan + 分镜 prompts + 可执行 canvas 图(不建任务)。"""
    result = await plan_from_text(
        text=body.text,
        num_shots=body.num_shots,
        character_reference=body.character_reference,
    )
    return {**result, "plan": asdict(result["plan"])}


async def _resolve_character_roster(pool: PgPool, subject_ids: list[str]) -> tuple[str | None, str]:
    """多角色绑定 → (首个 id 供 i2v 锁脸, 人设 roster 文本供 topic 注入)。

    "多身份锁定"的诚实边界:provider 的 i2v 每镜只吃 1 张参考图(omodul 硬限制),故仍只有
    首个角色的脸被跨镜锁定;其余角色仅以"姓名+描述"文本形式影响 storyboard LLM 的写作,
    不做画面身份锁定。
    """
    if not subject_ids:
        return None, ""
    svc = SubjectService(SubjectRepository(pool))
    parts: list[str] = []
    for sid in subject_ids:
        try:
            subj = await svc.get_subject(sid)
        except Exception:
            subj = None
        if subj:
            desc = subj.get("description") or ""
            parts.append(f"{subj.get('name', sid)}({desc})" if desc else subj.get("name", sid))
    return subject_ids[0], "、".join(parts)


@router.post("/episodes")
async def director_create_episode(
    body: EpisodeRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[TaskService, Depends(get_task_service)],
    pool: Annotated[PgPool, Depends(get_pg_pool)],
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """NL + 片表单 → 可行性门 → 建任务 → 后台出片。结构化字段逐条驱动 orchestrate。"""
    intent = await parse_intent(body.text)

    # 结构化字段优先于 LLM 猜的值。
    duration = body.duration_archetype or intent.get("duration_archetype", "1-5min")
    num_chars = (
        body.num_characters if body.num_characters is not None else intent.get("num_characters", 1)
    )

    roster_subject_id, characters_text = await _resolve_character_roster(
        pool, body.character_subject_ids
    )
    effective_subject_id = body.subject_id or roster_subject_id

    # 执行预设作 provider/quality 的底,显式字段覆盖。
    base_video, base_audio, base_quality = "auto", "vibevoice", body.quality_profile
    if body.preset and body.preset in EXECUTION_PRESETS:
        p = EXECUTION_PRESETS[body.preset]
        base_video, base_audio, base_quality = p.video_provider, p.audio_provider, p.quality_profile
    video_provider = body.video_provider or base_video
    audio_provider = body.audio_provider or base_audio
    quality_profile = body.quality_profile if body.quality_profile != "standard" else base_quality

    mode = "i2v" if effective_subject_id else "t2v"  # 绑了角色 → i2v 锁定
    try:
        plan = await produce(
            topic=intent["topic"],
            duration_archetype=duration,
            audio_provider=audio_provider,
            video_provider=video_provider,
            style=body.style_preset or intent.get("style", "cinematic"),
            num_characters=num_chars,
            budget_usd=body.budget_usd,
            mode=mode,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not plan.feasible:
        raise HTTPException(status_code=402, detail="; ".join(plan.notes) or "infeasible")

    # 结构化字段 → config_json → run_task 逐条透传进 orchestrate。
    kwargs: dict[str, Any] = {
        "num_characters": num_chars,
        "aspect_ratio": body.aspect_ratio,
        "quality_profile": quality_profile,
        "transition": body.transition,
        "per_shot_routing": body.per_shot_routing,
        "language": body.language,
        "subtitle_style": body.subtitle_style,
    }
    for k, v in (
        ("style_preset", body.style_preset),
        ("prompt_style", body.prompt_style),
        ("prompt_lighting", body.prompt_lighting),
        ("prompt_color_grade", body.prompt_color_grade),
        ("prompt_camera", body.prompt_camera),
        ("mood", body.mood),
        ("genre", body.genre),
        ("narrative_hook", body.narrative_hook),
        ("scene_notes", body.scene_notes),
        ("props", body.props),
        ("characters", characters_text or None),
        ("avatar_portrait", body.avatar_portrait),
        ("subject_id", effective_subject_id),
        ("bgm", body.bgm),
        ("sfx", body.sfx),
        ("voice_rate", body.voice_rate),
        ("voice_pitch", body.voice_pitch),
        ("voice_name", body.voice_name),
        ("bilingual_language", body.bilingual_language),
        ("intro_clip", body.intro_clip),
        ("outro_clip", body.outro_clip),
    ):
        if v:
            kwargs[k] = v
    if body.auto_rework_rounds is not None:
        kwargs["auto_rework_rounds"] = body.auto_rework_rounds

    try:
        task = await svc.create_task(
            topic=plan.topic,
            duration_archetype=duration,
            video_provider=plan.video_provider,
            audio_provider=audio_provider,
            user_id=str(user["id"]),
            **kwargs,
        )
    except CostLimitExceeded as e:
        raise HTTPException(status_code=402, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    sub = await svc.submit_task(task["id"])
    if sub.get("status") != "queued":
        background_tasks.add_task(svc.run_task_background, task["id"])
    return {
        "task_id": str(task["id"]),
        "status": sub.get("status", task.get("status")),
        "intent": intent,
        "plan": asdict(plan),
        "spec": {
            "duration_archetype": duration,
            "aspect_ratio": body.aspect_ratio,
            "quality_profile": quality_profile,
            "video_provider": plan.video_provider,
            "audio_provider": audio_provider,
            "num_characters": num_chars,
            "subject_locked": bool(effective_subject_id),
            "character_count": len(body.character_subject_ids)
            or (1 if effective_subject_id else 0),
            "avatar": bool(body.avatar_portrait),
        },
    }


class RenderRequest(BaseModel):
    """逐镜编辑回路:提交(编辑过的)canvas 分镜图 → 执行 + 装配成片。"""

    name: str = "导演分镜"
    topic: str = ""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    quality_profile: str = "standard"
    aspect_ratio: str = "9:16"
    transition: str = "fade"
    bgm: str | None = None
    sfx: str | None = None
    intro_clip: str | None = None
    outro_clip: str | None = None


@router.post("/render")
async def director_render(
    body: RenderRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[TaskService, Depends(get_task_service)],
    pool: Annotated[PgPool, Depends(get_pg_pool)],
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """逐镜编辑回路:存图 → 建任务 → 后台按用户改过的每镜出片 + 装配(不重跑 storyboard)。"""
    shot_nodes = [n for n in body.nodes if n.get("node_type") == "video"]
    if not shot_nodes:
        raise HTTPException(status_code=400, detail="图里没有 video 镜头节点")

    graph_svc = GraphService(GraphRepository(pool))
    graph = await graph_svc.save_graph(
        name=body.name,
        description="导演逐镜编辑",
        nodes=body.nodes,
        edges=body.edges,
        user_id=str(user["id"]),
    )
    graph_id = str(graph["id"])

    w, h = resolve_resolution(body.quality_profile, body.aspect_ratio)
    try:
        fps = get_quality_profile(body.quality_profile).fps
    except ValueError:
        fps = 24

    # 任务记录:逐镜编辑属本地装配,零云成本 → wan_local 走计费快路。
    try:
        task = await svc.create_task(
            topic=body.topic or body.name,
            duration_archetype="short",
            video_provider="wan_local",
            audio_provider="vibevoice",
            user_id=str(user["id"]),
            quality_profile=body.quality_profile,
            aspect_ratio=body.aspect_ratio,
        )
    except (CostLimitExceeded, ValueError) as e:
        raise HTTPException(status_code=402, detail=str(e)) from e

    background_tasks.add_task(
        render_graph_episode,
        graph_id=graph_id,
        task_id=task["id"],
        executor_service=ExecutorService(graph_svc),
        task_service=svc,
        width=w,
        height=h,
        fps=fps,
        transition=body.transition,
        bgm=body.bgm,
        sfx=body.sfx,
        intro_clip=body.intro_clip,
        outro_clip=body.outro_clip,
    )
    return {
        "task_id": str(task["id"]),
        "graph_id": graph_id,
        "status": "rendering",
        "shot_count": len(shot_nodes),
    }
