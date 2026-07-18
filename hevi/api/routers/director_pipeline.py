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
import hashlib
import logging
import uuid
from dataclasses import asdict
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
from hevi.director import shot_preparation as _prep
from hevi.director.concept import generate_concept_draft
from hevi.director.design_list import generate_design_list_draft
from hevi.director.pipeline_schemas import (
    Concept,
    DesignCharacter,
    DesignList,
    SceneStageSet,
    Screenplay,
    ShotList,
    ShotListItem,
)
from hevi.director.scene_stage import generate_scene_stage_draft, link_shots_to_scene_stage
from hevi.director.scene_stage_lint import lint_scene_stage
from hevi.director.screenplay import generate_screenplay_draft
from hevi.director.shot_list import generate_shot_list_draft
from hevi.director.tongjian_render import render_director_episode
from hevi.director.verdict_checks import ShotVerdict, verdict_shot
from hevi.subjects.repository import SubjectRepository
from hevi.subjects.subject_service import SubjectService
from hevi.tasks.repository import TaskRepository
from hevi.tasks.task_service import TaskService
from hevi.video.duration_mapper import get_duration_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/director-pipeline", tags=["director-pipeline"])

_WORKS: dict[str, dict[str, Any]] = {}
_OUTPUT_DIR = Path("output/director_pipeline")
# 身份锚图 art direction(2026-07-16 实证重写):旧值 "cinematic character portrait" + 战败场
# 的戏剧化 appearance(浴血/怒目)→ qwen-image 脑补成发光红眼、金龙肩甲的恶鬼(实测)。锚图
# 是下游 canonical/关键帧的派生源,必须是**干净中性定妆照**:平静表情、纯背景、写实真人。
_ART_DIRECTION = (
    "写实历史正剧定妆照,真人演员,平静自然的中性表情,正面半身像,柔和自然布光,"
    "纯色中性摄影棚背景,写实肤色、正常五官比例"
)
# 强负面词(实测能压住 qwen-image 的"电影级奇幻战场"风格惯性):发光眼/血污/游戏动漫/
# 奇幻夸张铠甲、金属鬼脸龙纹肩甲、瞪眼变形——这些是模型自行脑补加的,正向词压不住,靠负面词。
_PORTRAIT_NEGATIVE = (
    "发光的眼睛,红色眼睛,红眼,异色瞳,眼睛发光,血污,血迹,伤口,伤疤,恐怖,魔化,獠牙,"
    "游戏角色,动漫风,奇幻铠甲,发光盔甲,尖角肩甲,金属鬼脸肩甲,龙纹肩甲,浮夸金饰,夸张装饰,"
    "瞪大眼睛,凶神恶煞,五官变形,战场火光背景,烟雾"
)
# INC-003 场景资产走**空景板**口径(不是定妆照):要一张能当多角色 img2img 底图画布的**无人**
# 环境图。此前 scene 也套 _ART_DIRECTION(定妆照:"正面半身像,摄影棚背景"),环境描述压过口径 →
# 出来是"带一个人的环境图"(当底图会变三个人)。且 scene 参考图此前从没进渲染层(死资产),改
# 口径零回归。空景板经桥接层 scene_bg_by_id 进渲染层当画布。
_SCENE_PLATE_DIRECTION = (
    "写实历史正剧场景空镜,电影感建场镜头,广角全景,只有环境没有任何人物,自然布光,写实质感"
)
_SCENE_PLATE_NEGATIVE = "人物,人,角色,人群,肖像,半身像,面孔,行人,演员"
_PORTRAIT_MAX_ATTEMPTS = 3

# ①→②→③→③.5→④,每级有 _draft/_locked 两态。scene_stage(SPEC-004 场面调度)插在
# design_list 与 shot_list 之间:未锁 scene_stage 则 shot_list 无法锁(_require_stage_ready
# 走 _STAGES 顺序,自动成立),产集门 _stage_index("shot_list") 也随之右移,无需另改。
_STAGES = ("concept", "screenplay", "design_list", "scene_stage", "shot_list")
_STAGE_KEY = {  # 内存记录里存内容用的 key(跟 URL path 段独立,path 用连字符,dict 用下划线)
    "concept": "concept",
    "screenplay": "screenplay",
    "design_list": "design_list",
    "scene_stage": "scene_stage",
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
        "scene_stage": None,
        "shot_list": None,
        "scene_stage_lint": [],  # SPEC-004 §4:链接后跑的四条确定性 lint findings(生成后守护)
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
        "scene_stage": rec["scene_stage"],
        "shot_list": rec["shot_list"],
        "scene_stage_lint": rec.get("scene_stage_lint", []),
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
    work_id: str,
    body: Concept,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    rec = _require_work(work_id, user)
    rec["concept"] = body.model_dump()
    rec["locked_through"] = _stage_index("concept")
    # ②剧本草案含 LLM 自审-修订二遍(~106s),超同步反代 100s → 放后台跑,前端轮询
    # screenplay_generating 落地(同 scene_stage/shot_list 模式)。
    rec["status"] = "screenplay_generating"
    rec["error"] = None
    background_tasks.add_task(_run_screenplay_generate, work_id)
    return _work_status(rec)


# ── ②剧本 ─────────────────────────────────────────────────────────────────


async def _run_screenplay_generate(work_id: str) -> None:
    """②剧本草案后台生成:含 LLM 自审-修订二遍(初稿→审核员挑毛病并改好,总延迟 ~106s),
    超同步反代 100s → 放后台,前端轮询 screenplay_generating 落地。concept 已由调用端锁进 rec。"""
    rec = _WORKS.get(work_id)
    if rec is None:
        return
    try:
        concept = Concept.model_validate(rec["concept"])
        screenplay = await generate_screenplay_draft(
            concept=concept, material_text=rec["material_text"], llm=_resolve_llm()
        )
        rec["screenplay"] = screenplay.model_dump()
        rec["status"] = "screenplay_draft"
    except Exception as e:
        logger.exception("screenplay 后台生成失败: work_id=%s", work_id)
        rec["status"] = "screenplay_generate_failed"
        rec["error"] = str(e)


@router.post("/works/{work_id}/screenplay")
async def regenerate_screenplay(
    work_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    rec = _require_work(work_id, user)
    _require_stage_ready(rec, "screenplay")
    _rollback_downstream(rec, "screenplay")
    rec["status"] = "screenplay_generating"
    rec["error"] = None
    background_tasks.add_task(_run_screenplay_generate, work_id)
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
        if kind == "scene":
            # 空景板:无人环境图,当多角色 img2img 底图画布(INC-003)。
            prompt = f"{_SCENE_PLATE_DIRECTION},{name},{description or ''}"
            negative = _SCENE_PLATE_NEGATIVE
        else:
            prompt = f"{_ART_DIRECTION},{name},{description or kind}"
            # character 才压这套"发光眼/奇幻甲"负面词(prop 不需要,免得误伤道具材质)。
            negative = _PORTRAIT_NEGATIVE if kind == "character" else ""
        # 确定性 seed(治"每次测同一段故事人物形象都不一样"):按角色名派生稳定 seed,同名
        # 永远同脸——即便查重没命中要新建、或跨产集/跨进程重生成。hashlib(非内置 hash())
        # 保证跨进程稳定,不受 PYTHONHASHSEED 影响。
        seed = int(hashlib.sha256(name.encode("utf-8")).hexdigest(), 16) % (2**31)
        last_exc: Exception | None = None
        for attempt in range(1, _PORTRAIT_MAX_ATTEMPTS + 1):
            try:
                async with _concurrency:
                    await qwen_image_generate(
                        prompt=prompt,
                        output_path=portrait_path,
                        seed=seed,
                        negative_prompt=negative,
                    )
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


async def _build_scene_stage_set(screenplay: Screenplay, design_list: DesignList) -> SceneStageSet:
    """SPEC-004 ③.5:逐场生成 SceneStage 草案(每场一个,scene_ref=scene_no)。逐场 LLM,
    场次一多同 design-list 的重活,放后台跑。单场失败不拖垮整体——退回最小可锁草稿。"""
    stages = []
    for scene in screenplay.scenes:
        stage = await generate_scene_stage_draft(
            scene=scene, design_list=design_list, llm=_resolve_llm()
        )
        stages.append(stage)
    return SceneStageSet(stages=stages)


async def _run_design_list_lock(
    work_id: str, body: DesignList, *, user_id: str, subject_svc: SubjectService
) -> None:
    """③锁定的真正重活(N 个资产建号 + ③.5 场面调度逐场 LLM 生成)——角色/场次一多,就算
    每个调用本身都做了并发/超时收敛,总和还是可能顶到反向代理超时(线上已实测 524/挂起
    好几轮)。放到 background task 里跑,HTTP 响应不再等它,前端轮询 GET /works/{id}
    直到状态变化即可。SPEC-004:③锁定后自动生成的下一级不再是④分镜,而是③.5 场面调度草案。"""
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
        scene_stage = await _build_scene_stage_set(screenplay, locked)
        rec["scene_stage"] = scene_stage.model_dump()
        rec["status"] = "scene_stage_draft"
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


# ── ③.5 场面调度 SceneStage(SPEC-004)────────────────────────────────────────
#
# ③设计清单锁定后自动生成本级草案(每场一个 SceneStage);人在 Construction-First 下攻击
# 落位/注意力/机位后锁定,才放行④分镜。未锁本级则 shot-list 无法锁(_require_stage_ready
# 自动成立)。逐场 LLM 生成同 design-list 是重活,放 background task。


async def _run_scene_stage_regenerate(work_id: str) -> None:
    """③.5 逐场场面调度草案后台重生成(场次一多不顶反向代理超时,同 design-list 模式)。"""
    rec = _WORKS.get(work_id)
    if rec is None:
        return
    try:
        screenplay = Screenplay.model_validate(rec["screenplay"])
        design_list = DesignList.model_validate(rec["design_list"])
        scene_stage = await _build_scene_stage_set(screenplay, design_list)
        rec["scene_stage"] = scene_stage.model_dump()
        rec["status"] = "scene_stage_draft"
    except Exception as e:
        logger.exception("scene-stage 后台重新生成失败: work_id=%s", work_id)
        rec["status"] = "scene_stage_regenerate_failed"
        rec["error"] = str(e)


@router.post("/works/{work_id}/scene-stage")
async def regenerate_scene_stage(
    work_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    rec = _require_work(work_id, user)
    _require_stage_ready(rec, "scene_stage")
    _rollback_downstream(rec, "scene_stage")
    rec["status"] = "scene_stage_generating"
    rec["error"] = None
    background_tasks.add_task(_run_scene_stage_regenerate, work_id)
    return _work_status(rec)


async def _run_scene_stage_lock(work_id: str) -> None:
    """③.5 锁定后自动生成④分镜草案(逐场 LLM,放后台)。SPEC-004:shot_list 生成本身此级
    暂不接 SceneStage 引用(那是阶段 3 的桥接层投影),仅由本级门控放行——保持阶段 2 聚焦状态机。"""
    rec = _WORKS.get(work_id)
    if rec is None:
        return
    try:
        screenplay = Screenplay.model_validate(rec["screenplay"])
        design_list = DesignList.model_validate(rec["design_list"])
        shot_list = await generate_shot_list_draft(
            screenplay=screenplay, design_list=design_list, llm=_resolve_llm()
        )
        # SPEC-004 阶段 3:确定性填充每镜的场事实引用(scene_stage_ref/beat_range/
        # camera_setup_ref/attention_ref),画面空间/焦点由桥接层从 SceneStage 投影。
        scene_stage = SceneStageSet.model_validate(rec["scene_stage"])
        shot_list = link_shots_to_scene_stage(shot_list, scene_stage)
        rec["shot_list"] = shot_list.model_dump()
        # SPEC-004 §4:链接后跑四条确定性 lint(跳轴/反打/eyeline/剪辑冗余),findings 暴露给前端。
        rec["scene_stage_lint"] = [asdict(f) for f in lint_scene_stage(shot_list, scene_stage)]
        rec["status"] = "shot_list_draft"
    except Exception as e:
        logger.exception("scene-stage 锁定后生成分镜失败: work_id=%s", work_id)
        rec["status"] = "scene_stage_lock_failed"
        rec["error"] = str(e)


@router.post("/works/{work_id}/scene-stage/lock")
async def lock_scene_stage(
    work_id: str,
    body: SceneStageSet,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    rec = _require_work(work_id, user)
    rec["scene_stage"] = body.model_dump()
    rec["locked_through"] = _stage_index("scene_stage")
    rec["status"] = "scene_stage_locking"
    rec["error"] = None
    background_tasks.add_task(_run_scene_stage_lock, work_id)
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
        if rec.get("scene_stage"):  # SPEC-004 阶段 3:重新链接场事实引用 + §4 lint
            scene_stage = SceneStageSet.model_validate(rec["scene_stage"])
            shot_list = link_shots_to_scene_stage(shot_list, scene_stage)
            rec["scene_stage_lint"] = [asdict(f) for f in lint_scene_stage(shot_list, scene_stage)]
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


# ── 逐镜头准备台(INC-001 §A/§G/§I/§L)──────────────────────────────────────
#
# §L.2 职责边界:准备台(本组端点)负责提取资产/对白候选 → 确认 → 把镜头推进到 ready;
# 生成台(/produce)负责真实生成。所有 mutation 统一返回 {action, state}(§L.1 聚合态),
# 前端不再自己拼 pendingConfirmCount / 推导 shot.status。


def _find_shot(rec: dict[str, Any], shot_id: str) -> ShotListItem | None:
    for s in (rec.get("shot_list") or {}).get("shots", []):
        if s.get("shot_id") == shot_id:
            return ShotListItem.model_validate(s)
    return None


def _parse_candidate_id(candidate_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(candidate_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail="candidate_id 不是合法 UUID") from e


class ConfirmCandidateRequest(BaseModel):
    kind: str  # "asset" | "dialogue"
    status: str  # asset: linked/ignored/pending;dialogue: accepted/ignored/pending
    linked_entity_id: str | None = None  # asset 确认时的 subject_id
    linked_dialog_line_id: str | None = None  # dialogue 接受时的 ShotDialogLine id


class ReadinessPatch(BaseModel):
    skip_extraction: bool


@router.get("/works/{work_id}/preparation-overview")
async def preparation_overview(
    work_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    pool: Annotated[PgPool, Depends(get_pg_pool)],
) -> dict[str, Any]:
    """§L.1 全片就绪概览:每镜 status/extracted/skip_extraction + 产集拦截项。生成台用它
    判断"能不能生成、还差哪些镜"。未准备过的镜合并出默认 pending。"""
    rec = _require_work(work_id, user)
    overview = {r["shot_id"]: r for r in await _prep.readiness_overview(pool, work_id)}
    shots = [
        {
            "shot_id": s.get("shot_id"),
            "status": overview.get(s.get("shot_id"), {}).get("status", "pending"),
            "extracted": overview.get(s.get("shot_id"), {}).get("extracted", False),
            "skip_extraction": overview.get(s.get("shot_id"), {}).get("skip_extraction", False),
        }
        for s in (rec.get("shot_list") or {}).get("shots", [])
    ]
    return {"shots": shots, "blockers": await _prep.produce_blockers(pool, work_id)}


@router.get("/works/{work_id}/shots/{shot_id}/preparation-state")
async def get_shot_preparation_state(
    work_id: str,
    shot_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    pool: Annotated[PgPool, Depends(get_pg_pool)],
) -> dict[str, Any]:
    rec = _require_work(work_id, user)
    return await _prep.get_preparation_state(pool, work_id, shot_id, _find_shot(rec, shot_id))


@router.post("/works/{work_id}/shots/{shot_id}/extract")
async def extract_shot_candidates(
    work_id: str,
    shot_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    pool: Annotated[PgPool, Depends(get_pg_pool)],
) -> dict[str, Any]:
    """§G 提取:从已锁 ShotListItem 确定性物化候选(不另调 LLM)。"""
    rec = _require_work(work_id, user)
    shot = _find_shot(rec, shot_id)
    if shot is None:
        raise HTTPException(status_code=404, detail="shot 不存在(分镜未锁定或 shot_id 错误)")
    await _prep.extract_shot(pool, work_id, shot)
    state = await _prep.get_preparation_state(pool, work_id, shot_id, shot)
    return {"action": "extract", "state": state}


@router.post("/works/{work_id}/shots/{shot_id}/candidates/{candidate_id}/confirm")
async def confirm_shot_candidate(
    work_id: str,
    shot_id: str,
    candidate_id: str,
    body: ConfirmCandidateRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    pool: Annotated[PgPool, Depends(get_pg_pool)],
) -> dict[str, Any]:
    """§G/§A.2 确认(或回退)一条候选,后端按 §A.1 重算就绪。"""
    rec = _require_work(work_id, user)
    cand = _parse_candidate_id(candidate_id)
    if body.kind == "asset":
        if body.status not in ("linked", "ignored", "pending"):
            raise HTTPException(status_code=422, detail="asset 候选状态须为 linked/ignored/pending")
        await _prep.set_asset_candidate(
            pool, work_id, shot_id, cand, status=body.status, linked_entity_id=body.linked_entity_id
        )
    elif body.kind == "dialogue":
        if body.status not in ("accepted", "ignored", "pending"):
            raise HTTPException(
                status_code=422, detail="dialogue 候选状态须为 accepted/ignored/pending"
            )
        await _prep.set_dialogue_candidate(
            pool,
            work_id,
            shot_id,
            cand,
            status=body.status,
            linked_dialog_line_id=body.linked_dialog_line_id,
        )
    else:
        raise HTTPException(status_code=422, detail="kind 须为 asset 或 dialogue")
    state = await _prep.get_preparation_state(pool, work_id, shot_id, _find_shot(rec, shot_id))
    return {"action": "confirm", "state": state}


@router.patch("/works/{work_id}/shots/{shot_id}/readiness")
async def patch_shot_readiness(
    work_id: str,
    shot_id: str,
    body: ReadinessPatch,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    pool: Annotated[PgPool, Depends(get_pg_pool)],
) -> dict[str, Any]:
    """§I skip_extraction 逃生阀:置 true → 该镜直达 ready。"""
    rec = _require_work(work_id, user)
    await _prep.set_skip_extraction(pool, work_id, shot_id, body.skip_extraction)
    state = await _prep.get_preparation_state(pool, work_id, shot_id, _find_shot(rec, shot_id))
    return {"action": "skip_extraction", "state": state}


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


async def _resolve_scene_ref_paths(
    design_list: DesignList, *, subject_svc: SubjectService
) -> dict[str, str]:
    """INC-003:场景名 → ③锁定时建的空景板路径(多角色 img2img 底图画布)。scene 参考图口径已改
    成"无人环境图"(见 _SCENE_PLATE_DIRECTION)。key = DesignScene.name(= 渲染层 shot.scene_id)。
    查不到静默跳过 → 渲染层退回中性灰。"""
    out: dict[str, str] = {}
    for s in design_list.scenes:
        if not s.name or not s.subject_id:
            continue
        try:
            subj = await subject_svc.get_subject(s.subject_id)
        except Exception as e:
            logger.warning("解析场景 %s 空景板失败: %s", s.name, e)
            continue
        refs = (subj or {}).get("reference_images") or []
        if refs:
            out[s.name] = refs[0]
    return out


def _has_multichar_shots(shot_list: ShotList) -> bool:
    """有没有任何 ≥2 角色同框镜头(INC-003 compose 路由:有则需给出场角色建 Subject3D 视图,
    不再只在 scene_stage 有角度时建)。"""
    return any(len(sh.character_names or []) >= 2 for sh in shot_list.shots)


def _scene_stage_has_angles(scene_stage: SceneStageSet | None) -> bool:
    """SceneStage 里有没有任何结构化角度(facing_deg/azimuth_deg)——没有就没必要建 Subject3D
    视图(建了也一律 front、白花 ~172s/角色)。"""
    if scene_stage is None:
        return False
    for s in scene_stage.stages:
        if any(p.facing_deg is not None for p in s.blocking.initial_positions):
            return True
        if any(cs.azimuth_deg is not None for cs in s.coverage_plan.setups):
            return True
        if s.coverage_plan.master and s.coverage_plan.master.azimuth_deg is not None:
            return True
    return False


async def _resolve_subject3d_views(
    design_list: DesignList, *, subject_svc: SubjectService
) -> dict[str, dict[str, str]]:
    """SPEC-004 v2:角色名 → Subject3D 4 视图路径({view: path})。已建(metadata.subject3d.views)
    直接用;未建则调 generate_subject3d 现建(TripoSR CPU ~172s/角色,缓存进 metadata)。单个角色
    建失败静默跳过(该角色渲染时退回正面 2D 真照)。仅在 scene_stage 有角度时才调这里(见 gate)。"""
    out: dict[str, dict[str, str]] = {}
    for c in design_list.characters:
        if not c.name or not c.subject_id:
            continue
        try:
            subj = await subject_svc.get_subject(c.subject_id)
            views = ((subj or {}).get("metadata") or {}).get("subject3d", {}).get("views")
            if not views:
                built = await subject_svc.generate_subject3d(c.subject_id)
                views = (built or {}).get("views")
            if views:
                out[c.name] = views
        except Exception as e:
            logger.warning("角色 %s Subject3D 视图解析/生成失败,退回正面: %s", c.name, e)
    return out


_VERDICT_MAX_RETAKE = 1  # 尝试预算(§4.1.2):失败镜最多重掷 1 次,不无限烧钱


def _derive_shot_id(clip_path: str | None) -> str:
    """从 clip 路径反推 tongjian shot_id:.../SH003_02_clip.mp4 → SH003_02。"""
    if not clip_path:
        return ""
    stem = Path(clip_path).stem  # SH003_02_clip
    for suf in ("_clip", "_talk", "_narr", "_vis"):
        if stem.endswith(suf):
            return stem[: -len(suf)]
    return stem


def _purge_shot_artifacts(run_dir: Path, shot_id: str, *, hard: bool) -> None:
    """删掉某镜头的产物,逼 tongjian 渲染重生成它(其余镜头 clip 仍在 → 缓存复用不重跑)。
    re_roll(hard=False)只删动画/成片产物,保留关键帧 kf(同 prompt 重掷);
    rewrite(hard=True)连 kf 一起删,逼重出关键帧(治身份漂移)。"""
    if not shot_id:
        return
    pats = [f"{shot_id}_clip*", f"{shot_id}_talk*", f"{shot_id}_vis*", f"{shot_id}_narr*"]
    if hard:
        pats += [f"{shot_id}_kf*", f"{shot_id}_first*"]
    for pat in pats:
        for p in run_dir.glob(pat):
            with contextlib.suppress(Exception):
                p.unlink()


async def _run_verdict(shots: list[dict[str, Any]], vlm: Any) -> list[ShotVerdict]:
    out: list[ShotVerdict] = []
    for s in shots:
        clip = Path(s["path"]) if s.get("path") else None
        sid = _derive_shot_id(s.get("path"))
        if clip is None or not clip.exists():
            out.append(
                ShotVerdict(
                    shot_index=s["index"],
                    shot_id=sid,
                    passed=False,
                    diagnosis_category="动作",
                    retake_tier="re_roll",
                )
            )
            continue
        if s.get("degraded"):
            # 渲染层已判这一镜走了降级链(最典型:关键帧抄了 canon 定妆照 → 成片是"大头念
            # 台词")。verdict 的三项检查对这种镜**全部会通过**——画面不黑,身份分还满分
            # (它就是那张 canon 本人)。2026-07-17 审计实证:一次真实产集 20 镜里 14 镜如此,
            # 交付门全绿放行。故不重跑检查,直接尊重上游结论 → rewrite(hard purge 连 kf 一起
            # 删,逼重出关键帧;re_roll 保 kf 会把同一张定妆照再拼一遍,白烧钱)。
            out.append(
                ShotVerdict(
                    shot_index=s["index"],
                    shot_id=sid,
                    identity_score=s.get("consistency_score"),
                    passed=False,
                    diagnosis_category=s.get("diagnosis_category") or "构图",
                    retake_tier="rewrite",
                    checks={"upstream_degraded": True},
                )
            )
            continue
        out.append(
            await verdict_shot(
                shot_index=s["index"],
                shot_id=sid,
                clip_path=clip,
                identity_score=s.get("consistency_score"),
                vlm=vlm,
            )
        )
    return out


async def _persist_verdicts(
    pool: Any, task_id: Any, verdicts: list[ShotVerdict], attempt: int
) -> None:
    import json
    import uuid as _uuid

    async with pool.acquire() as conn:
        for v in verdicts:
            with contextlib.suppress(Exception):  # 落库失败不该拖垮出片
                await conn.execute(
                    "INSERT INTO shot_verdict (id, task_id, shot_index, shot_id, provider, "
                    "identity_score, black_ratio, hand_safety_ok, checks_json, "
                    "diagnosis_category, retake_tier, attempt, passed) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11,$12,$13)",
                    _uuid.uuid4(),
                    task_id,
                    v.shot_index,
                    v.shot_id,
                    v.provider,
                    v.identity_score,
                    v.black_ratio,
                    v.hand_safety_ok,
                    json.dumps(v.checks),
                    v.diagnosis_category,
                    v.retake_tier,
                    attempt,
                    v.passed,
                )


async def _verdict_and_retake(
    *,
    run_dir: Path,
    result: dict[str, Any],
    render_kwargs: dict[str, Any],
    task_repo: Any,
    task_id: Any,
) -> dict[str, Any]:
    """成片逐镜头裁决 + 五档返工(§6.1/§4.1.2)。失败镜按 tier 清产物重掷,最多 1 次;
    每一轮 verdict 都落 shot_verdict 表(护城河②数据资产)。返回最终 result。"""
    from obase.provider_registry import ProviderRegistry

    try:
        vlm = ProviderRegistry.get().vlm("default")
    except Exception:
        vlm = None

    verdicts = await _run_verdict(result["shots"], vlm)
    await _persist_verdicts(task_repo.pool, task_id, verdicts, attempt=0)

    attempt = 0
    while attempt < _VERDICT_MAX_RETAKE and any(not v.passed for v in verdicts):
        failed = [v for v in verdicts if not v.passed]
        logger.info(
            "director task %s verdict 第%d轮:%d 镜不过 → 返工 %s",
            task_id,
            attempt,
            len(failed),
            [(v.shot_id, v.retake_tier) for v in failed],
        )
        for v in failed:
            _purge_shot_artifacts(run_dir, v.shot_id, hard=(v.retake_tier == "rewrite"))
        attempt += 1
        result = await render_director_episode(**render_kwargs)  # 只重生成被清掉的镜头
        verdicts = await _run_verdict(result["shots"], vlm)
        await _persist_verdicts(task_repo.pool, task_id, verdicts, attempt=attempt)

    n_fail = sum(1 for v in verdicts if not v.passed)
    logger.info(
        "director task %s verdict 完成:%d/%d 镜通过(返工 %d 轮)",
        task_id,
        len(verdicts) - n_fail,
        len(verdicts),
        attempt,
    )
    return result


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
    scene_stage: SceneStageSet | None = None,
    subject_svc: SubjectService | None = None,
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

    # 建/取每角色的 Subject3D 视图。两种情形要建:①SPEC-004 v2 SceneStage 设了角度(非正面镜走
    # img2img 从对应视图带朝向);②INC-003 有 ≥2 角色同框镜头(compose 路由:多角色关键帧从各角色
    # front 视图按走位拼底图,需要视图)。都不满足则一律 front、建了白费 ~172s/角色,跳过。
    subject3d_views: dict[str, dict[str, str]] = {}
    if subject_svc is not None and (
        _scene_stage_has_angles(scene_stage) or _has_multichar_shots(shot_list)
    ):
        subject3d_views = await _resolve_subject3d_views(design_list, subject_svc=subject_svc)

    # INC-003:每场景空景板路径(多角色 img2img 底图画布)。无则渲染层退回中性灰。
    scene_bg_paths: dict[str, str] = {}
    if subject_svc is not None and _has_multichar_shots(shot_list):
        scene_bg_paths = await _resolve_scene_ref_paths(design_list, subject_svc=subject_svc)

    render_kwargs = {
        "shot_list": shot_list,
        "design_list": design_list,
        "concept": concept,
        "run_dir": run_dir,
        "subject_ref_paths": subject_ref_paths,
        "voice_by_speaker": voice_by_speaker,
        "aspect_ratio": aspect_ratio,
        "target_duration_sec": target_duration_sec,
        # SPEC-004 阶段 3:场事实 → render_director_episode 逐镜投影空间/焦点进关键帧 prompt。
        "scene_stage": scene_stage,
        # SPEC-004 v2:每角色 Subject3D 视图,非正面镜走 img2img 从对应视图带朝向。
        "subject3d_views": subject3d_views,
        # INC-003:每场景空景板,多角色镜头 img2img 底图画布。
        "scene_bg_paths": scene_bg_paths,
    }
    poller = asyncio.ensure_future(_progress_poller())
    try:
        result = await render_director_episode(**render_kwargs)
        # 成片逐镜头裁决 + 五档返工(黑帧/崩手/身份漂移 → re_roll/rewrite),落 shot_verdict。
        result = await _verdict_and_retake(
            run_dir=run_dir,
            result=result,
            render_kwargs=render_kwargs,
            task_repo=task_repo,
            task_id=task_id,
        )
        final_video = result["final_video"]
        shots = result["shots"]
        task = await task_repo.get_task(task_id)
        config_json = dict((task or {}).get("config_json") or {})
        config_json["actual_usd"] = config_json.get("estimated_usd", 0.0)
        # 返工预算(_VERDICT_MAX_RETAKE)用尽后仍不过的镜:成片存在、可看,但它是残的。
        # 此前 completed_shots 恒填 len(shots),等于宣称"每一镜都成了"——2026-07-17 审计那次
        # 产集 20 镜里 14 镜关键帧是定妆照,任务照样报 completed/100%/20 镜全完成。数字必须说真话。
        n_failed = sum(1 for s in shots if not s.get("passed", True))
        config_json["failed_shots"] = n_failed
        if n_failed:
            logger.error(
                "director-pipeline task %s 成片交付但 %d/%d 镜未过裁决(返工已用尽):%s",
                task_id,
                n_failed,
                len(shots),
                [s.get("diagnosis_category") for s in shots if not s.get("passed", True)][:5],
            )
        await task_repo.update_task(
            task_id,
            {
                "status": "completed",
                "progress_pct": 100.0,
                "result_video_path": final_video.video_path,
                "total_shots": len(shots),
                "completed_shots": len(shots) - n_failed,
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
    pool: Annotated[PgPool, Depends(get_pg_pool)],
) -> dict[str, Any]:
    rec = _require_work(work_id, user)
    if rec["locked_through"] < _stage_index("shot_list"):
        raise HTTPException(status_code=409, detail=f"分镜还没锁定(当前 {rec['status']}),不能产集")

    # §L.2 就绪门:被实际准备过(extracted)却仍有待确认候选的镜头拦产集(未准备过的镜不拦,
    # 向后兼容"锁分镜直接产集"的旧路径)。
    blockers = await _prep.produce_blockers(pool, work_id)
    if blockers:
        raise HTTPException(
            status_code=409,
            detail=f"还有 {len(blockers)} 个镜头未完成准备(提取后仍有待确认候选):{blockers[:5]}",
        )

    design_list = DesignList.model_validate(rec["design_list"])
    concept = Concept.model_validate(rec["concept"])

    # 每个角色一个不同音色(治"对话也像旁白");用角色名当 key,通鉴 voice_by_speaker
    # 也是按 speaker(=角色名)查。
    character_voices = _assign_character_voices(design_list)
    # 角色名 → 设计清单锁定的参考图(数字人 keyframe 的脸)。
    subject_ref_paths = await _resolve_subject_ref_paths(design_list, subject_svc=subject_svc)
    shot_list = ShotList.model_validate(rec["shot_list"])
    # SPEC-004 阶段 3:场事实(逐镜投影空间/焦点)。旧 work 无 scene_stage → None,渲染退回断链#3。
    scene_stage = (
        SceneStageSet.model_validate(rec["scene_stage"]) if rec.get("scene_stage") else None
    )
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
        scene_stage=scene_stage,
        subject_svc=subject_svc,  # SPEC-004 v2:后台建/取 Subject3D 视图用
    )

    rec["video_task_id"] = str(task_id)
    rec["status"] = "producing"
    logger.info("director-pipeline work %s → task %s 产集(通鉴口型管线)", work_id, task_id)
    return _work_status(rec)
