"""主线导演流水线 API —— 立意→剧本→设计清单→World Bible→Scene Script,逐级人审核锁定
才放行下游。

  - POST /director-pipeline/works                          素材 → 建 work + 生成①立意草稿
  - GET  /director-pipeline/works / /works/{id}             列出/查询 work 全量状态
  - POST /works/{id}/concept | /screenplay | /design-list | /world-bible | /scene-script
                                                             重新生成本级草稿(未锁定可反复调;
                                                             已锁定再调 = 回退该级 + 清空全部下游)
  - POST /works/{id}/concept/lock(及对应 screenplay/design-list/world-bible/scene-script/lock)
                                                             存入(可能已编辑的)内容 → 锁定 →
                                                             自动生成下一级草稿
  - POST /works/{id}/produce                                仅 scene_script_locked 才允许,
                                                             走 V2 document-first 管线
                                                             (`hevi.director.produce_v2::
                                                             run_v2_produce`)出真实成片

V1→V2 原地升级(2026-07-21,替换不并行):第4/5 级从 V1 的③.5 场面调度 SceneStage/④分镜
ShotList 换成 V2 的④World Bible/⑤Scene Script(`docs/specs/SPEC-007-cinematic-pipeline.md`,
G-FINAL 真机验证过),`/produce` 真正发起生成也从通鉴口型管线(`_run_director_via_tongjian`)
换成 `run_v2_produce`(多角色 reference-to-video,身份/风格/去重闸门齐全)。V1 那条路径
(`_run_director_via_tongjian` 及其 `scene_stage.py`/`shot_list.py`/`shot_preparation.py`/
`verdict_checks.py`/`tongjian_render.py` 依赖)标记 deprecated、不再被这个路由调用,但
**代码不删**——`scene_stage.py`/`scene_stage_lint.py` 有几个私有函数被 V2 自己的
`scene_stage_extract.py` 复用,`scene_render_avatar.py` 仍是通鉴/短剧频道的生产依赖,动不得。

跟现有 `director.py::director_create_episode`(一句话直接产集)并行存在,不替换——那是
另一条更早的极简路径,不是这次升级的范围。

work 状态存内存 map(同 tongjian/shortdrama 的既有 P0 兜底,不建表——`video_tasks` 只在
`/produce` 真正建生成任务时才创建那一行)。
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
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
    SceneScriptSet,
    SceneStageSet,
    Screenplay,
    ShotList,
    WorldBible,
)
from hevi.director.produce_v2 import run_v2_produce
from hevi.director.scene_script import generate_scene_script_draft
from hevi.director.scene_stage import generate_scene_stage_draft
from hevi.director.screenplay import generate_screenplay_draft
from hevi.director.tongjian_render import render_director_episode
from hevi.director.verdict_checks import ShotVerdict, verdict_shot
from hevi.director.world_bible import generate_world_bible_draft
from hevi.subjects.repository import SubjectRepository
from hevi.subjects.subject_service import SubjectService
from hevi.tasks.repository import TaskRepository
from hevi.tasks.task_service import TaskService
from hevi.tongjian.scene_render_avatar import multichar_chain_log

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

# V1→V2 原地升级(2026-07-21):①→②→③→④→⑤,同槽位替换不是插入新槽位——第4/5 槽从
# V1 的 scene_stage/shot_list 换成 V2 的 world_bible/scene_script,_stage_index 的下标
# 语义不变(_require_stage_ready/产集门槛照样按 _STAGES 顺序走,不用另改)。V1 的
# scene_stage/shot_list 生成函数仍保留在文件里(标记 deprecated,给 `_run_director_via_
# tongjian` 这条不再被调用但也不删除的旧路径用),只是不再是这五级流程的一部分。
_STAGES = ("concept", "screenplay", "design_list", "world_bible", "scene_script")
_STAGE_KEY = {  # 内存记录里存内容用的 key(跟 URL path 段独立,path 用连字符,dict 用下划线)
    "concept": "concept",
    "screenplay": "screenplay",
    "design_list": "design_list",
    "world_bible": "world_bible",
    "scene_script": "scene_script",
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
        "world_bible": None,
        "scene_script": None,
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
        "world_bible": rec["world_bible"],
        "scene_script": rec["scene_script"],
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
    """③锁定的真正重活(N 个资产建号 + ④World Bible 四卷并发 LLM 生成)——角色/场次一多,
    就算每个调用本身都做了并发/超时收敛,总和还是可能顶到反向代理超时(线上已实测
    524/挂起好几轮)。放到 background task 里跑,HTTP 响应不再等它,前端轮询
    GET /works/{id} 直到状态变化即可。V1→V2 原地升级(2026-07-21):③锁定后自动生成的
    下一级不再是 V1 的③.5 场面调度草案,是 V2 的④World Bible 草案。"""
    rec = _WORKS.get(work_id)
    if rec is None:
        return
    try:
        locked = await _lock_design_list_assets(
            body, user_id=user_id, work_id=work_id, subject_svc=subject_svc
        )
        rec["design_list"] = locked.model_dump()
        rec["locked_through"] = _stage_index("design_list")
        concept = Concept.model_validate(rec["concept"])
        world_bible = await generate_world_bible_draft(
            concept=concept,
            material_text=rec["material_text"],
            design_list=locked,
            llm=_resolve_llm(),
        )
        rec["world_bible"] = world_bible.model_dump()
        rec["status"] = "world_bible_draft"
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


# ── ④World Bible(V1→V2 原地升级,2026-07-21,替换原③.5 场面调度 SceneStage)──────
#
# ③设计清单锁定后自动生成本级草案(四卷并发生成,`generate_world_bible_draft`);人审
# 编辑后锁定,才放行⑤Scene Script。逐卷并发 LLM 是重活,放 background task(同
# design-list 既有模式)。


async def _run_world_bible_generate(work_id: str) -> None:
    """④World Bible 草案后台生成(四卷并发 LLM,不顶反向代理超时,同 design-list 模式)。"""
    rec = _WORKS.get(work_id)
    if rec is None:
        return
    try:
        concept = Concept.model_validate(rec["concept"])
        design_list = DesignList.model_validate(rec["design_list"])
        world_bible = await generate_world_bible_draft(
            concept=concept,
            material_text=rec["material_text"],
            design_list=design_list,
            llm=_resolve_llm(),
        )
        rec["world_bible"] = world_bible.model_dump()
        rec["status"] = "world_bible_draft"
    except Exception as e:
        logger.exception("world-bible 后台生成失败: work_id=%s", work_id)
        rec["status"] = "world_bible_generate_failed"
        rec["error"] = str(e)


@router.post("/works/{work_id}/world-bible")
async def regenerate_world_bible(
    work_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    rec = _require_work(work_id, user)
    _require_stage_ready(rec, "world_bible")
    _rollback_downstream(rec, "world_bible")
    rec["status"] = "world_bible_generating"
    rec["error"] = None
    background_tasks.add_task(_run_world_bible_generate, work_id)
    return _work_status(rec)


async def _build_scene_script_set(
    screenplay: Screenplay, design_list: DesignList, world_bible: WorldBible
) -> SceneScriptSet:
    """逐场生成 SceneScript 草案,**链式** `prev_handoff_out`/`prev_camera_movement`/
    `prev_no_cut_to` 传递(V1 `_build_scene_stage_set` 没有这层链式逻辑——V2 的段间承接
    [开场姿态是否咬合上一段收尾/运镜标签是否雷同/禁切清单延续]必须靠这条链,不是各场
    独立生成再机械拼接,G-FINAL 真机验证过这个链式生成机制)。单场失败不拖垮整体,继续
    下一场(同 `_build_scene_stage_set` 的"退回最小可锁草稿"精神)。"""
    scripts = []
    prev_handoff_out = ""
    prev_camera_movement = ""
    prev_no_cut_to: list[str] = []
    for scene in screenplay.scenes:
        script = await generate_scene_script_draft(
            scene=scene,
            design_list=design_list,
            world_bible=world_bible,
            llm=_resolve_llm(),
            prev_handoff_out=prev_handoff_out,
            prev_camera_movement=prev_camera_movement,
            prev_no_cut_to=prev_no_cut_to,
        )
        scripts.append(script)
        if script.segments:
            prev_handoff_out = script.segments[-1].handoff_out
            prev_camera_movement = script.segments[-1].camera_movement
        prev_no_cut_to = script.no_cut_to
    return SceneScriptSet(scripts=scripts)


async def _run_world_bible_lock(work_id: str) -> None:
    """④锁定后自动生成⑤Scene Script 草案(逐场链式 LLM,放后台)。"""
    rec = _WORKS.get(work_id)
    if rec is None:
        return
    try:
        screenplay = Screenplay.model_validate(rec["screenplay"])
        design_list = DesignList.model_validate(rec["design_list"])
        world_bible = WorldBible.model_validate(rec["world_bible"])
        scene_script_set = await _build_scene_script_set(screenplay, design_list, world_bible)
        rec["scene_script"] = scene_script_set.model_dump()
        rec["status"] = "scene_script_draft"
    except Exception as e:
        logger.exception("world-bible 锁定后生成 scene-script 失败: work_id=%s", work_id)
        rec["status"] = "world_bible_lock_failed"
        rec["error"] = str(e)


@router.post("/works/{work_id}/world-bible/lock")
async def lock_world_bible(
    work_id: str,
    body: WorldBible,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    rec = _require_work(work_id, user)
    rec["world_bible"] = body.model_dump()
    rec["locked_through"] = _stage_index("world_bible")
    rec["status"] = "world_bible_locking"
    rec["error"] = None
    background_tasks.add_task(_run_world_bible_lock, work_id)
    return _work_status(rec)


# ── ⑤Scene Script ───────────────────────────────────────────────────────────


async def _run_scene_script_regenerate(work_id: str) -> None:
    """同 `_run_design_list_lock`:逐场链式 LLM 生成放后台跑,场次一多不顶到反向代理超时。"""
    rec = _WORKS.get(work_id)
    if rec is None:
        return
    try:
        screenplay = Screenplay.model_validate(rec["screenplay"])
        design_list = DesignList.model_validate(rec["design_list"])
        world_bible = WorldBible.model_validate(rec["world_bible"])
        scene_script_set = await _build_scene_script_set(screenplay, design_list, world_bible)
        rec["scene_script"] = scene_script_set.model_dump()
        rec["status"] = "scene_script_draft"
    except Exception as e:
        logger.exception("scene-script 后台重新生成失败: work_id=%s", work_id)
        rec["status"] = "scene_script_regenerate_failed"
        rec["error"] = str(e)


@router.post("/works/{work_id}/scene-script")
async def regenerate_scene_script(
    work_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    rec = _require_work(work_id, user)
    _require_stage_ready(rec, "scene_script")
    _rollback_downstream(rec, "scene_script")
    rec["status"] = "scene_script_generating"
    rec["error"] = None
    background_tasks.add_task(_run_scene_script_regenerate, work_id)
    return _work_status(rec)


@router.post("/works/{work_id}/scene-script/lock")
async def lock_scene_script(
    work_id: str, body: SceneScriptSet, user: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    rec = _require_work(work_id, user)
    rec["scene_script"] = body.model_dump()
    rec["locked_through"] = _stage_index("scene_script")
    rec["status"] = "scene_script_locked"
    return _work_status(rec)


# ── V1→V2 原地升级(2026-07-21):逐镜头准备台(INC-001 §A/§G/§I/§L)已整段删除。
# 那套 candidate-confirm 状态机是 V1 专属(shot_preparation.py 的读写就绪门),V2 没有
# 对应的候选确认流程——world_bible/scene_script 各自的 draft→人审编辑→lock 循环本身
# 就是"生成前人工确认"的门,不需要另建一套。soffy 拍板直接删,不保留占位。

# ── ⑤产集 ─────────────────────────────────────────────────────────────────


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
        # INC-004 §4.3:渲染层算出的这一镜实付美元(L4 路由才非 None),原样带进
        # ShotVerdict.cost_usd 落库——三条构造路径都要带上,不只是"正常通过"那条。
        cost_usd = s.get("cost_usd")
        if clip is None or not clip.exists():
            out.append(
                ShotVerdict(
                    shot_index=s["index"],
                    shot_id=sid,
                    passed=False,
                    diagnosis_category="动作",
                    retake_tier="re_roll",
                    cost_usd=cost_usd,
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
                    cost_usd=cost_usd,
                )
            )
            continue
        v = await verdict_shot(
            shot_index=s["index"],
            shot_id=sid,
            clip_path=clip,
            identity_score=s.get("consistency_score"),
            vlm=vlm,
        )
        v.cost_usd = cost_usd
        out.append(v)
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
                    "diagnosis_category, retake_tier, attempt, passed, cost_usd) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11,$12,$13,$14)",
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
                    v.cost_usd,
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
    multichar_chain_log(
        "A",
        "_has_multichar_shots=%s subject3d_views keys=%s (per-char view keys=%s)",
        _has_multichar_shots(shot_list),
        list(subject3d_views.keys()),
        {k: list(v.keys()) for k, v in subject3d_views.items()},
    )

    # INC-003:每场景空景板路径(多角色 img2img 底图画布)。无则渲染层退回中性灰。
    scene_bg_paths: dict[str, str] = {}
    if subject_svc is not None and _has_multichar_shots(shot_list):
        scene_bg_paths = await _resolve_scene_ref_paths(design_list, subject_svc=subject_svc)
    multichar_chain_log("B", "scene_bg_paths keys=%s", list(scene_bg_paths.keys()))

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


async def _run_v2_produce_task(**kwargs: Any) -> None:
    """`run_v2_produce` 的 background-task 外壳——`BackgroundTasks` 不会捕获任务里抛出的
    异常并回写状态(FastAPI 只是把异常打进服务端日志),`run_v2_produce` 自己在"整条流水线
    走不下去"(比如一场戏一个可用段都没有)时会抛 `ProduceV2Error`,不接住的话
    `video_tasks.status` 会永远卡在生成前的旧状态,前端轮询卡死等不到 `failed`。这层
    镜像 `_run_director_via_tongjian` 自己内建的 `except Exception` 兜底,不是重复造轮子——
    `run_v2_produce` 本身保持"该抛就抛"是为了让它自己的单测能直接断言
    `pytest.raises(ProduceV2Error)`,捕获-回写状态是 background task 边界该做的事,两层
    职责分开。"""
    task_id = kwargs["task_id"]
    task_repo = kwargs["task_repo"]
    try:
        await run_v2_produce(**kwargs)
    except Exception as e:
        logger.exception("V2 产集失败: task_id=%s", task_id)
        await task_repo.update_task(
            task_id,
            {
                "status": "failed",
                "error": str(e)[:500],
                "updated_at": datetime.now(UTC).replace(tzinfo=None),
            },
        )


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
    if rec["locked_through"] < _stage_index("scene_script"):
        raise HTTPException(
            status_code=409, detail=f"Scene Script 还没锁定(当前 {rec['status']}),不能产集"
        )
    # V1→V2 原地升级(2026-07-21):V1 §L.2 逐镜头准备台就绪门已删除(见上方"逐镜头准备台"
    # 段落注释)。V2 产集门槛就是 world_bible+scene_script 都锁了,不需要另一套候选确认。

    design_list = DesignList.model_validate(rec["design_list"])
    concept = Concept.model_validate(rec["concept"])
    screenplay = Screenplay.model_validate(rec["screenplay"])
    world_bible = WorldBible.model_validate(rec["world_bible"])
    scene_script_set = SceneScriptSet.model_validate(rec["scene_script"])

    # 每个角色一个不同音色(治"对话也像旁白");用角色名当 key,run_v2_produce 的
    # voice_by_speaker 也是按 speaker(=角色名)查。
    character_voices = _assign_character_voices(design_list)
    # 角色名 → 设计清单锁定的参考图(multirole 生成的角色 canon)。
    subject_ref_paths = await _resolve_subject_ref_paths(design_list, subject_svc=subject_svc)
    # 场景名 → 设计清单锁定的空景板(multirole 生成的 scene_plate_path)。
    scene_ref_paths = await _resolve_scene_ref_paths(design_list, subject_svc=subject_svc)

    # create_task 只用来:建 video_tasks 行 + 预算熔断 + 积分预留(计费一致性)。真正的
    # 生成不走 submit_task/run_task(那条是通用长视频管线 orchestrate_longvideo——把全片
    # 对白拼一条轨、镜头拉伸去填,对白跟画面对不上、看不到说话人,2026-07-14 用户实测
    # 弃用),改成后台跑 run_v2_produce(document-first 多角色 reference-to-video 管线,
    # G-FINAL 真机验证过)。budget_usd 留空不透传(见历史注释:None 会撞下游 Pydantic
    # float 校验)。
    create_kwargs: dict[str, Any] = {
        "topic": concept.theme or rec["material_text"][:200],
        "duration_archetype": concept.duration_archetype,
        "video_provider": "happyhorse_1_1_maas_ref",  # V2 真实调用的 provider,计价按它估
        "audio_provider": "edge_tts",
        "user_id": str(user["id"]),
        "quality_profile": body.quality_profile,
        "aspect_ratio": body.aspect_ratio,
        "style": concept.style or "cinematic",
        "locked_scene_script": rec["scene_script"],
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

    async def _progress_cb(
        stage: str, pct: float, completed: int | None = None, total: int | None = None
    ) -> None:
        await svc.repository.update_task(
            task_id,
            {
                "progress_pct": pct,
                "config_json": {**task.get("config_json", {}), "stage": stage},
                **({"completed_shots": completed} if completed is not None else {}),
                **({"total_shots": total} if total is not None else {}),
            },
        )

    background_tasks.add_task(
        _run_v2_produce_task,
        task_repo=svc.repository,
        task_id=task_id,
        screenplay=screenplay,
        design_list=design_list,
        world_bible=world_bible,
        scene_script_set=scene_script_set,
        subject_ref_paths=subject_ref_paths,
        scene_ref_paths=scene_ref_paths,
        voice_by_speaker=character_voices,
        progress_cb=_progress_cb,
    )

    rec["video_task_id"] = str(task_id)
    rec["status"] = "producing"
    logger.info(
        "director-pipeline work %s → task %s 产集(V2 document-first 管线)", work_id, task_id
    )
    return _work_status(rec)
