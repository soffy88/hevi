"""SPEC-003 主线导演流水线 API —— 立意→剧本→设计清单→分镜,逐级人审核锁定才放行下游。

  - POST /director-pipeline/works                          素材 → 建 work + 生成①立意草稿
  - GET  /director-pipeline/works / /works/{id}             列出/查询 work 全量状态
  - POST /works/{id}/concept | /screenplay | /design-list | /shot-list
                                                             重新生成本级草稿(未锁定可反复调;
                                                             已锁定再调 = 回退该级 + 清空全部下游)
  - POST /works/{id}/concept/lock(及对应 screenplay/design-list/shot-list/lock)
                                                             存入(可能已编辑的)内容 → 锁定 →
                                                             自动生成下一级草稿
  - POST /works/{id}/produce                                仅 shotlist_locked 才允许,建真实
                                                             video_task 出片(现有 L1,不改)

跟现有 `director.py::director_create_episode`(一句话直接产集)并行存在,不替换——
SPEC-003 §7 说旧路径该废弃,但那是较大 UX 变更,本次先新增不删旧,详见
docs/specs/SPEC-003-mainline-director-pipeline.md 的实施取舍记录。

work 状态存内存 map(同 tongjian/shortdrama 的既有 P0 兜底,不建表——`video_tasks` 只在
`/produce` 真正建生成任务时才创建那一行)。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from obase.persistence import PgPool
from pydantic import BaseModel

from hevi.auth.dependencies import get_current_user
from hevi.cost.circuit_breaker import CostLimitExceeded
from hevi.credits.account_service import AccountService
from hevi.credits.billing_service import BillingService, InsufficientCredits
from hevi.credits.repository import CreditRepository
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.director.concept import generate_concept_draft
from hevi.director.design_list import generate_design_list_draft
from hevi.director.pipeline_schemas import (
    Concept,
    DesignCharacter,
    DesignList,
    Screenplay,
    ShotList,
)
from hevi.director.screenplay import generate_screenplay_draft
from hevi.director.shot_list import generate_shot_list_draft
from hevi.director.tongjian_render import render_director_episode
from hevi.subjects.repository import SubjectRepository
from hevi.subjects.subject_service import SubjectService
from hevi.tasks.repository import TaskRepository
from hevi.tasks.task_service import TaskService
from hevi.video.duration_mapper import get_duration_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/director-pipeline", tags=["director-pipeline"])

_WORKS: dict[str, dict[str, Any]] = {}
_OUTPUT_DIR = Path("output/director_pipeline")
_ART_DIRECTION = "cinematic character portrait, front facing, neutral expression, detailed"
_PORTRAIT_MAX_ATTEMPTS = 3

# ①→②→③→④,每级有 _draft/_locked 两态。
_STAGES = ("concept", "screenplay", "design_list", "shot_list")
_STAGE_KEY = {  # 内存记录里存内容用的 key(跟 URL path 段独立,path 用连字符,dict 用下划线)
    "concept": "concept",
    "screenplay": "screenplay",
    "design_list": "design_list",
    "shot_list": "shot_list",
}


async def get_pg_pool() -> PgPool:
    return await get_hevi_pg_pool()


async def get_task_service(pool: Annotated[PgPool, Depends(get_pg_pool)]) -> TaskService:
    return TaskService(TaskRepository(pool), BillingService(AccountService(CreditRepository(pool))))


async def get_subject_service(pool: Annotated[PgPool, Depends(get_pg_pool)]) -> SubjectService:
    return SubjectService(SubjectRepository(pool))


class CreateWorkRequest(BaseModel):
    material_text: str
    intent_hint: str = ""


def _init_work(
    work_id: str, *, material_text: str, intent_hint: str, user_id: str
) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "work_id": work_id,
        "user_id": user_id,
        "status": "concept_draft",
        # locked_through:已锁定到第几级(-1 = 一级都没锁,0 = concept 锁了,1 = screenplay
        # 锁了,以此类推)。状态机的真正判据,status 字符串只是给前端展示用的镜像——
        # 不从 status 字符串反解析阶段(那条路径此前有真实 bug:designlist/shotlist 的
        # status 拼写跟 _STAGES 的 design_list/shot_list 对不上,parse 会直接 ValueError)。
        "locked_through": -1,
        "material_text": material_text,
        "intent_hint": intent_hint,
        "created_at": datetime.now(UTC),
        "concept": None,
        "screenplay": None,
        "design_list": None,
        "shot_list": None,
        "video_task_id": None,
        "error": None,
    }
    _WORKS[work_id] = rec
    return rec


def _require_work(work_id: str, user: dict[str, Any]) -> dict[str, Any]:
    rec = _WORKS.get(work_id)
    if not rec:
        raise HTTPException(status_code=404, detail="work 不存在")
    if rec.get("user_id") and rec["user_id"] != str(user["id"]):
        raise HTTPException(status_code=404, detail="work 不存在")
    return rec


def _stage_index(stage: str) -> int:
    return _STAGES.index(stage)


def _require_stage_ready(rec: dict[str, Any], stage: str) -> None:
    """要重新生成/锁定这一级,前一级必须已锁定过(①立意没有前置)。"""
    idx = _stage_index(stage)
    if idx > 0 and rec["locked_through"] < idx - 1:
        raise HTTPException(status_code=409, detail=f"{_STAGES[idx - 1]} 还没锁定,不能操作 {stage}")


def _rollback_downstream(rec: dict[str, Any], from_stage: str) -> None:
    """退回上游 = 下游全部失效重来(SPEC-003 §4)。清空 from_stage 及其后所有级的内容,
    并把 locked_through 拉回到 from_stage 之前(from_stage 本身重新变回未锁定)。"""
    idx = _stage_index(from_stage)
    for stage in _STAGES[idx:]:
        rec[_STAGE_KEY[stage]] = None
    rec["locked_through"] = min(rec["locked_through"], idx - 1)
    rec["video_task_id"] = None


def _resolve_llm() -> Any:
    from obase.provider_registry import ProviderRegistry

    try:
        return ProviderRegistry.get().llm("qwen_cloud")
    except Exception:
        return ProviderRegistry.get().llm("default")


def _work_status(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        "work_id": rec["work_id"],
        "status": rec["status"],
        "locked_through": rec["locked_through"],
        "material_text": rec["material_text"],
        "created_at": rec["created_at"],
        "concept": rec["concept"],
        "screenplay": rec["screenplay"],
        "design_list": rec["design_list"],
        "shot_list": rec["shot_list"],
        "video_task_id": rec["video_task_id"],
        "error": rec["error"],
    }


# ── work 创建 + 查询 ─────────────────────────────────────────────────────────


@router.post("/works")
async def create_work(
    body: CreateWorkRequest, user: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    if not body.material_text.strip():
        raise HTTPException(status_code=422, detail="material_text 不能为空")
    work_id = str(uuid.uuid4())
    rec = _init_work(
        work_id,
        material_text=body.material_text,
        intent_hint=body.intent_hint,
        user_id=str(user["id"]),
    )
    concept = await generate_concept_draft(
        material_text=body.material_text, intent_hint=body.intent_hint, llm=_resolve_llm()
    )
    rec["concept"] = concept.model_dump()
    return _work_status(rec)


@router.get("/works")
async def list_works(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> list[dict[str, Any]]:
    mine = [r for r in _WORKS.values() if r.get("user_id") == str(user["id"])]
    return [_work_status(r) for r in sorted(mine, key=lambda r: r["created_at"], reverse=True)]


@router.get("/works/{work_id}")
async def get_work(
    work_id: str, user: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    return _work_status(_require_work(work_id, user))


# ── ①立意 ─────────────────────────────────────────────────────────────────


@router.post("/works/{work_id}/concept")
async def regenerate_concept(
    work_id: str, user: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    rec = _require_work(work_id, user)
    _rollback_downstream(rec, "concept")
    concept = await generate_concept_draft(
        material_text=rec["material_text"], intent_hint=rec["intent_hint"], llm=_resolve_llm()
    )
    rec["concept"] = concept.model_dump()
    rec["status"] = "concept_draft"
    return _work_status(rec)


@router.post("/works/{work_id}/concept/lock")
async def lock_concept(
    work_id: str, body: Concept, user: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    rec = _require_work(work_id, user)
    rec["concept"] = body.model_dump()
    rec["locked_through"] = _stage_index("concept")
    screenplay = await generate_screenplay_draft(
        concept=body, material_text=rec["material_text"], llm=_resolve_llm()
    )
    rec["screenplay"] = screenplay.model_dump()
    rec["status"] = "screenplay_draft"
    return _work_status(rec)


# ── ②剧本 ─────────────────────────────────────────────────────────────────


@router.post("/works/{work_id}/screenplay")
async def regenerate_screenplay(
    work_id: str, user: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    rec = _require_work(work_id, user)
    _require_stage_ready(rec, "screenplay")
    _rollback_downstream(rec, "screenplay")
    concept = Concept.model_validate(rec["concept"])
    screenplay = await generate_screenplay_draft(
        concept=concept, material_text=rec["material_text"], llm=_resolve_llm()
    )
    rec["screenplay"] = screenplay.model_dump()
    rec["status"] = "screenplay_draft"
    return _work_status(rec)


@router.post("/works/{work_id}/screenplay/lock")
async def lock_screenplay(
    work_id: str, body: Screenplay, user: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    rec = _require_work(work_id, user)
    rec["screenplay"] = body.model_dump()
    rec["locked_through"] = _stage_index("screenplay")
    design_list = await generate_design_list_draft(screenplay=body, llm=_resolve_llm())
    rec["design_list"] = design_list.model_dump()
    rec["status"] = "design_list_draft"
    return _work_status(rec)


# ── ③设计清单 ─────────────────────────────────────────────────────────────


@router.post("/works/{work_id}/design-list")
async def regenerate_design_list(
    work_id: str, user: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    rec = _require_work(work_id, user)
    _require_stage_ready(rec, "design_list")
    _rollback_downstream(rec, "design_list")
    screenplay = Screenplay.model_validate(rec["screenplay"])
    design_list = await generate_design_list_draft(screenplay=screenplay, llm=_resolve_llm())
    rec["design_list"] = design_list.model_dump()
    rec["status"] = "design_list_draft"
    return _work_status(rec)


async def _lock_design_list_assets(
    design_list: DesignList, *, user_id: str, work_id: str, subject_svc: SubjectService
) -> DesignList:
    """③锁定的核心动作:清单里每个还没建过 Subject 的角色/场景/道具,建成真实资产
    (character/scene/prop 三种 kind,复用既有 SubjectService,不建新表)。已有 subject_id
    的项(比如回退后重锁,或人工在草稿里就填了已有 subject_id)原样跳过,不重复建号。
    各资产的参考图生成互不依赖,并发发起——这一步顺序调用曾在线上把整个锁定请求拖到
    反向代理超时(Cloudflare 524),角色一多就必现。但完全不限流并发又会把 qwen-image
    提交接口打出 429(实测线上角色一多就触发,429 是原始 httpx.HTTPStatusError,不是
    QwenImageError,不受下面的重试保护,会直接把整个请求炸成 500)——用信号量把真实
    并发压到 2,并把 429/5xx 也纳入重试范围。"""
    portrait_dir = _OUTPUT_DIR / work_id / "design_assets"
    portrait_dir.mkdir(parents=True, exist_ok=True)
    _concurrency = asyncio.Semaphore(2)

    async def _ensure_subject(*, kind: str, name: str, description: str, slug: str) -> str | None:
        import httpx

        from hevi.image.qwen_image_service import QwenImageError, qwen_image_generate

        # 复用已有同名资产(2026-07-14):此前每次锁定都重建,角色库里同一个角色堆几十份
        # (豫让 ×12…),还每次重新花钱生成参考图。先查同名(同 kind、同 user)未删除的
        # 最新一版,有就直接复用其 subject_id,不重建、不再生成参考图。
        try:
            existing = await subject_svc.search_subjects(kind=kind, query=name, user_id=user_id)
            match = next((s for s in existing if (s.get("name") or "") == name), None)
            if match:
                logger.info("design-list 资产 %s 复用已有 Subject %s", name, match["id"])
                return str(match["id"])
        except Exception as e:
            logger.warning("design-list 资产 %s 查重失败,退回新建: %s", name, e)

        portrait_path = portrait_dir / f"{slug}.png"
        prompt = f"{_ART_DIRECTION}, {name}, {description or kind}"
        last_exc: Exception | None = None
        for attempt in range(1, _PORTRAIT_MAX_ATTEMPTS + 1):
            try:
                async with _concurrency:
                    await qwen_image_generate(prompt=prompt, output_path=portrait_path)
                last_exc = None
                break
            except (QwenImageError, httpx.HTTPStatusError) as e:
                last_exc = e
                logger.warning("design-list 资产 %s 参考图第%d次失败: %s", name, attempt, e)
                if attempt < _PORTRAIT_MAX_ATTEMPTS:
                    await asyncio.sleep(2.0 * attempt)
        if last_exc is not None:
            logger.warning("design-list 资产 %s 参考图最终失败,跳过建号: %s", name, last_exc)
            return None
        subject = await subject_svc.create_subject(
            kind=kind,
            name=name,
            description=description,
            reference_images=[str(portrait_path)],
            user_id=user_id,
        )
        return str(subject["id"])

    async def _assign(item: Any, *, kind: str, name: str, description: str, slug: str) -> None:
        if item.subject_id:
            return
        item.subject_id = await _ensure_subject(
            kind=kind, name=name, description=description, slug=slug
        )

    tasks = [
        _assign(
            c,
            kind="character",
            name=c.name,
            description=f"{c.appearance} {c.wardrobe} {c.hairstyle}".strip(),
            slug=f"char_{c.name}",
        )
        for c in design_list.characters
    ]
    tasks += [
        _assign(
            s,
            kind="scene",
            name=s.name,
            description=f"{s.environment} {s.mood}".strip(),
            slug=f"scene_{s.name}",
        )
        for s in design_list.scenes
    ]
    tasks += [
        _assign(p, kind="product", name=p.name, description=p.appearance, slug=f"prop_{p.name}")
        for p in design_list.props
    ]
    if tasks:
        await asyncio.gather(*tasks)
    return design_list


def _seed_design_list_subject_ids(body: DesignList, prior: dict[str, Any] | None) -> None:
    """重试幂等:上一次锁定(哪怕因某个资产建号失败而整体报错)已经建好的 Subject,
    按 name 对上就直接复用,不再重复调 qwen_image_generate 重建——避免每次点"重试"都
    把角色/场景参考图真实生成一遍、重复花钱。"""
    if not prior:
        return
    for key in ("characters", "scenes", "props"):
        prior_by_name = {item.get("name"): item.get("subject_id") for item in prior.get(key, [])}
        for item in getattr(body, key):
            if not item.subject_id and prior_by_name.get(item.name):
                item.subject_id = prior_by_name[item.name]


async def _run_design_list_lock(
    work_id: str, body: DesignList, *, user_id: str, subject_svc: SubjectService
) -> None:
    """③锁定的真正重活(N 个资产建号 + ④分镜逐场 LLM 生成)——角色/场次一多,就算每个
    调用本身都做了并发/超时收敛,总和还是可能顶到反向代理超时(线上已经实测 524/挂起
    好几轮)。放到 background task 里跑,HTTP 响应不再等它,前端轮询 GET /works/{id}
    直到状态变化即可,彻底摆脱"一个请求扛所有重活"这类超时。"""
    rec = _WORKS.get(work_id)
    if rec is None:
        return
    try:
        locked = await _lock_design_list_assets(
            body, user_id=user_id, work_id=work_id, subject_svc=subject_svc
        )
        rec["design_list"] = locked.model_dump()
        rec["locked_through"] = _stage_index("design_list")
        screenplay = Screenplay.model_validate(rec["screenplay"])
        shot_list = await generate_shot_list_draft(
            screenplay=screenplay, design_list=locked, llm=_resolve_llm()
        )
        rec["shot_list"] = shot_list.model_dump()
        rec["status"] = "shot_list_draft"
    except Exception as e:
        logger.exception("design-list 后台锁定失败: work_id=%s", work_id)
        rec["design_list"] = body.model_dump()
        rec["status"] = "design_list_lock_failed"
        rec["error"] = str(e)


@router.post("/works/{work_id}/design-list/lock")
async def lock_design_list(
    work_id: str,
    body: DesignList,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    subject_svc: Annotated[SubjectService, Depends(get_subject_service)],
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    rec = _require_work(work_id, user)
    _seed_design_list_subject_ids(body, rec.get("design_list"))
    rec["design_list"] = body.model_dump()
    rec["status"] = "design_list_locking"
    rec["error"] = None
    background_tasks.add_task(
        _run_design_list_lock, work_id, body, user_id=str(user["id"]), subject_svc=subject_svc
    )
    return _work_status(rec)


# ── ④分镜头剧本 ────────────────────────────────────────────────────────────


async def _run_shot_list_regenerate(work_id: str) -> None:
    """同 _run_design_list_lock:逐场 LLM 生成放后台跑,场次一多不顶到反向代理超时。"""
    rec = _WORKS.get(work_id)
    if rec is None:
        return
    try:
        screenplay = Screenplay.model_validate(rec["screenplay"])
        design_list = DesignList.model_validate(rec["design_list"])
        shot_list = await generate_shot_list_draft(
            screenplay=screenplay, design_list=design_list, llm=_resolve_llm()
        )
        rec["shot_list"] = shot_list.model_dump()
        rec["status"] = "shot_list_draft"
    except Exception as e:
        logger.exception("shot-list 后台重新生成失败: work_id=%s", work_id)
        rec["status"] = "shot_list_regenerate_failed"
        rec["error"] = str(e)


@router.post("/works/{work_id}/shot-list")
async def regenerate_shot_list(
    work_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    rec = _require_work(work_id, user)
    _require_stage_ready(rec, "shot_list")
    _rollback_downstream(rec, "shot_list")
    rec["status"] = "shot_list_generating"
    rec["error"] = None
    background_tasks.add_task(_run_shot_list_regenerate, work_id)
    return _work_status(rec)


@router.post("/works/{work_id}/shot-list/lock")
async def lock_shot_list(
    work_id: str, body: ShotList, user: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    rec = _require_work(work_id, user)
    rec["shot_list"] = body.model_dump()
    rec["locked_through"] = _stage_index("shot_list")
    rec["status"] = "shot_list_locked"
    return _work_status(rec)


# ── ⑤产集(现有 L1,不改)────────────────────────────────────────────────────


class ProduceRequest(BaseModel):
    video_provider: str = "auto"
    audio_provider: str = "edge_tts"
    quality_profile: str = "standard"
    aspect_ratio: str = "9:16"
    budget_usd: float | None = None


_FEMALE_HINT_KEYS = ("女", "母", "姑", "妃", "娘", "婆", "少女", "女声", "女性", "姐", "妹")


def _guess_gender(character: DesignCharacter) -> str:
    """从 voice_hint / personality / 名字粗判性别,用于挑音色池。判不出默认 male
    (历史题材男性角色居多),不追求精确——只求同一部片里角色声音有区分度。"""
    blob = f"{character.voice_hint} {character.personality} {character.name}"
    if any(k in blob for k in _FEMALE_HINT_KEYS):
        return "female"
    return "male"


def _assign_character_voices(design_list: DesignList) -> dict[str, str]:
    """给每个角色分一个不同的 edge_tts 音色(键为角色名,对应 character_voices)。
    优先用人工在设计清单里显式填的 voice_id;否则按 voice_hint 粗判的性别,在该性别
    音色池里轮询分配,保证同性别的不同角色也落到不同声音(治"对话也像旁白——所有人
    一个声音")。声线倾向里带"低沉/沙哑/浑厚"的优先挑 deep 音色。"""
    from hevi.audio.edge_tts_custom import FEMALE_VOICE_POOL, MALE_VOICE_POOL

    pools = {"male": list(MALE_VOICE_POOL), "female": list(FEMALE_VOICE_POOL)}
    rr = {"male": 0, "female": 0}  # 池用尽后的兜底轮询计数
    used_voices: set[str] = set()  # 已占用的音色,保证还有余量时不重复
    out: dict[str, str] = {}
    for c in design_list.characters:
        if not c.name:
            continue
        if c.voice_id:
            out[c.name] = c.voice_id
            used_voices.add(c.voice_id)
            continue
        gender = _guess_gender(c)
        pool = pools[gender]
        # 声线倾向明确"低沉/沙哑"的,若池里有 deep/mature 音色且还没被占,优先给它。
        deep_pref = any(k in c.voice_hint for k in ("低沉", "沙哑", "浑厚", "苍老"))
        pick = None
        if deep_pref:
            pick = next(
                (v for v in pool if ("deep" in v or "mature" in v) and v not in used_voices), None
            )
        if pick is None:  # 池里第一个还没被占的音色 → 同性别角色尽量互不撞声
            pick = next((v for v in pool if v not in used_voices), None)
        if pick is None:  # 池已用尽(角色数 > 音色数),只能轮询复用
            pick = pool[rr[gender] % len(pool)]
            rr[gender] += 1
        used_voices.add(pick)
        out[c.name] = pick
    return out


async def _resolve_shot_character_refs(
    shot_list: dict[str, Any], design_list: DesignList, *, subject_svc: SubjectService
) -> dict[int, list[str]]:
    """逐镜头把 ShotListItem.character_names(剧本阶段的人物名字符串)解析成该镜头
    出场角色各自的参考图文件路径——orchestrator 侧(shot_character_refs)只处理文件
    路径,不做数据库查询(同 character_reference 现有约定),所以数据库查询放在这里,
    产集这一步天然只做一次,不会像 injected_video_fn 那样每镜/每变体重复查。查不到
    subject 或没有参考图的角色,静默跳过(不阻断整镜,orchestrator 侧本来就有"该镜头
    没有可用参考图 → 回退全片统一参考图"的兜底)。"""
    name_to_path: dict[str, str] = {}
    for c in design_list.characters:
        if not c.subject_id or c.name in name_to_path:
            continue
        try:
            subj = await subject_svc.get_subject(c.subject_id)
        except Exception as e:
            logger.warning("解析角色 %s(subject %s)参考图失败: %s", c.name, c.subject_id, e)
            continue
        refs = (subj or {}).get("reference_images") or []
        if refs:
            name_to_path[c.name] = refs[0]

    out: dict[int, list[str]] = {}
    for idx, shot in enumerate(shot_list.get("shots", [])):
        paths = [name_to_path[n] for n in shot.get("character_names") or [] if n in name_to_path]
        if paths:
            out[idx] = paths
    return out


async def _resolve_subject_ref_paths(
    design_list: DesignList, *, subject_svc: SubjectService
) -> dict[str, str]:
    """角色名 → 设计清单锁定时建的参考图路径(数字人 keyframe 的脸从这来)。查不到的角色
    静默跳过(scene_render_avatar 侧对没有 ref_image 的角色有兜底)。"""
    out: dict[str, str] = {}
    for c in design_list.characters:
        if not c.name or not c.subject_id:
            continue
        try:
            subj = await subject_svc.get_subject(c.subject_id)
        except Exception as e:
            logger.warning("解析角色 %s 参考图失败: %s", c.name, e)
            continue
        refs = (subj or {}).get("reference_images") or []
        if refs:
            out[c.name] = refs[0]
    return out


async def _run_director_via_tongjian(
    *,
    task_repo: TaskRepository,
    task_id: Any,
    shot_list: ShotList,
    design_list: DesignList,
    concept: Concept,
    subject_ref_paths: dict[str, str],
    voice_by_speaker: dict[str, str],
    aspect_ratio: str,
    target_duration_sec: int,
) -> None:
    """后台真实生成:导演锁定内容 → 通鉴对白+口型管线(render_director_episode)。
    直接更新 video_tasks/shot_states,复用前端既有 taskApi.videoUrl/shots(零改动)。
    镜像 shortdrama._run_episode_via_tongjian 的落库方式。"""
    run_dir = Path("output/tasks") / str(task_id)
    await task_repo.update_task(
        task_id, {"status": "running", "updated_at": datetime.now(UTC).replace(tzinfo=None)}
    )
    # 数字人逐镜渲染慢(每镜数分钟),通鉴各层不吐进度回调 → 前端会一直停在 0% 让人以为
    # 卡死(用户实测抱怨)。起一个轮询器数 run_dir 里已产出的 *_talk.mp4 talking clip,
    # 按"有对白的镜头数"折算进度(配音占 ~10%,逐镜数字人 10-90%,装配收尾到 100%)。
    total_talk_shots = max(
        1,
        sum(
            1
            for s in shot_list.shots
            if any(
                (dl.character_name or "").strip() and (dl.text or "").strip()
                for dl in s.dialogue_lines
            )
        ),
    )

    async def _progress_poller() -> None:
        while True:
            await asyncio.sleep(15)
            try:
                done = len(list(run_dir.glob("*_talk.mp4")))
                pct = min(90.0, 10.0 + 80.0 * min(done, total_talk_shots) / total_talk_shots)
                await task_repo.update_task(
                    task_id,
                    {
                        "progress_pct": pct,
                        "completed_shots": done,
                        "total_shots": total_talk_shots,
                        "updated_at": datetime.now(UTC).replace(tzinfo=None),
                    },
                )
            except Exception:  # 进度回写绝不可拖垮生成
                pass

    poller = asyncio.ensure_future(_progress_poller())
    try:
        result = await render_director_episode(
            shot_list=shot_list,
            design_list=design_list,
            concept=concept,
            run_dir=run_dir,
            subject_ref_paths=subject_ref_paths,
            voice_by_speaker=voice_by_speaker,
            aspect_ratio=aspect_ratio,
            target_duration_sec=target_duration_sec,
        )
        final_video = result["final_video"]
        shots = result["shots"]
        task = await task_repo.get_task(task_id)
        config_json = dict((task or {}).get("config_json") or {})
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
        logger.info(
            "director-pipeline task %s 渲染完成(通鉴口型管线): %s", task_id, final_video.video_path
        )
    except Exception as e:
        logger.exception("director-pipeline task %s 渲染失败(通鉴口型管线): %s", task_id, e)
        await task_repo.update_task(
            task_id,
            {
                "status": "failed",
                "error": str(e)[:500],
                "updated_at": datetime.now(UTC).replace(tzinfo=None),
            },
        )
    finally:
        poller.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await poller


@router.post("/works/{work_id}/produce")
async def produce_work(
    work_id: str,
    body: ProduceRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[TaskService, Depends(get_task_service)],
    subject_svc: Annotated[SubjectService, Depends(get_subject_service)],
) -> dict[str, Any]:
    rec = _require_work(work_id, user)
    if rec["locked_through"] < _stage_index("shot_list"):
        raise HTTPException(status_code=409, detail=f"分镜还没锁定(当前 {rec['status']}),不能产集")

    design_list = DesignList.model_validate(rec["design_list"])
    concept = Concept.model_validate(rec["concept"])

    # 每个角色一个不同音色(治"对话也像旁白");用角色名当 key,通鉴 voice_by_speaker
    # 也是按 speaker(=角色名)查。
    character_voices = _assign_character_voices(design_list)
    # 角色名 → 设计清单锁定的参考图(数字人 keyframe 的脸)。
    subject_ref_paths = await _resolve_subject_ref_paths(design_list, subject_svc=subject_svc)
    shot_list = ShotList.model_validate(rec["shot_list"])
    duration_cfg = get_duration_config(concept.duration_archetype)

    # create_task 只用来:建 video_tasks 行 + 预算熔断 + 积分预留(计费一致性)。真正的
    # 生成不走 submit_task/run_task(那条是通用长视频管线 orchestrate_longvideo——把全片
    # 对白拼一条轨、镜头拉伸去填,对白跟画面对不上、看不到说话人,2026-07-14 用户实测
    # 弃用),改成后台跑 render_director_episode(通鉴对白+口型管线)。budget_usd 留空
    # 不透传(见历史注释:None 会撞下游 Pydantic float 校验)。
    create_kwargs: dict[str, Any] = {
        "topic": concept.theme or rec["material_text"][:200],
        "duration_archetype": concept.duration_archetype,
        "video_provider": "happyhorse_1_1_maas_lock",  # 数字人管线的真实 provider,计费按它估
        "audio_provider": "edge_tts",
        "user_id": str(user["id"]),
        "quality_profile": body.quality_profile,
        "aspect_ratio": body.aspect_ratio,
        "style": concept.style or "cinematic",
        "locked_shot_list": rec["shot_list"],
        "character_voices": character_voices or None,
    }
    if body.budget_usd is not None:
        create_kwargs["budget_usd"] = body.budget_usd
    try:
        task = await svc.create_task(**create_kwargs)
    except CostLimitExceeded as e:
        raise HTTPException(status_code=402, detail=str(e)) from e
    except InsufficientCredits as e:
        # 同 tasks.py::create_new_task 既有惯例——余额不够是用户可操作的正常情况
        # (充值/换便宜档),不该原样炸成 500。此前这里没接住,线上用户点"确认生成"
        # 撞到这个就是一个空的 500,看不出任何原因。
        raise HTTPException(
            status_code=402,
            detail={
                "error": "insufficient_credits",
                "credits_needed": e.credits_needed,
                "credits_available": e.credits_available,
            },
        ) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    task_id = task["id"]
    background_tasks.add_task(
        _run_director_via_tongjian,
        task_repo=svc.repository,
        task_id=task_id,
        shot_list=shot_list,
        design_list=design_list,
        concept=concept,
        subject_ref_paths=subject_ref_paths,
        voice_by_speaker=character_voices,
        aspect_ratio=body.aspect_ratio,
        target_duration_sec=int(duration_cfg["target_s"]),
    )

    rec["video_task_id"] = str(task_id)
    rec["status"] = "producing"
    logger.info("director-pipeline work %s → task %s 产集(通鉴口型管线)", work_id, task_id)
    return _work_status(rec)
