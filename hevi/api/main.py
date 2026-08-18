# ruff: noqa: E402, I001
# dotenv must load before application imports; adapters are composed below.
import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()  # 标准: 在所有本地 import 之前

from hevi.api.mcp_mount import mount_mcp
from hevi.api.routers.audio_library import router as audio_router
from hevi.audio.task_adapter import execute_voice_studio_task
from hevi.api.routers.auth import router as auth_router
from hevi.api.routers.backlot import router as backlot_router
from hevi.api.routers.canvas import router as canvas_router
from hevi.api.routers.creative import router as creative_router
from hevi.api.routers.credits import router as credits_router
from hevi.api.routers.dashboard import router as dashboard_router
from hevi.api.routers.director import router as director_router
from hevi.director.graph_render import execute_task as director_graph_task_adapter
from hevi.season_planner.production import execute_shortdrama_task
from hevi.studio.slate import execute_lot_task
from hevi.api.routers.director_pipeline import router as director_pipeline_router
from hevi.api.routers.explainer import (
    execute_task as explainer_task_adapter,
)
from hevi.api.routers.explainer import router as explainer_router
from hevi.api.routers.gallery import router as gallery_router
from hevi.api.routers.cinematic import router as cinematic_router
from hevi.api.routers.history_series import router as history_series_router
from hevi.api.routers.payment import router as payment_router
from hevi.api.routers.pipeline import router as pipeline_router
from hevi.api.routers.pro_studio import router as pro_studio_router
from hevi.api.routers.provider_presets import router as provider_presets_router
from hevi.api.routers.publishers import router as publishers_router
from hevi.api.routers.material_corpus import router as material_corpus_router
from hevi.api.routers.production_tools_v2 import router as production_tools_v2_router
from hevi.api.routers.presenters import router as presenters_router
from hevi.api.routers.series import router as series_router
from hevi.api.routers.shortdrama import router as shortdrama_router
from hevi.api.routers.style import router as style_router
from hevi.api.routers.studio import router as studio_router
from hevi.api.routers.subjects import router as subjects_router
from hevi.api.routers.tasks import router as tasks_router
from hevi.api.routers.templates import router as templates_router
from hevi.api.routers.tongjian import execute_task as tongjian_task_adapter
from hevi.api.routers.tongjian import router as tongjian_router
from hevi.api.routers.freezone import router as freezone_router
from hevi.api.routers.embrace_runtime import router as embrace_router
from hevi.api.routers.lite import router as lite_router
from hevi.api.routers.voice_studio import router as voice_studio_router
from hevi.api.routers.ws import router as ws_router
from hevi.core.config import settings
from hevi.monitoring.middleware import PrometheusMiddleware
from hevi.monitoring.router import router as metrics_router
from hevi.providers.registry import register_all_providers
from hevi.production.adapters import configure_default_adapters

configure_default_adapters(
    director_graph=director_graph_task_adapter,
    explainer=explainer_task_adapter,
    shortdrama=execute_shortdrama_task,
    tongjian=tongjian_task_adapter,
    voice_studio_tts=execute_voice_studio_task,
    lot=execute_lot_task,
)


def _cors_list(raw: str) -> list[str]:
    import json as _json

    raw = raw.strip()
    if raw.startswith("["):
        return list(_json.loads(raw))
    return [o.strip() for o in raw.split(",") if o.strip()] or ["*"]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    register_all_providers()  # L-021

    # v9.1: 任务大盘 SQLite 建表(幂等)。
    from hevi.core.db import init_db

    init_db()

    from hevi.credits.account_service import AccountService
    from hevi.credits.billing_service import BillingService
    from hevi.credits.repository import CreditRepository
    from hevi.db.pg_pool import get_hevi_pg_pool
    from hevi.queue.worker import QueueWorker
    from hevi.resilience.balance_prober import BalanceProber
    from hevi.tasks.repository import TaskRepository
    from hevi.tasks.task_service import TaskService

    pool = await get_hevi_pg_pool()
    repo = TaskRepository(pool)
    billing = BillingService(AccountService(CreditRepository(pool)))
    svc = TaskService(repo, billing_svc=billing)
    worker = QueueWorker(svc, poll_interval=5.0)
    worker_task = asyncio.create_task(worker.run())

    # 余额探针(HEVI 路线图 Phase1 #30):此前 refresh_fal_balance 写了但从没被调度过。
    prober = BalanceProber(poll_interval=3600.0)
    prober_task = asyncio.create_task(prober.run())

    yield

    worker.stop()
    worker_task.cancel()
    with suppress(asyncio.CancelledError):
        await worker_task

    prober.stop()
    prober_task.cancel()
    with suppress(asyncio.CancelledError):
        await prober_task


app = FastAPI(
    title="hevi v6",
    lifespan=lifespan,
    redirect_slashes=False,
)

_cors_origins = _cors_list(settings.cors_origins)
# Wildcard origins + credentials is browser-invalid AND insecure (any site could read
# credentialed responses). When origins are wildcarded, disable credentials.
_cors_allow_credentials = _cors_origins != ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(PrometheusMiddleware)

app.include_router(metrics_router)
app.include_router(auth_router, prefix="/api")
app.include_router(credits_router, prefix="/api")
app.include_router(payment_router, prefix="/api")
app.include_router(pipeline_router, prefix="/api")
app.include_router(pro_studio_router, prefix="/api")
app.include_router(provider_presets_router, prefix="/api")
app.include_router(publishers_router, prefix="/api")
app.include_router(material_corpus_router, prefix="/api")
app.include_router(backlot_router, prefix="/api")
app.include_router(studio_router, prefix="/api")
app.include_router(production_tools_v2_router, prefix="/api")
app.include_router(presenters_router, prefix="/api")
app.include_router(tasks_router, prefix="/api")
app.include_router(subjects_router, prefix="/api")
app.include_router(creative_router, prefix="/api")
app.include_router(canvas_router, prefix="/api")
app.include_router(templates_router, prefix="/api")
app.include_router(audio_router, prefix="/api")
app.include_router(series_router, prefix="/api")
app.include_router(style_router, prefix="/api")
app.include_router(director_router, prefix="/api")
app.include_router(director_pipeline_router, prefix="/api")
app.include_router(tongjian_router, prefix="/api")
app.include_router(cinematic_router, prefix="/api")  # 黄金公式动画演绎
app.include_router(history_series_router, prefix="/api")  # P2 历史现场每日连载
app.include_router(shortdrama_router, prefix="/api")
app.include_router(explainer_router, prefix="/api")
app.include_router(gallery_router, prefix="/api")
app.include_router(voice_studio_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(lite_router, prefix="/api")  # 本地零费用:选题→veya-loop→确认→HTML 出片
app.include_router(ws_router)  # WebSocket 路由自带 /api/ws 前缀
app.include_router(freezone_router, prefix="/api")
app.include_router(embrace_router, prefix="/api")  # 3O 内化运行时(Xia/提升/修复/画像/草图)

# MCP Agent 双入口 — 在 /mcp 暴露 hevi skills (Streamable HTTP transport)
mount_mcp(app)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "6.0.0"}
