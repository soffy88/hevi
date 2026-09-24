"""Video Intelligence case boundary.

Wave 1 intentionally ingests evidence only.  Analysis and reproduction are
separate durable operations and are not triggered by this endpoint.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.sourcing.loader_bridge import AssetRepository
from hevi.tasks.repository import TaskRepository
from hevi.tasks.task_service import TaskService
from hevi.video_intelligence.case_models import (
    AssetRef,
    CaseIngestInput,
    DuplicateOutcome,
    ProvenanceRecord,
    ProvenanceStatus,
    VideoCase,
    media_sha256,
)
from hevi.video_intelligence.case_repository import CaseRepository
from hevi.video_intelligence.intelligence_repository import (
    IntelligenceRepository,
    pattern_plan_hash,
)
from hevi.video_intelligence.intelligence_runtime import BENCHMARK_DIMENSIONS
from hevi.video_intelligence.runtime_repository import (
    CaseAnalysisRepository,
    CaseReproductionRepository,
)
from hevi.video_intelligence.ssrf import validate_external_url

router = APIRouter(prefix="/intelligence", tags=["video-intelligence"])


class AnalyzeCaseRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=255)


class ReproduceCaseRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=255)
    provider: str = Field(min_length=1, max_length=128)
    model: str = Field(default="default", min_length=1, max_length=255)
    model_version: str | None = None
    generation_mode: str = "exact_structure"
    analysis_id: str
    workspace_id: str | None = None
    generation_parameters: dict[str, Any] = Field(default_factory=dict)


class BenchmarkCaseRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=255)
    analysis_id: str
    benchmark_providers: list[str] = Field(default_factory=list)
    workspace_id: str | None = None


async def _repo() -> CaseRepository:
    return CaseRepository(await get_hevi_pg_pool())


def _safe_local_media(path: str) -> Path:
    target = Path(path).expanduser().resolve()
    allowed = [Path(item).expanduser().resolve() for item in os.getenv("HEVI_MEDIA_ROOTS", "").split(os.pathsep) if item]
    if not allowed:
        allowed = [Path.cwd().resolve()]
    if not any(target == root or root in target.parents for root in allowed):
        raise HTTPException(status_code=422, detail="local_video_path is outside approved media roots")
    if not target.is_file() or target.stat().st_size <= 0:
        raise HTTPException(status_code=422, detail="local_video_path is missing or empty")
    return target


@router.post("/cases")
async def ingest_case(
    body: CaseIngestInput,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[CaseRepository, Depends(_repo)],
) -> dict[str, Any]:
    user_id = str(user["id"])
    if body.idempotency_key:
        existing = await repo.find_idempotent(user_id=user_id, key=body.idempotency_key)
        if existing:
            return {"case": existing.model_dump(mode="json"), "idempotent_replay": True}
    if not any((body.local_video_path, body.uploaded_asset_id, body.existing_asset_id, body.source_url)):
        raise HTTPException(status_code=422, detail="one media source is required")

    sha256: str | None = None
    asset_id = body.uploaded_asset_id or body.existing_asset_id
    duration_ms = width = height = None
    fps = None
    provenance: list[ProvenanceRecord] = []
    if body.local_video_path:
        target = _safe_local_media(body.local_video_path)
        sha256 = media_sha256(target)
        asset = await AssetRepository(repo.pool).create(
            asset_type="scene",
            name=target.name,
            data={
                "path": str(target),
                "sha256": sha256,
                "media_type": "video/mp4",
                "source_type": "reference",
            },
            user_id=user_id,
        )
        asset_id = str(asset["id"])
        provenance.append(ProvenanceRecord(
            source_type="local_file",
            source_uri=str(target),
            evidence_hash=sha256,
            extraction_method="sha256:file_registration",
            confidence=1.0,
        ))
    elif body.source_url:
        try:
            await validate_external_url(body.source_url)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        provenance.append(ProvenanceRecord(
            source_type="source_url",
            source_uri=body.source_url,
            evidence_hash=body.source_url,
            extraction_method="declared_metadata_only",
            confidence=None,
        ))

    if asset_id and not body.local_video_path:
        owned_asset = await AssetRepository(repo.pool).get_for_user(asset_id, user_id=user_id)
        if owned_asset is None:
            raise HTTPException(status_code=404, detail="media asset not found")

    duplicate = DuplicateOutcome.NEW
    if sha256:
        existing = await repo.find_exact_hash(user_id=user_id, sha256=sha256)
        if existing:
            duplicate = DuplicateOutcome.EXACT_DUPLICATE

    status = ProvenanceStatus.VERIFIED if body.local_video_path else ProvenanceStatus.UNVERIFIED
    case = VideoCase(
        id=str(uuid.uuid4()),
        user_id=user_id,
        title=body.title,
        description=body.description,
        source_url=body.source_url,
        source_platform=body.source_platform,
        source_author=body.source_author,
        provenance_status=status,
        provenance=provenance,
        original_video_asset_id=asset_id,
        original_prompt=body.original_prompt,
        prompt_origin=body.prompt_origin,
        reference_assets=[AssetRef.model_validate(item) for item in body.reference_assets],
        declared_model=body.declared_model,
        declared_model_version=body.declared_model_version,
        rights_status=body.rights_status,
        rights_metadata=body.rights_metadata,
        tags=body.tags,
        duplicate_outcome=duplicate,
        exact_asset_sha256=sha256,
        duration_ms=duration_ms,
        width=width,
        height=height,
        fps=fps,
    )
    stored = await repo.create(case, idempotency_key=body.idempotency_key)
    return {"case": stored.model_dump(mode="json"), "idempotent_replay": False}


@router.get("/cases")
async def list_cases(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[CaseRepository, Depends(_repo)],
    limit: int = 100,
) -> dict[str, Any]:
    cases = await repo.list_owned(user_id=str(user["id"]), limit=limit)
    case_payloads = [case.model_dump(mode="json") for case in cases]
    summaries = await IntelligenceRepository(repo.pool).list_case_summaries(
        user_id=str(user["id"]), case_ids=[case.id for case in cases]
    )
    for payload in case_payloads:
        payload.update(summaries.get(str(payload["id"]), {
            "reproduction_count": 0,
            "latest_reproduction_status": None,
            "latest_verdict_id": None,
        }))
    return {"cases": case_payloads, "total": len(case_payloads)}


@router.get("/cases/{case_id}")
async def get_case(
    case_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[CaseRepository, Depends(_repo)],
) -> dict[str, Any]:
    try:
        case = await repo.get_owned(case_id, user_id=str(user["id"]))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="case not found") from exc
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    return {"case": case.model_dump(mode="json")}


@router.post("/cases/{case_id}/analyze")
async def analyze_case_endpoint(
    case_id: str,
    body: AnalyzeCaseRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[CaseRepository, Depends(_repo)],
) -> dict[str, Any]:
    user_id = str(user["id"])
    case = await repo.get_owned(case_id, user_id=user_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    analysis_repo = CaseAnalysisRepository(repo.pool)
    existing = await analysis_repo.find_idempotent(
        case_id=case_id, user_id=user_id, key=body.idempotency_key
    )
    if existing:
        return {"analysis": existing, "idempotent_replay": True}
    analysis = await analysis_repo.create_pending(
        case_id=case_id, user_id=user_id, key=body.idempotency_key,
        analyzer_version="case-analysis-v1",
    )
    service = TaskService(TaskRepository(repo.pool))
    task = await service.create_task(
        topic=f"case-analysis:{case_id}", duration_archetype="1-5min",
        video_provider="h3_local", audio_provider="vibevoice", user_id=user_id,
        idempotency_key=f"case-analysis:{body.idempotency_key}",
        production_source="case_analysis", case_id=case_id,
        analysis_id=str(analysis["id"]),
    )
    submitted = await service.submit_task(task["id"])
    return {
        "analysis": analysis,
        "task": {"id": str(submitted["id"]), "status": submitted["status"]},
        "idempotent_replay": False,
    }


@router.post("/cases/{case_id}/reproduce")
async def reproduce_case_endpoint(
    case_id: str,
    body: ReproduceCaseRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[CaseRepository, Depends(_repo)],
) -> dict[str, Any]:
    user_id = str(user["id"])
    case = await repo.get_owned(case_id, user_id=user_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    analysis = await CaseAnalysisRepository(repo.pool).get_owned(body.analysis_id, user_id=user_id)
    if not analysis or analysis.get("case_id") != uuid.UUID(case_id):
        raise HTTPException(status_code=422, detail="a case-owned analysis is required")
    if analysis.get("status") != "succeeded":
        raise HTTPException(status_code=409, detail="analysis has not succeeded")
    repro_repo = CaseReproductionRepository(repo.pool)
    existing = await repro_repo.find_idempotent(
        case_id=case_id, user_id=user_id, key=body.idempotency_key
    )
    if existing:
        return {"reproduction": existing, "idempotent_replay": True}
    service = TaskService(TaskRepository(repo.pool))
    task = await service.create_task(
        topic=f"case-reproduction:{case_id}", duration_archetype="1-5min",
        video_provider=body.provider, audio_provider="vibevoice", user_id=user_id,
        idempotency_key=f"case-reproduction:{body.idempotency_key}",
        production_source="case_reproduction", case_id=case_id,
        analysis_id=body.analysis_id,
        provider_id=body.provider, model_id=body.model,
    )
    reproduction = await repro_repo.create_pending(
        case_id=case_id, user_id=user_id, workspace_id=body.workspace_id,
        key=body.idempotency_key, provider_id=body.provider, model_id=body.model,
        model_version=body.model_version, generation_mode=body.generation_mode,
        compiled_prompt=case.original_prompt or "", reference_bindings=[],
        parameters=body.generation_parameters, task_id=str(task["id"]),
    )
    config = dict(task.get("config_json") or {})
    config.update({"reproduction_id": str(reproduction["id"]), "provider_id": body.provider, "model_id": body.model})
    await TaskRepository(repo.pool).update_task(task["id"], {"config_json": config})
    submitted = await service.submit_task(task["id"])
    return {
        "reproduction": reproduction,
        "task": {"id": str(submitted["id"]), "status": submitted["status"]},
        "idempotent_replay": False,
    }


@router.post("/cases/{case_id}/benchmark")
async def benchmark_case_endpoint(
    case_id: str,
    body: BenchmarkCaseRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[CaseRepository, Depends(_repo)],
) -> dict[str, Any]:
    """Submit a benchmark to the existing durable task runtime.

    Provider fan-out is intentionally explicit.  An empty or one-provider
    request is durably recorded as environment-blocked, never as a benchmark
    pass.
    """
    user_id = str(user["id"])
    case = await repo.get_owned(case_id, user_id=user_id)
    analysis = await CaseAnalysisRepository(repo.pool).get_owned(body.analysis_id, user_id=user_id)
    if case is None or not analysis or analysis.get("case_id") != uuid.UUID(case_id):
        raise HTTPException(status_code=404, detail="case or analysis not found")
    analysis_json = dict(analysis.get("analysis_json") or {})
    plan = {
        "case_id": case_id,
        "analysis_revision": str(analysis_json.get("analyzer_version") or "unknown"),
        "generation_mode": "exact_structure",
        "compiled_semantic_intent": case.original_prompt or "",
        "shot_structure": analysis_json.get("case_shots") or [],
        "reference_bindings": analysis_json.get("reference_bindings") or [],
        "duration_ms": case.duration_ms,
        "aspect_ratio": case.aspect_ratio,
        "acceptance_dimensions": list(BENCHMARK_DIMENSIONS),
    }
    ir = IntelligenceRepository(repo.pool)
    plan_row = await ir.create_benchmark_plan(
        user_id=user_id, workspace_id=body.workspace_id, case_id=case_id,
        analysis_revision=str(plan["analysis_revision"]), plan=plan, plan_hash=pattern_plan_hash(plan),
    )
    benchmark = await ir.create_benchmark(
        user_id=user_id, workspace_id=body.workspace_id, case_id=case_id,
        plan_id=str(plan_row["id"]), key=body.idempotency_key,
    )
    service = TaskService(TaskRepository(repo.pool))
    task = await service.create_task(
        topic=f"case-benchmark:{case_id}", duration_archetype="1-5min",
        video_provider="benchmark", audio_provider="vibevoice", user_id=user_id,
        idempotency_key=f"case-benchmark:{body.idempotency_key}",
        production_source="case_benchmark", case_id=case_id, analysis_id=body.analysis_id,
        benchmark_id=str(benchmark["id"]), benchmark_providers=body.benchmark_providers,
        workspace_id=body.workspace_id,
    )
    submitted = await service.submit_task(task["id"])
    return {"benchmark": benchmark, "task": {"id": str(submitted["id"]), "status": submitted["status"]}}


@router.get("/benchmarks")
async def list_benchmarks(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[CaseRepository, Depends(_repo)],
    limit: int = 100,
) -> dict[str, Any]:
    rows = await IntelligenceRepository(repo.pool).list_benchmarks(
        user_id=str(user["id"]), limit=limit
    )
    return {"benchmarks": jsonable_encoder(rows), "total": len(rows)}


@router.get("/benchmarks/{benchmark_id}")
async def get_benchmark(
    benchmark_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[CaseRepository, Depends(_repo)],
) -> dict[str, Any]:
    row = await IntelligenceRepository(repo.pool).get_benchmark(
        benchmark_id, user_id=str(user["id"])
    )
    if row is None:
        raise HTTPException(status_code=404, detail="benchmark not found")
    return {"benchmark": jsonable_encoder(row)}


@router.get("/patterns")
async def list_patterns(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[CaseRepository, Depends(_repo)],
    limit: int = 100,
) -> dict[str, Any]:
    rows = await IntelligenceRepository(repo.pool).list_patterns(
        user_id=str(user["id"]), limit=limit
    )
    return {"patterns": jsonable_encoder(rows), "total": len(rows)}


@router.get("/patterns/{pattern_id}")
async def get_pattern(
    pattern_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[CaseRepository, Depends(_repo)],
) -> dict[str, Any]:
    row = await IntelligenceRepository(repo.pool).get_pattern(
        pattern_id, user_id=str(user["id"])
    )
    if row is None:
        raise HTTPException(status_code=404, detail="pattern not found")
    return {"pattern": jsonable_encoder(row)}


@router.get("/templates")
async def list_templates(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[CaseRepository, Depends(_repo)],
    limit: int = 100,
) -> dict[str, Any]:
    rows = await IntelligenceRepository(repo.pool).list_templates(
        user_id=str(user["id"]), limit=limit
    )
    return {"templates": jsonable_encoder(rows), "total": len(rows)}


@router.get("/templates/{template_id}")
async def get_template(
    template_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[CaseRepository, Depends(_repo)],
) -> dict[str, Any]:
    row = await IntelligenceRepository(repo.pool).get_template(
        template_id, user_id=str(user["id"])
    )
    if row is None:
        raise HTTPException(status_code=404, detail="template not found")
    return {"template": jsonable_encoder(row)}


__all__ = ["router"]
