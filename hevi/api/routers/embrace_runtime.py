"""运行时接线 —— 3O 内化能力的 API 出口(3O 内化 Round 3f)。

把 5 项 dramaclaw 内化能力暴露为可调用的运行时端点(Xia 会话 / 候选提升 / 修复计划 /
风格画像 / 草图编辑),让 agent/前端真正能用,而非纯库。会话与池为进程内存(与
shortdrama 的 _RUNS 同模式),必要时可落盘。

全部端点遵循既有路由惯例:auth 依赖 + 直接调服务层;失败给明确 HTTP 状态。
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user
from hevi.director.chat_assistant import XiaAssistant
from hevi.director.promotion import (
    PromotionCandidate,
    PromotionPool,
)
from hevi.director.repair_agents import plan_repair, repair_decision
from hevi.director.sketch_edit import (
    SketchEditOp,
    SketchEditorError,
    apply_sketch_edits,
)
from hevi.style.style_analyzer import (
    analyze_reference_image,
    merge_with_draft,
)
from hevi.verdict.convergence import ConvergenceLog

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/embrace", tags=["embrace"])

#: 进程内存状态(与 shortdrama._RUNS 同模式;重启即失,必要时落盘)。
_CHAT = XiaAssistant()
_CONVERGENCE = ConvergenceLog()
_MAX_REFERENCE_BYTES = 50 * 1024 * 1024


# ── Xia 会话制片助理 ─────────────────────────────────────────────

class ChatRequest(BaseModel):
    project_id: str
    message: str
    failures: list[dict[str, Any]] | None = None


@router.post("/chat")
async def chat(
    body: ChatRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Xia 会话:识别意图(状态/推进/审计/修复/提升/帮助)→ 执行 → 回复骨架。"""
    if not body.project_id.strip() or not body.message.strip():
        raise HTTPException(status_code=422, detail="project_id 与 message 不能为空")
    return _CHAT.handle(body.project_id, body.message, failures=body.failures)


@router.get("/chat/{project_id}")
async def chat_state(
    project_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """会话状态(轮次/意图/项目进度快照)。"""
    return _CHAT.session(project_id).to_dict()


# ── 候选提升双轨 ─────────────────────────────────────────────────

class CandidateIn(BaseModel):
    candidate_id: str
    kind: str
    name: str
    source: str = "generated"
    score: float = 0.0
    score_note: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class PromoteRequest(BaseModel):
    candidate_id: str
    action: str = "promote"  # promote | reject
    reason: str = ""


@router.post("/promote/{project_id}/candidates")
async def add_candidate(
    project_id: str,
    body: CandidateIn,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """登记一个探索候选(进候选池,不自动提升)。"""
    pool = _promotion_pool(project_id)
    try:
        pool.add_candidate(
            PromotionCandidate(
                candidate_id=body.candidate_id,
                kind=body.kind,
                name=body.name,
                source=body.source,
                score=body.score,
                score_note=body.score_note,
                payload=dict(body.payload),
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {"candidate_id": body.candidate_id, "registered": True}


@router.post("/promote/{project_id}/decide")
async def decide_candidate(
    project_id: str,
    body: PromoteRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """提升(过线+无冲突)或驳回(记原因)。"""
    pool = _promotion_pool(project_id)
    if body.action == "reject":
        if not body.reason.strip():
            raise HTTPException(status_code=422, detail="驳回必须给原因")
        return {"rejected": pool.reject(body.candidate_id, body.reason)}
    asset, issues = pool.promote(body.candidate_id)
    if asset is None:
        raise HTTPException(status_code=409, detail="; ".join(issues))
    return {"promoted": asset.asset_id, "kind": asset.kind, "name": asset.name}


@router.get("/promote/{project_id}")
async def promotion_state(
    project_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """候选池 + 主线资产状态。"""
    pool = _promotion_pool(project_id)
    return {
        "candidates": [c.to_dict() for c in pool.candidates],
        "locked": [
            {"kind": a.kind, "name": a.name, "asset_id": a.asset_id}
            for a in pool.locked
        ],
    }


_PROMOTION_POOLS: dict[str, PromotionPool] = {}


def _promotion_pool(project_id: str) -> PromotionPool:
    if project_id not in _PROMOTION_POOLS:
        _PROMOTION_POOLS[project_id] = PromotionPool()
    return _PROMOTION_POOLS[project_id]


# ── 修复计划 ─────────────────────────────────────────────────────

class RepairPlanRequest(BaseModel):
    failures: list[dict[str, Any]]
    budget_limit: int = 3
    episode_num: int = 1


@router.post("/repair-plan")
async def repair_plan_endpoint(
    body: RepairPlanRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """失败清单 → 修复计划(agent 表映射)+ 收敛决策。"""
    if not body.failures:
        raise HTTPException(status_code=422, detail="failures 不能为空")
    plan = plan_repair(body.failures, budget_limit=body.budget_limit)
    decision = repair_decision(plan, _CONVERGENCE, episode_num=body.episode_num)
    return {"plan": plan.to_dict(), "decision": decision}


# ── 风格画像(确定性)─────────────────────────────────────────────

@router.post("/style-analyze")
async def style_analyze_endpoint(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    file: Annotated[UploadFile, File(description="参考图,确定性风格画像")],
) -> dict[str, Any]:
    """参考图 → 确定性风格画像(主色板/亮度/饱和/对比度/暖冷)+ VLM 语言草稿合并。"""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="空文件")
    if len(data) > _MAX_REFERENCE_BYTES:
        raise HTTPException(status_code=413, detail="文件过大(上限 50MB)")
    suffix = Path(file.filename or "").suffix or ".png"
    profile: Any = None
    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
        tmp.write(data)
        tmp.flush()
        tmp_path = Path(tmp.name)
        try:
            profile = analyze_reference_image(tmp_path)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"画像失败: {e}") from e
        # VLM 语言草稿可选合并(本地视觉模型可用时);必须在 tmp 存活期内做
        try:
            from hevi.providers.local_qwen_vl_adapter import vl_model_available

            if vl_model_available():
                from hevi.style.draft_from_reference import draft_style_from_reference

                draft = await draft_style_from_reference(tmp_path, vlm=_vlm_adapter())
                profile = merge_with_draft(profile, draft)
        except Exception as e:
            logger.warning("style-analyze: vlm merge skipped: %s", e)
    result: dict[str, Any] = profile.to_dict()
    result["dominant_color"] = profile.dominant_color
    return result


def _vlm_adapter() -> Any:
    from hevi.providers.local_qwen_vl_adapter import local_qwen_vl_adapter

    return local_qwen_vl_adapter


# ── 草图编辑 ─────────────────────────────────────────────────────

class SketchOpIn(BaseModel):
    op: str
    params: dict[str, Any] = Field(default_factory=dict)
    note: str = ""


class SketchEditRequest(BaseModel):
    ops: list[SketchOpIn]


@router.post("/sketch-edit")
async def sketch_edit_endpoint(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    file: Annotated[UploadFile, File(description="草图图片")],
    ops: Annotated[
        str,
        File(description='JSON: [{"op":"crop","params":{"box":[0,0,40,30]}}, ...]'),
    ],
) -> dict[str, Any]:
    """草图编辑:应用确定性编辑操作(裁切/重构图/灰度/去网格/pose 骨架),返回产物路径。"""
    import json

    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="空文件")
    try:
        ops_data = json.loads(ops)
        ops_parsed = [SketchOpIn(**o) for o in ops_data]
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"ops 不是合法 JSON: {e}") from e
    suffix = Path(file.filename or "").suffix or ".png"
    with tempfile.TemporaryDirectory(prefix="hevi_sketch_") as td:
        src = Path(td) / f"in{suffix}"
        src.write_bytes(data)
        out = Path(td) / f"out{suffix}"
        try:
            result = apply_sketch_edits(
                src,
                out,
                [
                    SketchEditOp(op=o.op, params=dict(o.params), note=o.note)
                    for o in ops_parsed
                ],
            )
        except SketchEditorError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        return result.to_dict()


# ── workflow 端点组(3O 内化 Round 3g: 让 workflow 运行时可用)──────────────

class WorkflowRunRequest(BaseModel):
    """通用 workflow 请求:config/input 以 JSON 透传,由各 workflow 构建 dataclass。"""

    workflow: str
    config: dict[str, Any] = Field(default_factory=dict)
    input_data: dict[str, Any] = Field(default_factory=dict)


@router.post("/workflows/run")
async def run_workflow(
    body: WorkflowRunRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """运行一个内化 workflow(delivery-gate / export-pack / music-to-video /
    story-to-animation / promo-plan / final-review),产 report JSON。

    全部为确定性骨架 + 可选外部工具(ffmpeg/gh/音频),缺工具时优雅降级。
    """
    import tempfile

    with tempfile.TemporaryDirectory(prefix="hevi_wf_") as td:
        out_dir = Path(td)
        result = await _dispatch_workflow(body.workflow, body.config, body.input_data, out_dir)
        if result.get("report_path") and Path(result["report_path"]).exists():
            result["report"] = json.loads(
                Path(result["report_path"]).read_text(encoding="utf-8")
            )
        return result


async def _dispatch_workflow(
    workflow: str, config: dict[str, Any], input_data: dict[str, Any], out_dir: Path
) -> dict[str, Any]:
    from hevi.assembly.export_pack_workflow import (
        ExportPackConfig,
        ExportPackInput,
        export_pack_workflow,
    )
    from hevi.assembly.music_to_video_workflow import (
        MusicVideoConfig,
        MusicVideoInput,
        music_to_video_workflow,
    )
    from hevi.assembly.promo_video_workflow import (
        PromoConfig,
        PromoInput,
        promo_video_workflow,
    )
    from hevi.assembly.story_to_animation_workflow import (
        StoryConfig,
        StoryInput,
        story_to_animation_workflow,
    )
    from hevi.verdict.delivery_gate import run_delivery_gate
    from hevi.verdict.final_review import run_final_review

    if workflow == "delivery-gate":
        video = Path(config["video_path"])
        gate = await __import__("asyncio").to_thread(
            run_delivery_gate,
            video,
            out_dir=out_dir,
            bgm_path=Path(config["bgm_path"]) if config.get("bgm_path") else None,
        )
        return {
            "status": "completed",
            "passed": gate.passed,
            "items": [i.__dict__ for i in gate.items],
            "contact_sheet": str(gate.contact_sheet_path) if gate.contact_sheet_path else None,
        }
    if workflow == "export-pack":
        export_cfg = ExportPackConfig(
            out_dir=out_dir,
            project_name=config["project_name"],
            episode_no=int(config.get("episode_no", 1)),
            zip_path=Path(config["zip_path"]),
        )
        export_inp = ExportPackInput(
            video=Path(config["video_path"]) if config.get("video_path") else None,
            srt=Path(config["srt_path"]) if config.get("srt_path") else None,
            stylepack_ref=config.get("stylepack_ref", ""),
        )
        return await export_pack_workflow(export_cfg, export_inp, out_dir)
    if workflow == "music-to-video":
        music_cfg = MusicVideoConfig(
            audio_path=Path(config["audio_path"]),
            out_path=Path(config.get("out_path", "out.mp4")),
            mode=config.get("mode", "lyrics"),
            fps=int(config.get("fps", 30)),
        )
        music_inp = MusicVideoInput(lyrics=list(config.get("lyrics", [])))
        return await music_to_video_workflow(music_cfg, music_inp, out_dir)
    if workflow == "story-to-animation":
        story_cfg = StoryConfig(
            out_path=Path(config.get("out_path", "out.mp4")),
            mode=config.get("mode", "plan"),
            transition=config.get("transition", "cut"),
        )
        story_inp = StoryInput(
            text=config.get("text", ""),
            images=[Path(i) for i in config.get("images", [])],
        )
        return await story_to_animation_workflow(story_cfg, story_inp, out_dir)
    if workflow == "promo-plan":
        promo_cfg = PromoConfig(
            product_name=config["product_name"],
            target_duration_s=float(config.get("target_duration_s", 30.0)),
            energy_axis=float(config.get("energy_axis", 0.0)),
            tone_axis=float(config.get("tone_axis", 0.0)),
            features=list(config.get("features", [])),
        )
        promo_inp = PromoInput(page_url=config.get("page_url", ""))
        return await promo_video_workflow(promo_cfg, promo_inp, out_dir)
    if workflow == "final-review":
        inputs_present = {k: bool(v) for k, v in input_data.get("inputs", {}).items()}
        result = run_final_review(
            inputs_present,
            verdicts=input_data.get("verdicts"),
            conflicts=input_data.get("conflicts"),
        )
        return {"status": "completed", "review": result.to_dict()}
    raise HTTPException(status_code=422, detail=f"unknown workflow {workflow!r}")
