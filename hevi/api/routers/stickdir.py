"""火柴人导演线 API —— 提案 + CPU 渲染。

  - POST /api/stickdir/proposal   文案 → 导演提案(proposal.json / proposal.md)
  - POST /api/stickdir/render     提案 → 真实 mp4(CPU)

渲染是 CPU 重活, 用后台线程执行(不阻塞事件循环), 产物落在输出目录。
自包含: 不依赖数据库/鉴权, 便于在无 PG 环境下独立测试。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from hevi.layer4_legacy.stickdir import llm, proposal, render, whitelist

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stickdir", tags=["stickdir"])

#: 输出根目录(相对仓库根)
OUTPUT_ROOT = Path(__file__).resolve().parents[3] / "output" / "stickdir"


class ProposalRequest(BaseModel):
    # ``copy`` 与 BaseModel.copy() 冲突, 用别名暴露
    model_config = ConfigDict(populate_by_name=True)

    text: str = Field(..., min_length=1, alias="copy", description="原始文案")
    aspect: str = Field(..., description="9:16 或 16:9")
    style: str = Field(..., description="1A/1B/2A/2B/3")
    duration: int | None = Field(None, description="30/60/90/120, 缺省 60")
    use_llm: bool = Field(False, description="是否尝试本机 ollama 重写")


class RenderRequest(ProposalRequest):
    fps: int = Field(30, ge=1, le=60)
    burn_subtitles: bool = True
    name: str | None = None


def _build(req: ProposalRequest) -> proposal.Proposal:
    completer = llm.make_completer() if req.use_llm else None
    try:
        return proposal.build_proposal(
            copy=req.text,
            aspect=req.aspect,
            style=req.style,
            duration=req.duration,
            complete=completer,
        )
    except proposal.SetupError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/options")
def options() -> dict[str, Any]:
    """可用画幅/风格/时长/动作白名单(前端下拉用)。"""
    return {
        "aspect": list(whitelist.ASPECT),
        "style": [{"key": k, "name_zh": whitelist.STYLE_NAME[k]} for k in whitelist.STYLE],
        "duration": list(whitelist.DURATIONS),
        "default_duration": whitelist.DEFAULT_DURATION,
        "action": list(whitelist.ACTION),
    }


@router.post("/proposal")
def create_proposal(req: ProposalRequest) -> dict[str, Any]:
    """生成导演提案(不渲染)。"""
    prop = _build(req)
    out_dir = OUTPUT_ROOT / _slug(req)
    jpath, mpath = proposal.write(prop, out_dir)
    return {
        "proposal": prop.data,
        "markdown": prop.markdown,
        "json_path": str(jpath),
        "md_path": str(mpath),
    }


@router.post("/render")
async def render_proposal_endpoint(req: RenderRequest) -> dict[str, Any]:
    """生成提案并 CPU 渲染成 mp4(在线程池里跑, 不阻塞事件循环)。"""
    import anyio

    prop = _build(req)
    out_dir = OUTPUT_ROOT / _slug(req)
    proposal.write(prop, out_dir)
    stem = (
        req.name or f"stickdir_{req.style}_{req.aspect.replace(':', 'x')}_{prop.data['duration']}s"
    )
    out_mp4 = out_dir / f"{stem}.mp4"

    def _do() -> Path:
        return render.render_proposal(
            prop.data, out_mp4, fps=req.fps, burn_subtitles=req.burn_subtitles
        )

    try:
        path = await anyio.to_thread.run_sync(_do)
    except Exception as exc:  # noqa: BLE001 - 渲染失败映射为 500
        logger.exception("stickdir render failed")
        raise HTTPException(status_code=500, detail=f"render failed: {exc}") from exc
    return {
        "mp4_path": str(path),
        "srt_path": str(path.with_suffix(".srt")),
        "proposal_json": str(out_dir / "proposal.json"),
        "self_checks": prop.data["self_checks"],
    }


def _slug(req: ProposalRequest) -> str:
    dur = req.duration or whitelist.DEFAULT_DURATION
    return f"{req.style}_{req.aspect.replace(':', 'x')}_{dur}s"


__all__ = ["OUTPUT_ROOT", "ProposalRequest", "RenderRequest", "router"]
