"""Judge API (minimal)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from hevi.judge import run_hard_checks, run_pairwise, run_self_iterate, select_backend

router = APIRouter(prefix="/judge", tags=["judge"])


class HardCheckRequest(BaseModel):
    video_path: str
    expected_duration_s: float | None = None
    subtitle_path: str | None = None


@router.post("/hard-check")
async def hard_check(req: HardCheckRequest) -> dict[str, Any]:
    return run_hard_checks(req.video_path, expected_duration_s=req.expected_duration_s,
                          subtitle_path=req.subtitle_path).to_dict()


class PairwiseRequest(BaseModel):
    video_a: str
    video_b: str
    backend: str | None = None


@router.post("/pairwise")
async def pairwise(req: PairwiseRequest) -> dict[str, Any]:
    b = select_backend(req.backend or "local")
    return run_pairwise(b, req.video_a, req.video_b).to_dict()
