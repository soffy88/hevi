"""TaskService adapters for the durable Video Intelligence runtime.

These functions are adapter composition only.  Queueing, leases, retries and
terminal task transitions remain owned by ``TaskService``.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from pathlib import Path
from typing import Any

from obase.persistence import PgPool

from hevi.artifact_store import ArtifactRepository, get_object_store
from hevi.production.artifacts import Artifact, ArtifactManifest
from hevi.providers.registry import ProviderRegistry
from hevi.sourcing.loader_bridge import AssetRepository
from hevi.verdict.case_dimensions import evaluate_case_artifact, persist_case_verdict

from .analysis import analyze_reel
from .case_analysis import CaseAnalysis, analyze_case
from .case_repository import CaseRepository
from .reproduction import ReproductionMode, build_reproduction_plan
from .runtime_repository import CaseAnalysisRepository, CaseReproductionRepository


def _asset_path(asset: dict[str, Any]) -> Path:
    data = dict(asset.get("data") or {})
    raw = data.get("path") or data.get("local_path")
    if not raw and str(data.get("uri") or "").startswith("file://"):
        raw = str(data["uri"])[7:]
    if not raw:
        raise RuntimeError("CASE_SOURCE_ASSET_HAS_NO_LOCAL_PATH")
    path = Path(str(raw))
    if not path.is_file():
        raise RuntimeError("CASE_SOURCE_ASSET_LOCAL_FILE_MISSING")
    return path


async def execute_case_analysis_task(task: dict[str, Any], pool: PgPool) -> dict[str, Any]:
    config = dict(task.get("config_json") or {})
    user_id = str(task.get("user_id") or config.get("user_id") or "")
    case_id = str(config.get("case_id") or "")
    analysis_id = str(config.get("analysis_id") or "")
    case_repo = CaseRepository(pool)
    analysis_repo = CaseAnalysisRepository(pool)
    case = await case_repo.get_owned(case_id, user_id=user_id)
    if case is None:
        raise RuntimeError("CASE_NOT_FOUND_OR_NOT_OWNED")
    record = await analysis_repo.get_owned(analysis_id, user_id=user_id)
    if record is None:
        raise RuntimeError("CASE_ANALYSIS_NOT_FOUND_OR_NOT_OWNED")
    if record.get("status") == "succeeded" and record.get("analysis_json"):
        return {
            "status": "completed", "domain_only": True,
            "config_json": {**config, "analysis_id": analysis_id, "analysis_status": "succeeded"},
        }
    await analysis_repo.mark_running(analysis_id, user_id=user_id)
    await case_repo.update_owned(
        case_id, user_id=user_id, changes={"analysis_status": "running"}
    )
    try:
        asset_id = case.original_video_asset_id
        if not asset_id:
            raise RuntimeError("CASE_SOURCE_ASSET_REQUIRED")
        asset = await AssetRepository(pool).get_for_user(asset_id, user_id=user_id)
        if asset is None:
            raise RuntimeError("CASE_SOURCE_ASSET_NOT_FOUND_OR_NOT_OWNED")
        reel = await asyncio.to_thread(analyze_reel, _asset_path(asset))
        analysis = analyze_case(case, reel)
        # Keep the durable request identity as the analysis identity.  The
        # source observer id remains provenance inside the serialized result.
        analysis = analysis.model_copy(update={"analysis_id": analysis_id})
        if not await analysis_repo.succeed(analysis_id, user_id=user_id, analysis=analysis):
            raise RuntimeError("CASE_ANALYSIS_RESULT_COMMIT_LOST")
        await case_repo.update_owned(
            case_id,
            user_id=user_id,
            changes={
                "analysis_status": "completed",
                "duration_ms": reel.video_probe.duration_ms,
                "width": reel.video_probe.width,
                "height": reel.video_probe.height,
                "fps": (
                    reel.video_probe.fps_num / reel.video_probe.fps_den
                    if reel.video_probe.fps_num and reel.video_probe.fps_den
                    else None
                ),
                "shots_json": [item.model_dump(mode="json") for item in analysis.case_shots],
            },
        )
        return {
            "status": "completed",
            "domain_only": True,
            "config_json": {**config, "analysis_id": analysis_id, "analysis_status": "succeeded"},
        }
    except Exception as exc:
        await analysis_repo.fail(analysis_id, user_id=user_id, reason=str(exc))
        await case_repo.update_owned(
            case_id, user_id=user_id, changes={"analysis_status": "failed"}
        )
        return {"status": "failed", "error": str(exc), "config_json": config}


async def _call_video_provider(
    *, provider: str, prompt: str, output_path: Path, parameters: dict[str, Any],
    idempotency_key: str,
) -> Any:
    caller = ProviderRegistry.get().generic("video", provider)
    request = {
        "prompt": prompt,
        "output_path": output_path,
        "mode": parameters.get("mode", "t2v"),
        "duration_s": float(parameters.get("duration_s", 5.0)),
        "width": parameters.get("width"),
        "height": parameters.get("height"),
        "seed": parameters.get("seed"),
        "config": {**parameters, "idempotency_key": idempotency_key},
        "idempotency_key": idempotency_key,
    }
    value = caller(**{key: val for key, val in request.items() if val is not None})
    return await value if inspect.isawaitable(value) else value


async def execute_case_reproduction_task(task: dict[str, Any], pool: PgPool) -> dict[str, Any]:
    config = dict(task.get("config_json") or {})
    user_id = str(task.get("user_id") or config.get("user_id") or "")
    case_id = str(config.get("case_id") or "")
    reproduction_id = str(config.get("reproduction_id") or "")
    repo = CaseReproductionRepository(pool)
    case = await CaseRepository(pool).get_owned(case_id, user_id=user_id)
    record = await repo.get_owned(reproduction_id, user_id=user_id)
    if case is None or record is None:
        raise RuntimeError("CASE_REPRODUCTION_NOT_FOUND_OR_NOT_OWNED")
    asset_repo = AssetRepository(pool)
    if record.get("output_asset_id") and record.get("verdict_id"):
        existing_asset = await asset_repo.get_for_user(
            str(record["output_asset_id"]), user_id=user_id
        )
        if existing_asset is not None:
            existing_path = _asset_path(existing_asset)
            return {
                "status": "completed", "result_video_path": str(existing_path),
                "config_json": {**config, "reproduction_id": reproduction_id,
                                "verdict_id": str(record["verdict_id"])},
            }
    analysis_id = str(config.get("analysis_id") or "")
    analysis_repo = CaseAnalysisRepository(pool)
    analysis_row = await analysis_repo.get_owned(analysis_id, user_id=user_id)
    if not analysis_row or not analysis_row.get("analysis_json"):
        await repo.fail(
            reproduction_id, user_id=user_id, failure_code="ANALYSIS_REQUIRED",
            failure_detail="a succeeded CaseAnalysis is required before reproduction",
        )
        return {"status": "failed", "error": "ANALYSIS_REQUIRED", "config_json": config}
    await repo.mark_running(reproduction_id, user_id=user_id)
    provider = str(record["provider_id"])
    model = str(record["model_id"])
    plan = build_reproduction_plan(
        case,
        CaseAnalysis.model_validate(analysis_row["analysis_json"]),
        provider=provider,
        model=model,
        mode=ReproductionMode(str(record["generation_mode"])),
        generation_parameters=dict(record.get("generation_parameters") or {}),
    )
    if not await repo.update_plan(
        reproduction_id, user_id=user_id, compiled_prompt=plan.compiled_prompt,
        reference_bindings=[item.model_dump(mode="json") for item in plan.reference_bindings],
        parameters=plan.generation_parameters,
    ):
        raise RuntimeError("CASE_REPRODUCTION_PLAN_COMMIT_LOST")
    output_dir = Path("output/case_reproductions") / reproduction_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "reproduction.mp4"
    started = time.monotonic()
    try:
        # The output location is deterministic for the reproduction intent.
        # If a worker died after a synchronous provider wrote the file, a
        # redelivery resumes from that durable side effect instead of calling
        # the provider a second time.
        value: Any = {}
        if output_path.is_file():
            produced = output_path
        else:
            prompt: Any = plan.compiled_prompt
            if provider == "h3_local":
                prompt = {"integrated_multimodal_description": plan.compiled_prompt}
            value = await _call_video_provider(
                provider=provider,
                prompt=prompt if isinstance(prompt, str) else str(prompt.get("integrated_multimodal_description", "")),
                output_path=output_path,
                parameters=plan.generation_parameters,
                idempotency_key=str(record["idempotency_key"]),
            )
            raw_produced = value.get("path") or value.get("output_path") if isinstance(value, dict) else value
            if not raw_produced:
                raise RuntimeError("PROVIDER_OUTPUT_PATH_MISSING")
            produced = Path(str(raw_produced))
        if not produced.is_file():
            raise RuntimeError("PROVIDER_OUTPUT_MISSING")
        cost_amount = float(value.get("cost", 0.0)) if isinstance(value, dict) else 0.0
        # Canonical artifact persistence happens before the AssetRepository
        # projection.  The outer TaskService lifecycle verifies/commits the
        # same manifest again idempotently.
        manifest = ArtifactManifest(
            production_id=str((task.get("config_json") or {}).get("production_id") or task["id"]),
            revision_id=str(task.get("_canonical_revision_id") or (task.get("config_json") or {}).get("revision_id") or "") or None,
            attempt_id=str(task.get("_attempt_id") or task["id"]),
            tenant_id=user_id,
            artifacts=[Artifact.from_path(produced, kind="video", media_type="video/mp4", primary=True, logical_role="case_reproduction")],
        )
        committed = await ArtifactRepository(pool, get_object_store()).commit(manifest)
        artifact = committed.artifacts[0]
        if record.get("output_asset_id"):
            output_asset = await asset_repo.get_for_user(
                str(record["output_asset_id"]), user_id=user_id
            )
            if output_asset is None:
                raise RuntimeError("CASE_OUTPUT_ASSET_NOT_FOUND_OR_NOT_OWNED")
        else:
            output_asset = await asset_repo.create(
                asset_type="scene",
                name=f"case-reproduction-{reproduction_id}",
                data={
                    "path": str(produced), "uri": artifact.uri, "artifact_id": artifact.artifact_id,
                    "sha256": artifact.sha256, "media_type": artifact.media_type,
                    "source_type": "generated", "case_reproduction_id": reproduction_id,
                },
                user_id=user_id,
            )
            if not await repo.record_generated(
                reproduction_id, user_id=user_id, output_asset_id=str(output_asset["id"]),
                latency_ms=(time.monotonic() - started) * 1000,
                cost_amount=cost_amount,
            ):
                raise RuntimeError("CASE_REPRODUCTION_GENERATED_COMMIT_LOST")
        verdict = evaluate_case_artifact(produced)
        verdict_id = await persist_case_verdict(
            pool, task_id=str(task["id"]), provider=provider,
            artifact_path=produced, verdict=verdict,
            attempt=int(record.get("attempt_no") or 1),
        )
        if not await repo.record_verdicted(
            reproduction_id, user_id=user_id, verdict_id=verdict_id
        ):
            raise RuntimeError("CASE_REPRODUCTION_VERDICT_COMMIT_LOST")
        latency_ms = (time.monotonic() - started) * 1000
        if not await repo.succeed(
            reproduction_id, user_id=user_id, output_asset_id=str(output_asset["id"]),
            verdict_id=verdict_id, cost_amount=cost_amount,
            latency_ms=latency_ms,
        ):
            raise RuntimeError("CASE_REPRODUCTION_RESULT_COMMIT_LOST")
        return {
            "status": "completed", "result_video_path": str(produced),
            "config_json": {**config, "reproduction_id": reproduction_id, "verdict_id": verdict_id,
                            "artifact_manifest": committed.model_dump(mode="json"),
                            "quality": {"passed": bool(verdict.get("passed")), "report": verdict}},
        }
    except Exception as exc:
        await repo.fail(
            reproduction_id, user_id=user_id, failure_code=type(exc).__name__,
            failure_detail=str(exc), latency_ms=(time.monotonic() - started) * 1000,
        )
        return {"status": "failed", "error": str(exc), "config_json": config}


__all__ = ["execute_case_analysis_task", "execute_case_reproduction_task"]
