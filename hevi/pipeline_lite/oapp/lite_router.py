"""oapp:lite_router —— Lite 管道 HTTP 路由接入层。

只做:收 HTTP 请求 → 组 LiteTaskContext → 调 omodul 编排 → 回 HTTP 响应。
不包含任何业务规则与文件操作。
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException

from hevi.core.workspace import new_task_id
from hevi.pipeline_lite.omodul.omodul_lite_assembler import run_lite_pipeline
from hevi.pipeline_lite.schemas import LiteAssembleResult, LiteCue, LiteTaskContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lite", tags=["lite"])


class LiteAssembleRequest(LiteTaskContext):
    """HTTP 入参:直接复用数据契约,少一层映射就是少一层面条。"""

    task_id: str = ""  # 留空则服务端生成
    audio_path: str | None = None


class LiteAssembleAccepted(LiteAssembleResult):
    """202 受理响应:任务尚未执行, status 允许 pending。"""

    status: Literal["pending", "completed", "failed"] = "pending"


@router.post("/assemble", response_model=LiteAssembleAccepted, status_code=202)
async def assemble_lite(
    body: LiteAssembleRequest,
    background_tasks: BackgroundTasks,
) -> LiteAssembleAccepted:
    """提交一个 Lite 任务,立即 202 + 后台执行。"""
    if not body.task_id:
        body.task_id = new_task_id()
    if not body.cues:
        raise HTTPException(status_code=422, detail="cues 不能为空")
    background_tasks.add_task(_run_background, body.model_copy(deep=True))
    return LiteAssembleAccepted(
        task_id=body.task_id,
        status="pending",
        progress=0,
        decision_trail=[{"stage": "accepted", "outcome": "queued"}],
    )


@router.post("/generate", response_model=LiteAssembleResult, status_code=201)
async def generate_lite_sync(
    body: LiteAssembleRequest,
) -> LiteAssembleResult:
    """同步出片端点:hevi 外部编排(veya 视频可靠性闭环)直连用。

    直接跑完整 Lite 管线并返回 video_path。长任务由 FastAPI 线程池承载;
    失败以 LiteAssembleResult(status="failed", error=...) 返回,不抛 HTTP 5xx。
    """
    if not body.task_id:
        body.task_id = new_task_id()
    if not body.cues:
        raise HTTPException(status_code=422, detail="cues 不能为空")
    ctx = body.model_copy(deep=True)
    # 兜底: 部分调用方只给 topic 不给 cues 时, 生成单镜头全屏卡片。
    if not ctx.cues:
        ctx.cues = [
            LiteCue(index=0, narration=ctx.topic, template="card",
                    props={"title": ctx.topic, "fullscreen": True})
        ]
    try:
        result = await run_lite_pipeline(ctx, audio_path=getattr(ctx, "audio_path", None))
    except Exception as exc:
        logger.exception("lite %s 同步生成崩溃: %s", ctx.task_id, exc)
        return LiteAssembleResult(
            task_id=ctx.task_id, status="failed",
            error=f"lite pipeline raised: {exc}",
            decision_trail=[{"stage": "failed", "outcome": "exception"}],
        )
    return result


async def _run_background(ctx: LiteTaskContext) -> None:
    """后台任务:脱离请求生命周期执行装配;失败只 log,不抛穿。"""
    try:
        result = await run_lite_pipeline(ctx, audio_path=getattr(ctx, "audio_path", None))
        logger.info("lite %s done: %s", ctx.task_id, result.status)
    except Exception as exc:  # pragma: no cover - 防御性兜底
        logger.exception("lite %s 后台任务崩溃: %s", ctx.task_id, exc)


__all__ = ["LiteAssembleRequest", "router"]
