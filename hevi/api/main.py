from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()  # 标准: 在所有本地 import 之前

from hevi.api.routers.canvas import router as canvas_router  # noqa: E402
from hevi.api.routers.creative import router as creative_router  # noqa: E402
from hevi.api.routers.subjects import router as subjects_router  # noqa: E402
from hevi.api.routers.tasks import router as tasks_router  # noqa: E402
from hevi.monitoring.middleware import PrometheusMiddleware  # noqa: E402
from hevi.monitoring.router import router as metrics_router  # noqa: E402
from hevi.providers.registry import register_all_providers  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    register_all_providers()  # L-021
    yield


app = FastAPI(
    title="hevi v6",
    lifespan=lifespan,
    redirect_slashes=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev; 生产收紧
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(PrometheusMiddleware)

app.include_router(metrics_router)
app.include_router(tasks_router, prefix="/api")
app.include_router(subjects_router, prefix="/api")
app.include_router(creative_router, prefix="/api")
app.include_router(canvas_router, prefix="/api")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "6.0.0"}
