"""OpenShorts execution endpoint with truthful artifact semantics."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user
from hevi.openshorts.omodul import execute_ai_short

router = APIRouter(prefix="/openshorts", tags=["openshorts"])


class AIShortRunRequest(BaseModel):
    run_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,80}$")
    description: str = ""
    url: str = ""
    cost_mode: str = "low_cost"
    with_voiceover: bool = True
    language: str = ""
    voice: str = ""
    voice_engine: str = "native"
    voice_design: str = ""
    voiceover_path: str | None = None
    talking_head_path: str | None = None
    actor_image: str | None = None
    b_roll_paths: list[str] = Field(default_factory=list)
    publish_to: list[str] = Field(default_factory=list)
    estimated_cost_usd: float = Field(default=0.65, ge=0)


@router.post("/ai-short/run")
async def run_ai_short(
    body: AIShortRunRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    run_id = body.run_id or uuid.uuid4().hex
    output_dir = Path("output/openshorts/runs") / run_id
    job = await execute_ai_short(
        description=body.description,
        url=body.url,
        cost_mode=body.cost_mode,
        publish_to=body.publish_to,
        input_data={
            "with_voiceover": body.with_voiceover,
            "language": body.language,
            "voice": body.voice,
            "voice_engine": body.voice_engine,
            "voice_design": body.voice_design,
            "voiceover_path": body.voiceover_path,
            "talking_head_path": body.talking_head_path,
            "actor_image": body.actor_image,
            "b_roll_paths": body.b_roll_paths,
            "estimated_cost_usd": body.estimated_cost_usd,
        },
        output_dir=output_dir,
    )
    return job.model_dump(mode="json")


__all__ = ["router"]
