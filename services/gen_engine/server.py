"""hevi-gen-engine uvicorn 入口 —— 包装上游 voicebox 应用并挂载 /api/ai/*。

镜像布局:
    /app/backend/    <- git 子模块 services/voicebox/backend(上游 voicebox 后端)
    /app/gen_engine/  <- 本文件 + ai_routes.py + tts_worker.py(HEVI 自有)
    /app/frontend/   <- 上游 web UI 构建产物(可选)

上游 backend/app.py 在导入时构造模块级 `app`(FastAPI 实例, 含 lifespan: 模型
加载/卸载、MCP 挂载、SPA 静态托管), 这里以包模块 `backend.app` 导入复用。

⚠️ 路由顺序: 上游 app.py 在构造时已注册 `/{full_path:path}` SPA catch-all,
后加的路由会被它遮蔽, 因此把 /api/ai/* 路由整体挪到路由表最前。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_APP_ROOT = Path(__file__).resolve().parent.parent  # /app
if (_APP_ROOT / "backend" / "app.py").is_file():
    sys.path.insert(0, str(_APP_ROOT))
    # 上游 backend/app.py 模块级构造 `app`(FastAPI 实例)。
    import backend.app as _voicebox_app  # type: ignore[import-not-found]
else:
    logger.warning("未找到 voicebox backend(子模块未检出) — 仅启动 AI 端点")
    from fastapi import FastAPI

    _voicebox_app = type("Empty", (), {"app": FastAPI()})()

from .ai_routes import router as ai_router  # noqa: E402

_ai_route_count = len(ai_router.routes)
_voicebox_app.app.include_router(ai_router, prefix="/api/ai")
# 新版 FastAPI 用惰性 _IncludedRouter 包装(只追加 1 个对象), 不能按"末尾 N 条"
# 重排 —— 按 original_router 精确定位 AI 路由并移到最前, 避免被上游 SPA
# catch-all 遮蔽(否则 /api/ai/health 返回 SPA 页面)。
_ai_router_obj = next(
    (
        r
        for r in _voicebox_app.app.router.routes
        if getattr(r, "original_router", None) is ai_router
    ),
    None,
)
if _ai_router_obj is not None:
    _voicebox_app.app.router.routes.remove(_ai_router_obj)
    _voicebox_app.app.router.routes.insert(0, _ai_router_obj)
logger.info(
    "hevi-gen-engine: 挂载 %d 条 /api/ai/* 路由 (总路由 %d)",
    _ai_route_count,
    len(_voicebox_app.app.router.routes),
)

app = _voicebox_app.app
