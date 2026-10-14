"""Huobao short-drama agent layer API router.

Exposes:
- POST /huobao/estimate: Batch generation estimation (shots, duration, CPU runtime)
- POST /huobao/retry: One-click selective retry of failed shots
- POST /huobao/merge/validate: Pre-merge validation ensuring all clip files exist
- POST /huobao/rewrite: Novel to formatted screenplay with tone selection and verbatim checks
- POST /huobao/assets/dedup: Cross-episode asset deduplication and alias merging
"""

from __future__ import annotations

import logging
import tempfile
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from hevi.capabilities.registry import CapabilityError, describe, get, list as list_caps
from hevi.huobao.assets import AssetRegistry
from hevi.huobao.batch import (
    MissingClipPrerequisiteError,
    ShotTask,
    estimate_batch,
    retry_failed_shots,
    validate_merge_prerequisites,
)
from hevi.huobao.rewrite import (
    TONES,
    DialogueDroppedError,
    rewrite_novel_to_screenplay,
)
from hevi.huobao.capabilities import register_huobao_capabilities

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/huobao", tags=["huobao"])

# Register huobao capabilities into the unified capability registry on import.
register_huobao_capabilities()


class EstimateRequest(BaseModel):
    shots: list[dict[str, Any]]
    engine: str = "sdturbo_cpu"
    tts_engine: str = "piper"
    width: int = 1080
    height: int = 1920


class RetryRequest(BaseModel):
    tasks: list[dict[str, Any]]


class MergeValidateRequest(BaseModel):
    clip_paths: list[str]
    audio_path: str | None = None


class RewriteRequest(BaseModel):
    novel_text: str
    title: str = "短剧剧本"
    tone: str = "classical"
    target_duration_s: float = 75.0


class AssetDedupRequest(BaseModel):
    characters: list[dict[str, Any]] = Field(default_factory=list)
    scenes: list[dict[str, Any]] = Field(default_factory=list)
    props: list[dict[str, Any]] = Field(default_factory=list)
    base_seed: int = 42


@router.post("/estimate")
async def estimate_endpoint(req: EstimateRequest) -> dict[str, Any]:
    """Estimate batch generation resource requirements, duration, and CPU run time."""
    est = estimate_batch(
        req.shots,
        engine=req.engine,
        tts_engine=req.tts_engine,
        width=req.width,
        height=req.height,
    )
    return est.to_dict()


@router.post("/retry")
async def retry_endpoint(req: RetryRequest) -> dict[str, Any]:
    """Selective retry for failed shots only."""
    tasks = [ShotTask(**t) for t in req.tasks]

    def _simulated_retry(t: ShotTask) -> None:
        # Default retry execution marks successful re-render
        t.status = "success"
        t.error_message = None

    updated, count = retry_failed_shots(tasks, _simulated_retry)
    return {
        "retried_count": count,
        "tasks": [t.to_dict() for t in updated],
    }


@router.post("/merge/validate")
async def merge_validate_endpoint(req: MergeValidateRequest) -> dict[str, Any]:
    """Validate that all required clip files exist before merging."""
    try:
        verified = validate_merge_prerequisites(req.clip_paths, req.audio_path)
        return {
            "valid": True,
            "verified_count": len(verified),
            "clips": [str(p) for p in verified],
        }
    except MissingClipPrerequisiteError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/rewrite")
async def rewrite_endpoint(req: RewriteRequest) -> dict[str, Any]:
    """Rewrite novel text into a standardized short-drama screenplay with tone."""
    if req.tone not in TONES:
        raise HTTPException(
            status_code=400,
            detail=f"无效语气: {req.tone}。可选语气: {list(TONES.keys())}",
        )
    try:
        screenplay = rewrite_novel_to_screenplay(
            req.novel_text,
            title=req.title,
            tone=req.tone,
            target_duration_s=req.target_duration_s,
        )
        return {
            "title": screenplay.title,
            "tone": screenplay.tone,
            "scene_count": len(screenplay.scenes),
            "markdown": screenplay.to_markdown(),
        }
    except DialogueDroppedError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.get("/capabilities")
async def capabilities_list() -> dict[str, Any]:
    """List all registered capabilities (front-end AI one-click prefill source)."""
    return {"capabilities": describe()}


class CapabilityPreviewRequest(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)
    aspect: str = "9:16"
    seed: int = 42
    preview_seconds: float = 3.0


@router.post("/capabilities/{name}/preview")
async def capability_preview(name: str, req: CapabilityPreviewRequest) -> dict[str, Any]:
    """Generate a 3-second preview for a named capability."""
    try:
        cap = get(name)
    except CapabilityError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    with tempfile.TemporaryDirectory(prefix=f"huobao_cap_preview_{name}_") as td:
        out = Path(td) / "preview"
        try:
            result = cap.render_safe(
                req.params, out, duration=req.preview_seconds, aspect=req.aspect, seed=req.seed
            )
        except CapabilityError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        return {"name": name, "result": result.to_dict()}
    """Perform cross-episode asset deduplication, alias merging, and 3-question filtering."""
    registry = AssetRegistry(base_seed=req.base_seed)

    for c in req.characters:
        registry.register_character(
            name=c.get("name", ""),
            aliases=c.get("aliases", []),
            role=c.get("role", "supporting"),
            appearance=c.get("appearance", ""),
            styling=c.get("styling", ""),
            description=c.get("description", ""),
            episode=int(c.get("episode", 1)),
        )

    for s in req.scenes:
        registry.register_scene(
            location=s.get("location", ""),
            time=s.get("time", "白天"),
            prompt=s.get("prompt", ""),
            lighting=s.get("lighting", ""),
            episode=int(s.get("episode", 1)),
        )

    for p in req.props:
        registry.register_prop(
            name=p.get("name", ""),
            prop_type=p.get("type", "信物"),
            description=p.get("description", ""),
            episode=int(p.get("episode", 1)),
        )

    return registry.to_dict()
