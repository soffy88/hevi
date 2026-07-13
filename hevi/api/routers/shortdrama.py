"""短剧创建入口 API —— SPEC-001 §7 阶段1"补上的建季"能力。

  - POST /shortdrama/runs                                   手稿 → StoryGraph → SeasonPlan(后台异步跑)
  - GET  /shortdrama/runs / /shortdrama/runs/{run_id}        列出/查询 run 状态
  - POST /shortdrama/runs/{run_id}/replan                    对结果不满意 → 重新抽取+规划
  - POST /shortdrama/runs/{run_id}/characters/{char_id}/upload  上传角色参考图 → 建 Subject 并绑定
  - POST /shortdrama/runs/{run_id}/confirm                   角色绑定确认 → dispatch_season(真实派发)

run 状态存内存 map(同 hevi/api/routers/tongjian.py 的 P0 兜底),不建表。派发之后
dispatch_season 建的 VideoTask 会被 hevi/queue/worker.py 的后台队列自动捞走真实生成
(真花钱),所以 /confirm 强制要求非空的 series_budget_usd 以复用 B3 季预算熔断,且
duration_archetype 不接受 "short"(该档会让主线管线跳过一致性打分,见 scripts/g1_shortdrama_run.py
顶部注释)。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from obase.persistence import PgPool
from pydantic import BaseModel

from hevi.auth.dependencies import get_current_user
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.season_planner.dispatch import dispatch_season
from hevi.season_planner.planner import build_season_plan
from hevi.season_planner.schemas import EpisodePlan
from hevi.season_planner.tongjian_bridge import render_episode
from hevi.series.repository import SeriesRepository
from hevi.series.series_service import SeriesService
from hevi.storygraph.extract import extract_story_graph
from hevi.storygraph.schemas import StoryGraph
from hevi.subjects.repository import SubjectRepository
from hevi.subjects.subject_service import SubjectService
from hevi.tasks.repository import TaskRepository
from hevi.tasks.task_service import TaskService
from hevi.video.duration_mapper import get_duration_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shortdrama", tags=["shortdrama"])

_RUNS: dict[str, dict[str, Any]] = {}
# fire-and-forget 真实生成任务的强引用(asyncio 文档明确警告:create_task() 返回值
# 不留引用会被当垃圾提前回收/取消)。任务完成后从集合里移除,不无限增长。
_RUN_TASKS: set[asyncio.Task[Any]] = set()

_MAX_PLAN_ATTEMPTS = 5
_ART_DIRECTION = "cinematic character portrait, front facing, neutral expression, detailed"
_OUTPUT_DIR = Path("output/shortdrama")  # 模块级常量,便于测试 monkeypatch 到临时目录
_PORTRAIT_MAX_ATTEMPTS = 3  # qwen-image 偶发瞬时失败(含对方服务端 bug)重试次数
_PORTRAIT_RETRY_DELAY_S = 3.0


async def get_pg_pool() -> PgPool:
    return await get_hevi_pg_pool()


class RunRequest(BaseModel):
    source_name: str
    raw_text: str
    target_episodes: int = 3


class CharacterBinding(BaseModel):
    mode: str  # "auto"(自动生成参考图) | "existing"(复用已有角色)
    subject_id: str | None = None


class ConfirmRequest(BaseModel):
    bindings: dict[str, CharacterBinding] = {}
    video_provider: str = "happyhorse_1_1_maas_lock"
    duration_archetype: str = "1-5min"
    series_budget_usd: float = 20.0
    style_pack_id: str | None = None


# ── 内存 run 记录 ────────────────────────────────────────────────────────────


def _init_run(
    run_id: str, *, source_name: str, raw_text: str, target_episodes: int, user_id: str
) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "run_id": run_id,
        "user_id": user_id,
        "status": "PENDING",
        "source_name": source_name,
        "raw_text": raw_text,
        "target_episodes": target_episodes,
        "created_at": datetime.now(UTC),
        "story": None,
        "plan": None,
        "gate": None,
        "bindings": {},  # char_id -> {"mode": "existing", "subject_id": ...}(如上传参考图预绑定)
        "series_id": None,
        "error": None,
        "progress": None,  # 人类可读的当前步骤(如"建角色 2/3: 道士"),供前端展示进度
    }
    _RUNS[run_id] = rec
    return rec


def _require_run(run_id: str, user: dict[str, Any]) -> dict[str, Any]:
    rec = _RUNS.get(run_id)
    if not rec:
        raise HTTPException(status_code=404, detail="run 不存在")
    if rec.get("user_id") and rec["user_id"] != str(user["id"]):
        raise HTTPException(status_code=404, detail="run 不存在")
    return rec


# ── 后台任务:B0 抽取 + 剧集规划 ────────────────────────────────────────────


async def _plan_pipeline(run_id: str) -> None:
    """B0 抽取 StoryGraph + 剧集规划(best-of-N + 5 次重试),落到 AWAITING_CHARACTERS。

    即便 5 次重试后 G_SEASON 门仍未通过,也不中断——把 gate 结果原样返回给前端,
    前端展示警告并提供"重新规划"按钮,人工判断是否接受这版分集。
    """
    rec = _RUNS[run_id]
    rec["status"] = "RUNNING"
    try:
        story = await extract_story_graph(source_name=rec["source_name"], raw_text=rec["raw_text"])
        if not story.characters or not story.events:
            rec["status"] = "FAILED"
            rec["error"] = "StoryGraph 抽取结果为空(检查 qwen_cloud 是否可用/手稿是否可读)"
            return

        plan = gate = None
        for attempt in range(1, _MAX_PLAN_ATTEMPTS + 1):
            plan, gate = await build_season_plan(story, target_episodes=rec["target_episodes"])
            logger.info(
                "shortdrama run %s G_SEASON(第%d次尝试): passed=%s", run_id, attempt, gate.passed
            )
            if gate.passed:
                break

        rec["story"] = story
        rec["plan"] = plan
        rec["gate"] = gate
        rec["status"] = "AWAITING_CHARACTERS"
    except Exception as e:
        logger.exception("shortdrama run %s 规划失败: %s", run_id, e)
        rec["status"] = "FAILED"
        rec["error"] = str(e)[:500]


# ── 序列化 ───────────────────────────────────────────────────────────────────


def _story_summary(story: StoryGraph) -> dict[str, Any]:
    return {
        "characters": [
            {
                "char_id": c.char_id,
                "name": c.name,
                "aliases": c.aliases,
                "description": c.description,
                "role": c.role,
            }
            for c in story.characters
        ],
        "relationships": [
            {
                "from_char": r.from_char,
                "to_char": r.to_char,
                "relation_type": r.relation_type,
                "valence": r.valence,
            }
            for r in story.relationships
        ],
        "events": [
            {"event_id": e.event_id, "summary": e.summary, "beat_type": e.beat_type}
            for e in story.events
        ],
    }


def _plan_summary(plan: Any) -> dict[str, Any]:
    return {
        "target_episodes": plan.target_episodes,
        "episodes": [
            {
                "ep_number": ep.ep_number,
                "title": ep.title,
                "characters_present": ep.characters_present,
                "target_emotion_arc": ep.target_emotion_arc,
                "beats": ep.beats,
            }
            for ep in plan.episodes
        ],
    }


def _character_bindings(rec: dict[str, Any]) -> list[dict[str, Any]]:
    story: StoryGraph = rec["story"]
    bindings = rec.get("bindings") or {}
    out = []
    for c in story.characters:
        b = bindings.get(c.char_id)
        out.append(
            {
                "char_id": c.char_id,
                "name": c.name,
                "bound": b is not None,
                "subject_id": (b or {}).get("subject_id"),
            }
        )
    return out


def _rec_to_status(rec: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "run_id": rec["run_id"],
        "status": rec["status"],
        "source_name": rec["source_name"],
        "target_episodes": rec["target_episodes"],
        "created_at": rec["created_at"],
        "series_id": rec.get("series_id"),
        "error": rec.get("error"),
        "progress": rec.get("progress"),
    }
    if rec.get("story") is not None:
        out["story_graph"] = _story_summary(rec["story"])
        out["characters"] = _character_bindings(rec)
    if rec.get("plan") is not None:
        out["season_plan"] = _plan_summary(rec["plan"])
    if rec.get("gate") is not None:
        out["gate"] = {
            "passed": rec["gate"].passed,
            "errors": rec["gate"].errors,
            "warnings": rec["gate"].warnings,
        }
    return out


# ── API Endpoints ────────────────────────────────────────────────────────────


@router.post("/runs")
async def start_run(
    body: RunRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict[str, str]:
    """提交手稿,启动 B0 抽取 + 剧集规划(异步后台跑)。"""
    if not body.raw_text.strip():
        raise HTTPException(status_code=422, detail="raw_text 不能为空")
    if len(body.raw_text) > 50_000:
        raise HTTPException(status_code=422, detail="原文过长(上限 5 万字)")
    if not (1 <= body.target_episodes <= 50):
        raise HTTPException(status_code=422, detail="目标集数需在 1-50 之间")

    run_id = str(uuid.uuid4())
    _init_run(
        run_id,
        source_name=body.source_name,
        raw_text=body.raw_text,
        target_episodes=body.target_episodes,
        user_id=str(user["id"]),
    )
    background_tasks.add_task(_plan_pipeline, run_id)
    logger.info("shortdrama run %s started: %s", run_id, body.source_name)
    return {"run_id": run_id, "status": "PENDING"}


@router.get("/runs")
async def list_runs(user: Annotated[dict, Depends(get_current_user)]) -> list[dict[str, Any]]:
    mine = [r for r in _RUNS.values() if r.get("user_id") == str(user["id"])]
    return [_rec_to_status(r) for r in sorted(mine, key=lambda r: r["created_at"], reverse=True)]


@router.get("/runs/{run_id}")
async def get_run(run_id: str, user: Annotated[dict, Depends(get_current_user)]) -> dict[str, Any]:
    rec = _require_run(run_id, user)
    return _rec_to_status(rec)


@router.post("/runs/{run_id}/replan")
async def replan_run(
    run_id: str,
    background_tasks: BackgroundTasks,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict[str, str]:
    """对抽取/分集结果不满意 → 用同一份手稿重新跑一遍抽取+规划(丢弃旧结果)。"""
    rec = _require_run(run_id, user)
    if rec["status"] not in ("AWAITING_CHARACTERS", "FAILED"):
        raise HTTPException(status_code=409, detail=f"当前状态 {rec['status']} 不可重新规划")
    rec["status"] = "RUNNING"
    rec["story"] = None
    rec["plan"] = None
    rec["gate"] = None
    rec["bindings"] = {}
    rec["error"] = None
    background_tasks.add_task(_plan_pipeline, run_id)
    return {"run_id": run_id, "status": "RUNNING"}


@router.post("/runs/{run_id}/characters/{char_id}/upload", status_code=201)
async def upload_character_reference(
    run_id: str,
    char_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    pool: Annotated[PgPool, Depends(get_pg_pool)],
    file: Annotated[UploadFile, File(description="角色参考图")],
) -> dict[str, Any]:
    """上传一张照片给某个角色建 Subject 并绑定(confirm 时该角色不再自动生成参考图)。"""
    rec = _require_run(run_id, user)
    if rec.get("story") is None:
        raise HTTPException(status_code=409, detail="StoryGraph 尚未就绪")
    story: StoryGraph = rec["story"]
    char = next((c for c in story.characters if c.char_id == char_id), None)
    if char is None:
        raise HTTPException(status_code=404, detail="角色不存在")

    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=422, detail="只接受图片文件")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="空文件")

    svc = SubjectService(SubjectRepository(pool))
    subject = await svc.create_subject(
        kind="character", name=char.name, description=char.description, user_id=str(user["id"])
    )
    updated = await svc.add_reference_upload(
        str(subject["id"]), filename=file.filename or "photo.jpg", data=data
    )
    final = updated or subject
    subject_id = str(final["id"])
    refs = final.get("reference_images") or []
    rec["bindings"][char_id] = {
        "mode": "existing",
        "subject_id": subject_id,
        "ref_image": refs[0] if refs else None,
    }
    return {"char_id": char_id, "subject_id": subject_id}


async def _generate_subject3d_background(subject_id: str, char_id: str, run_id: str) -> None:
    """派发后台建 Subject3D(见调用点注释)。独立 pool 连接——这是脱离请求生命周期的
    fire-and-forget 任务,不能借用某个已随请求结束而关闭的连接。"""
    try:
        pool = await get_hevi_pg_pool()
        subject_svc = SubjectService(SubjectRepository(pool))
        await subject_svc.generate_subject3d(subject_id)
        logger.info("shortdrama run %s 角色 %s Subject3D 生成完成", run_id, char_id)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "shortdrama run %s 角色 %s Subject3D 生成失败(降级为纯2D,不影响出片): %s",
            run_id,
            char_id,
            e,
        )


async def _run_episode_via_tongjian(
    *,
    task_repo: TaskRepository,
    task_id: uuid.UUID,
    ep: EpisodePlan,
    story: StoryGraph,
    duration_archetype: str,
    subject_ref_paths: dict[str, str],
    subject_id_map: dict[str, str],
) -> None:
    """真实生成一集:StoryGraph/EpisodePlan → hevi.season_planner.tongjian_bridge
    (复用通鉴 cloud_avatar 对白+口型管线,见该模块 docstring)。

    不走 task_service.run_task()——那条路是 dispatch_season 建好 VideoTask 后"该由谁
    去跑"的默认答案,但它接的是通用长视频管线(无对白能力,2026-07-12 真实验证效果
    远不如通鉴)。这里直接更新 video_tasks/shot_states,让 SeasonBoard 现有 UI
    (taskApi.videoUrl/shots)零改动继续可用。
    """
    await task_repo.update_task(
        task_id, {"status": "running", "updated_at": datetime.now(UTC).replace(tzinfo=None)}
    )
    try:
        duration_cfg = get_duration_config(duration_archetype)
        # 每集渲染前现查一遍 Subject3D 是否就绪(而不是沿用 confirm 时刻的快照)——
        # 本地 TripoSR 生成要约3分钟(CPU,见 subject3d_local.py),confirm→dispatch
        # 通常几秒内就完成,大概率赶不上第一集;后面几集渲染时如果已经生成完,
        # 这里能捡到,不需要重新触发生成(character_bible_for_episode 2D 优先于3D,
        # 拿不到也不影响出片,只是拿不到"机位驱动渲染"的补充数据)。
        subject3d_views: dict[str, dict[str, str]] = {}
        if subject_id_map:
            pool = await get_hevi_pg_pool()
            subject_svc = SubjectService(SubjectRepository(pool))
            for char_id, subj_id in subject_id_map.items():
                try:
                    subj = await subject_svc.get_subject(subj_id)
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "shortdrama episode %s 角色 %s 查询 Subject3D 失败(降级为纯2D): %s",
                        task_id,
                        char_id,
                        e,
                    )
                    continue
                views = ((subj or {}).get("metadata") or {}).get("subject3d", {}).get("views")
                if views:
                    subject3d_views[char_id] = views

        result = await render_episode(
            ep,
            story,
            run_dir=Path("output/tasks") / str(task_id),
            target_duration_sec=int(duration_cfg["target_s"]),
            subject_ref_paths=subject_ref_paths,
            subject3d_views=subject3d_views,
        )
        final_video = result["final_video"]
        shots = result["shots"]
        task = await task_repo.get_task(task_id)
        config_json = dict((task or {}).get("config_json") or {})
        # actual_usd 严格来说应该是真实计费,但 task_service 自己也从不回填这个字段
        # (STATUS.md 早前记过的既有坑)——退而求其次,沿用派发时算好的预估值,让
        # B3 季预算熔断至少看得到"这一集大概花了多少",而不是永远读到 $0。
        config_json["actual_usd"] = config_json.get("estimated_usd", 0.0)
        await task_repo.update_task(
            task_id,
            {
                "status": "completed",
                "progress_pct": 100.0,
                "result_video_path": final_video.video_path,
                "total_shots": len(shots),
                "completed_shots": len(shots),
                "error": None,
                "config_json": config_json,
                "updated_at": datetime.now(UTC).replace(tzinfo=None),
            },
        )
        await task_repo.delete_shots(task_id)
        for shot in shots:
            await task_repo.create_shot_state(
                {
                    "task_id": task_id,
                    "shot_index": shot["index"],
                    "status": "completed" if shot["passed"] else "failed",
                    "output_path": shot["path"],
                    "selection_json": {
                        "provider": shot["provider"],
                        "consistency_score": shot["consistency_score"],
                        "passed": shot["passed"],
                        "diagnosis_category": shot["diagnosis_category"],
                        "retry_count": shot["retry_count"],
                    },
                }
            )
        logger.info("shortdrama episode %s 渲染完成(通鉴桥接): %s", task_id, final_video.video_path)
    except Exception as e:
        logger.exception("shortdrama episode %s 渲染失败(通鉴桥接): %s", task_id, e)
        await task_repo.update_task(
            task_id,
            {
                "status": "failed",
                "error": str(e)[:500],
                "updated_at": datetime.now(UTC).replace(tzinfo=None),
            },
        )


async def _confirm_pipeline(run_id: str, body: ConfirmRequest, user_id: str) -> None:
    """角色绑定确认后:补齐未绑定角色的 Subject(auto 生成参考图)→ dispatch_season。"""
    rec = _RUNS[run_id]
    try:
        story: StoryGraph = rec["story"]
        plan = rec["plan"]
        pool = await get_hevi_pg_pool()
        subject_svc = SubjectService(SubjectRepository(pool))

        auto_chars = [
            c
            for c in story.characters
            if rec["bindings"].get(c.char_id) is None
            and not (
                (b := body.bindings.get(c.char_id)) is not None
                and b.mode == "existing"
                and b.subject_id
            )
        ]
        # char_id → 该角色参考图路径(reference_images[0],"设封面"约定里下游锁脸统一
        # 读的那张)。2026-07-12 补:建号阶段真的会存参考图,但通鉴 cloud_avatar 渲染
        # 路径(见下面 _run_episode_via_tongjian/render_episode)此前完全没读过这个
        # 字段——canonical 像是从文字描述现场重新生成的,身份参考图建了却没人用。
        subject_ref_paths: dict[str, str] = {}
        subject_id_map: dict[str, str] = {}
        for c in story.characters:
            pre = rec["bindings"].get(c.char_id)
            if pre is not None:
                subject_id_map[c.char_id] = pre["subject_id"]
                if pre.get("ref_image"):
                    subject_ref_paths[c.char_id] = pre["ref_image"]
                continue
            binding = body.bindings.get(c.char_id)
            if binding is not None and binding.mode == "existing" and binding.subject_id:
                subject_id_map[c.char_id] = binding.subject_id
                # 选的是这次 run 之外已存在的 Subject,本地没有它的数据,唯一需要一次
                # 真实 get_subject 的分支(其余两种情况——上传预绑定/本 run 内 auto 建号
                # ——参考图路径在各自建号的地方就已经拿到手,不用回查数据库)。参考图
                # 本身是"增强,非必需"(同 subject_embed.py 的既有设计意图)——查不到就
                # 退回原来的文字描述生成,不能因为一个角色的查询失败拖垮整条派发。
                try:
                    existing_subj = await subject_svc.get_subject(binding.subject_id)
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "shortdrama run %s 角色 %s 查询已存在 Subject %s 参考图失败: %s",
                        run_id,
                        c.name,
                        binding.subject_id,
                        e,
                    )
                    existing_subj = None
                existing_refs = (existing_subj or {}).get("reference_images") or []
                if existing_refs:
                    subject_ref_paths[c.char_id] = existing_refs[0]
                continue

            idx = auto_chars.index(c) + 1
            rec["progress"] = f"建角色参考图 {idx}/{len(auto_chars)}: {c.name}"

            from hevi.image.qwen_image_service import qwen_image_generate

            portrait_dir = _OUTPUT_DIR / run_id / "subjects" / c.char_id
            portrait_dir.mkdir(parents=True, exist_ok=True)
            portrait_path = portrait_dir / "portrait.png"
            prompt = f"{_ART_DIRECTION}, {c.name}, {c.description or '角色肖像'}"
            # 阿里云 qwen-image 偶发算法侧内部错误(2026-07-12 真实撞见:'DashscopeLogger'
            # object has no attribute 'warning',对方服务端 bug),单次瞬时失败不该
            # 拖垮整条派发——重试几次,仍失败才真的放弃这个角色。
            last_exc: Exception | None = None
            for attempt in range(1, _PORTRAIT_MAX_ATTEMPTS + 1):
                try:
                    await qwen_image_generate(prompt=prompt, output_path=portrait_path)
                    last_exc = None
                    break
                except Exception as e:  # noqa: BLE001
                    last_exc = e
                    logger.warning(
                        "shortdrama run %s 角色 %s 参考图第%d次失败: %s", run_id, c.name, attempt, e
                    )
                    if attempt < _PORTRAIT_MAX_ATTEMPTS:
                        await asyncio.sleep(_PORTRAIT_RETRY_DELAY_S)
            if last_exc is not None:
                raise last_exc

            subject = await subject_svc.create_subject(
                kind="character",
                name=c.name,
                description=c.description,
                reference_images=[str(portrait_path)],
                user_id=user_id,
            )
            subject_id_map[c.char_id] = str(subject["id"])
            subject_ref_paths[c.char_id] = str(portrait_path)
            # 立即落进 rec["bindings"](同上传预绑定的存法)——这个角色的 Subject 已经
            # 真建好了,即便后面某个角色/dispatch_season 失败导致整体重试,也不会把
            # 这个已经成功的角色重新生成一遍参考图、建出一个重复 Subject。
            rec["bindings"][c.char_id] = {
                "mode": "existing",
                "subject_id": subject_id_map[c.char_id],
                "ref_image": str(portrait_path),
            }

        rec["progress"] = "派发剧集(建 Series + 逐集任务)..."
        task_repo = TaskRepository(pool)
        task_service = TaskService(task_repo)
        series_service = SeriesService(SeriesRepository(pool), task_service=task_service)

        spec: dict[str, Any] = {
            "video_provider": body.video_provider,
            "duration_archetype": body.duration_archetype,
            "budget_usd": body.series_budget_usd,
        }
        dispatched = await dispatch_season(
            plan,
            story,
            series_service=series_service,
            task_service=task_service,
            subject_id_map=subject_id_map,
            style_pack_id=body.style_pack_id,
            spec=spec,
            user_id=user_id,
        )
        # dispatch_season 只建 VideoTask 行(status="pending"),不会自己触发真实生成
        # ——2026-07-12 真实撞见的严重疏漏,已修(见下面 _run_episode_via_tongjian 的
        # docstring)。同时,真实跑出来的效果比通鉴差远了:通用长视频管线
        # (hevi/pipeline/longvideo_orchestrator.py)没有"对白 vs 旁白"的区分能力,
        # 产出的是纯第三人称诗化旁白、零人物对话——所以这里改用
        # hevi/season_planner/tongjian_bridge.py,复用通鉴已验证的 L2(戏剧化剧本)→
        # L3(配音)→L4(分镜)→L6(cloud_avatar 角色对白+口型)→L8(装配) 管线,不再走
        # task_service.run_task/orchestrate_longvideo 那条通用管线。
        for idx, ep_dict in enumerate(dispatched["episodes"]):
            ep_id = uuid.UUID(str(ep_dict["id"]))
            episode_plan = plan.episodes[idx]
            t = asyncio.create_task(
                _run_episode_via_tongjian(
                    task_repo=task_repo,
                    task_id=ep_id,
                    ep=episode_plan,
                    story=story,
                    duration_archetype=body.duration_archetype,
                    subject_ref_paths=subject_ref_paths,
                    subject_id_map=subject_id_map,
                )
            )
            _RUN_TASKS.add(t)
            t.add_done_callback(_RUN_TASKS.discard)

        # Subject3D 后台补建(HEVI-ARCHITECTURE.md v3.0 §5.7,2026-07-13 探路落地)——
        # 本地 TripoSR 推理约3分钟/角色(CPU,GPU 被同机其他租户占满,见
        # subject3d_local.py),不能同步阻塞派发。fire-and-forget:失败只记日志,
        # 不影响本集出片(_run_episode_via_tongjian 拿不到 3D 数据会自动退回 2D
        # 参考图,这是已验证工作正常的既有路径)。赶不上第一集就等下一集捡漏。
        for char_id, subj_id in subject_id_map.items():
            t3d = asyncio.create_task(_generate_subject3d_background(subj_id, char_id, run_id))
            _RUN_TASKS.add(t3d)
            t3d.add_done_callback(_RUN_TASKS.discard)

        rec["series_id"] = dispatched["series_id"]
        rec["status"] = "DISPATCHED"
        rec["progress"] = None
        logger.info("shortdrama run %s 派发完成: series_id=%s", run_id, dispatched["series_id"])
    except Exception as e:
        logger.exception("shortdrama run %s 派发失败: %s", run_id, e)
        rec["status"] = "FAILED"
        rec["error"] = str(e)[:500]


@router.post("/runs/{run_id}/confirm")
async def confirm_run(
    run_id: str,
    body: ConfirmRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict[str, str]:
    """角色绑定确认 → 派发(建 Series + 逐集 VideoTask,由后台队列真实生成)。

    也允许在 status=="FAILED" 时重新调用(前提 story/plan 仍在)——上一次派发若是卡在
    建角色参考图/dispatch_season 这一步失败(而非规划阶段失败,规划失败时 story/plan
    本就是 None,下面这行会挡住),不该逼用户从头"重新规划"、白白丢掉已经生成好、
    没问题的 StoryGraph/SeasonPlan。已成功建号的角色见 rec["bindings"] 增量落地,
    重试不会重新生成已经建好的角色。
    """
    rec = _require_run(run_id, user)
    if rec["status"] not in ("AWAITING_CHARACTERS", "FAILED"):
        raise HTTPException(status_code=409, detail=f"当前状态 {rec['status']} 不可确认派发")
    if rec.get("story") is None or rec.get("plan") is None:
        raise HTTPException(status_code=409, detail="StoryGraph/SeasonPlan 尚未就绪")
    if body.duration_archetype == "short":
        raise HTTPException(
            status_code=422,
            detail='duration_archetype 不接受 "short"(该档会跳过身份一致性打分)',
        )
    if body.series_budget_usd <= 0:
        raise HTTPException(status_code=422, detail="series_budget_usd 必须为正数")

    rec["status"] = "DISPATCHING"
    rec["error"] = None
    background_tasks.add_task(_confirm_pipeline, run_id, body, str(user["id"]))
    return {"run_id": run_id, "status": "DISPATCHING"}
