from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()  # 标准: 在所有本地 import 之前

from hevi.providers.registry import register_all_providers  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    register_all_providers()  # L-021
    yield


app = FastAPI(
    title="hevi v6",
    lifespan=lifespan,
    redirect_slashes=False,  # 标准
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev; 生产收紧
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "6.0.0"}
