import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()  # 标准: 在所有本地 import 之前

from hevi.api.mcp_mount import mount_mcp  # noqa: E402
from hevi.api.routers.audio_library import router as audio_router  # noqa: E402
from hevi.api.routers.auth import router as auth_router  # noqa: E402
from hevi.api.routers.canvas import router as canvas_router  # noqa: E402
from hevi.api.routers.creative import router as creative_router  # noqa: E402
from hevi.api.routers.credits import router as credits_router  # noqa: E402
from hevi.api.routers.director import router as director_router  # noqa: E402
from hevi.api.routers.director_pipeline import router as director_pipeline_router  # noqa: E402
from hevi.api.routers.explainer import router as explainer_router  # noqa: E402
from hevi.api.routers.gallery import router as gallery_router  # noqa: E402
from hevi.api.routers.production_tools import router as production_tools_router
from hevi.api.routers.production_tools_v2 import router as production_tools_v2_router  # noqa: E402
from hevi.api.routers.publish_studio import router as publish_studio_router  # noqa: E402
from hevi.api.routers.pro_studio import router as pro_studio_router  # noqa: E402
from hevi.api.routers.payment import router as payment_router  # noqa: E402
from hevi.api.routers.series import router as series_router  # noqa: E402
from hevi.api.routers.shortdrama import router as shortdrama_router  # noqa: E402
from hevi.api.routers.style import router as style_router  # noqa: E402
from hevi.api.routers.subjects import router as subjects_router  # noqa: E402
from hevi.api.routers.tasks import router as tasks_router  # noqa: E402
from hevi.api.routers.templates import router as templates_router  # noqa: E402
from hevi.api.routers.tongjian import router as tongjian_router  # noqa: E402
from hevi.api.routers.voice_studio import router as voice_studio_router  # noqa: E402
from hevi.api.routers.memory import router as memory_router  # noqa: E402
from hevi.api.routers.providers import router as providers_router  # noqa: E402
from hevi.core.config import settings  # noqa: E402
from hevi.monitoring.middleware import PrometheusMiddleware  # noqa: E402
from hevi.monitoring.router import router as metrics_router  # noqa: E402
from hevi.providers.registry import register_all_providers  # noqa: E402

# Lazy imports for optional modules (services/ai_models may have untested deps)
import logging as _logging
_startup_log = _logging.getLogger("hevi.startup")

ai_models_router = None
try:
    from hevi.api.routers.ai_models import router as ai_models_router  # noqa: E402
except Exception as _e:
    _startup_log.warning("ai_models router skipped: %s", _e)

try:
    from hevi.services import setup_middleware as _setup_middleware  # noqa: E402
except Exception as _e:
    _setup_middleware = None
    _startup_log.warning("services middleware skipped: %s", _e)

try:
    from hevi.ai_models import unified_ai_service  # noqa: E402
except Exception as _e:
    unified_ai_service = None
    _startup_log.warning("ai_models service skipped: %s", _e)


def _cors_list(raw: str) -> list[str]:
    import json as _json

    raw = raw.strip()
    if raw.startswith("["):
        return list(_json.loads(raw))
    return [o.strip() for o in raw.split(",") if o.strip()] or ["*"]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    register_all_providers()  # L-021

    from hevi.credits.account_service import AccountService
    from hevi.credits.billing_service import BillingService
    from hevi.credits.repository import CreditRepository
    from hevi.db.pg_pool import get_hevi_pg_pool
    from hevi.job_queue.worker import QueueWorker
    from hevi.resilience.balance_prober import BalanceProber
    from hevi.tasks.repository import TaskRepository
    from hevi.tasks.task_service import TaskService

    # Initialize microservices (optional, may fail in minimal deployments)
    try:
        from hevi.services import service_registry
        await service_registry.initialize_default_services()
    except Exception as _e:
        service_registry = None
        _startup_log.warning("microservices init skipped: %s", _e)
    
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

    # Cleanup microservices
    try:
        from hevi.services import service_registry as _sr
        cache_service = _sr.get_service('cache_service')
        if cache_service:
            await cache_service.close()
    except Exception:
        pass

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

# Setup microservices middleware (optional)
if _setup_middleware is not None:
    try:
        _setup_middleware(app)
    except Exception as _e:
        _startup_log.warning("microservices middleware skipped: %s", _e)

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
app.include_router(shortdrama_router, prefix="/api")
app.include_router(explainer_router, prefix="/api")
app.include_router(gallery_router, prefix="/api")
app.include_router(production_tools_router, prefix="/api")
app.include_router(production_tools_v2_router, prefix="/api")
app.include_router(publish_studio_router, prefix="/api")
app.include_router(pro_studio_router, prefix="/api")
if ai_models_router is not None:
    app.include_router(ai_models_router, prefix="/api")
app.include_router(memory_router, prefix="/api")
app.include_router(providers_router, prefix="/api")
app.include_router(voice_studio_router, prefix="/api")

# MCP Agent 双入口 — 在 /mcp 暴露 hevi skills (Streamable HTTP transport)
mount_mcp(app)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "6.0.0"}
