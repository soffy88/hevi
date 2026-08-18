"""跨平台一键发布路由 —— 列出发布器 + 触发发布(差距 B2)。

- GET  /api/publishers            列出发布器(含可用性探测)
- POST /api/publishers/{platform}/publish  触发发布(服务端路径; 空实现返回
  skipped, 不阻断)
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user
from hevi.publishers import list_publishers, publish_to_platform

router = APIRouter(prefix="/publishers", tags=["publishers"])


class PublishRequest(BaseModel):
    media_path: str = Field(description="服务端成片路径")
    title: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)


@router.get("")
async def get_publishers(
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """列出已注册发布器(含 available 探测)。"""
    items = list_publishers()
    return {"publishers": items, "total": len(items)}


@router.post("/{platform}/publish")
async def trigger_publish(
    platform: str,
    req: PublishRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """触发发布。失败不 raise: 返回 status 为 skipped/failed + reason。"""
    result = await publish_to_platform(
        platform,
        Path(req.media_path),
        title=req.title,
        description=req.description,
        tags=req.tags,
    )
    return result.to_dict()
