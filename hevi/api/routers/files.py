"""通用文件代理 — GET /api/files?path=... (inline 播放/下载)。

复用 hevi.api.routers.studio 的产物解析规则 (_resolve_artifact):
只允许部署产物根目录 (output/assets/data 等) 下、后缀白名单内的文件,
解析后必须仍在根内, 否则 403/404/415。

鉴权与 /api/studio/artifacts/download 同款: Authorization Bearer 头
或 ?token= 查询参数 (<video>/<a> 发不出请求头时用), 无有效 token → 401。
与 download 端点的区别: 本端点 inline 返回 (不设 attachment), 供
<video src> 直接播放; download 端点强制附件下载。
"""

from __future__ import annotations

import mimetypes
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from hevi.api.routers.studio import _resolve_artifact
from hevi.auth.jwt_handler import decode_access_token

router = APIRouter(tags=["files"])

_optional_bearer = HTTPBearer(auto_error=False)


@router.get("/files")
async def serve_file(
    path: str = Query(min_length=1, description="容器内产物绝对路径"),
    token: str | None = Query(default=None, description="JWT(供 <video>/<a> 用)"),
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer)] = None,
) -> FileResponse:
    """Serve a produced artifact inline for browser playback/download."""
    raw = credentials.credentials if credentials is not None else token
    if not raw:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        payload = decode_access_token(raw)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
    if not payload.get("sub"):
        raise HTTPException(status_code=401, detail="Invalid token: missing sub")
    resolved = _resolve_artifact(path)
    media_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
    return FileResponse(str(resolved), media_type=media_type, filename=resolved.name)
