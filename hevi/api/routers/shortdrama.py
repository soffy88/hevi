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
from hevi.series.repository import SeriesRepository
from hevi.series.series_service import SeriesService
from hevi.storygraph.extract import extract_story_graph
from hevi.storygraph.schemas import StoryGraph
from hevi.subjects.repository import SubjectRepository
from hevi.subjects.subject_service import SubjectService
from hevi.tasks.repository import TaskRepository
from hevi.tasks.task_service import TaskService

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
    subject_id = str((updated or subject)["id"])
    rec["bindings"][char_id] = {"mode": "existing", "subject_id": subject_id}
    return {"char_id": char_id, "subject_id": subject_id}


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
        subject_id_map: dict[str, str] = {}
        for c in story.characters:
            pre = rec["bindings"].get(c.char_id)
            if pre is not None:
                subject_id_map[c.char_id] = pre["subject_id"]
                continue
            binding = body.bindings.get(c.char_id)
            if binding is not None and binding.mode == "existing" and binding.subject_id:
                subject_id_map[c.char_id] = binding.subject_id
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
            # 立即落进 rec["bindings"](同上传预绑定的存法)——这个角色的 Subject 已经
            # 真建好了,即便后面某个角色/dispatch_season 失败导致整体重试,也不会把
            # 这个已经成功的角色重新生成一遍参考图、建出一个重复 Subject。
            rec["bindings"][c.char_id] = {
                "mode": "existing",
                "subject_id": subject_id_map[c.char_id],
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
        # dispatch_season 只建 VideoTask 行(status="pending"),并不会触发真实生成——
        # 这是 2026-07-12 真实撞见的一个严重疏漏:云端 provider(happyhorse_1_1_maas_lock
        # 等)的任务不会被 QueueWorker 的串行队列捞走(那条队列走 status="queued",
        # 只有 submit_task() 对本地 provider 才会转过去),必须像
        # hevi/api/routers/series.py::create_episode 那样显式 submit_task()+
        # (非本地 provider 时)调 run_task_background 才会真的开始生成。此前这一步
        # 完全缺失,派发"成功"但视频永远停在 pending,不会有人去跑它。
        for ep in dispatched["episodes"]:
            ep_id = uuid.UUID(str(ep["id"]))
            submitted = await task_service.submit_task(ep_id)
            if submitted.get("status") != "queued" and not task_service.is_local_provider(
                body.video_provider
            ):
                t = asyncio.create_task(task_service.run_task_background(ep_id))
                _RUN_TASKS.add(t)
                t.add_done_callback(_RUN_TASKS.discard)

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
