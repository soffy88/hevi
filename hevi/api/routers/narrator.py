"""Narrator AI CLI 代理。无 CLI/key 时返回 503,不编造片库。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from hevi.narrator.client import ALLOWED, NarratorUnavailable, narrator_status, run_narrator

router = APIRouter(prefix="/narrator", tags=["narrator"])


class RunRequest(BaseModel):
    verb: str
    extra: list[str] = Field(default_factory=list, max_length=8)


@router.get("/status")
def status() -> dict[str, Any]:
    return narrator_status()


@router.post("/run")
def run(body: RunRequest) -> dict[str, Any]:
    if body.verb not in ALLOWED:
        raise HTTPException(status_code=400, detail=f"verb 不在白名单: {sorted(ALLOWED)}")
    try:
        return run_narrator(body.verb, body.extra)
    except NarratorUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
