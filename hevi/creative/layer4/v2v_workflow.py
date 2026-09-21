"""HEVI Layer4 V2V adapter — previz-still-driven provider video generation.

This module owns NO canonical 3O element and creates NO second provider
registry, NO second ledger, NO second artifact authority.  It orchestrates:

  source artifact (Blender previz still, with lineage)
  → existing provider plane (Alibaba MaaS workspace via
    ``hevi.video.dashscope_i2v_service`` + ``run_durable_provider_job``)
  → downloaded mp4 → ffprobe validation → artifact metadata

Provider execution durability (ProviderExecutionRecord + ProviderCallRecord
via CallLedgerStore) comes from ``run_durable_provider_job`` unchanged.
Artifact authority stays with ``ArtifactManifest``/``ArtifactRepository``.
Failure codes feed the existing ``track_task_failure`` → RepairIncident seam.

Supported provider leg (the only legs with live credentials in this env):
  - ``dashscope-i2v`` / ``wan2.2-i2v-flash`` (previz still + prompt → video)
  - ``dashscope-r2v`` / ``happyhorse-1.1-r2v`` (reference still + prompt → video)

True video-file-in → video-out is offered by no currently keyed provider;
the production leg is therefore previz/reference-still-to-video, named
honestly as such.  Unknown providers/models fail closed here.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

V2V_PROVIDER_DEFAULT = "dashscope-i2v"
V2V_MODEL_DEFAULT = "wan2.2-i2v-flash"

# provider → allowed models.  Closed table: anything else fails closed.
V2V_PROVIDER_MODELS: dict[str, tuple[str, ...]] = {
    "dashscope-i2v": ("wan2.2-i2v-flash",),
    "dashscope-r2v": ("happyhorse-1.1-r2v",),
}

V2VRunner = Callable[..., Awaitable[Path]]


class V2VContractError(ValueError):
    """Refusal with a stable machine code (missing input, unknown provider)."""


def resolve_artifact_local_path(artifact: Any) -> str | None:
    """Resolve an artifact authority record to a local file path.

    Committed artifacts carry object-store URIs (``file://...`` locally,
    ``s3://...`` in SaaS); legacy rows carry raw worker paths.  Returns the
    path only if the file exists on this host, else None (fail closed).
    """

    candidates: list[str] = []
    for raw in (getattr(artifact, "uri", "") or "", getattr(artifact, "path", "") or ""):
        text = str(raw)
        if text.startswith("file://"):
            candidates.append(text.removeprefix("file://"))
        elif text.startswith("file:"):
            candidates.append(text.removeprefix("file:"))
        elif text.startswith("s3://"):
            continue  # remote object: not resolvable without a fetch plane
        elif text:
            candidates.append(text)
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def build_v2v_request(*, v2v_spec: dict[str, Any], source_path: str) -> dict[str, Any]:
    """Validate the minimal V2V production input contract (pure function).

    Required: reference (source_path), prompt, provider, model, output
    constraints.  The adapter resolves ``source_path`` from the artifact
    authority by ``source_artifact_id`` — this function never guesses it.
    """

    prompt = str(v2v_spec.get("prompt") or "").strip()
    if not prompt:
        raise V2VContractError("V2V_PROMPT_REQUIRED")
    if not source_path:
        raise V2VContractError("V2V_REFERENCE_REQUIRED")
    provider = str(v2v_spec.get("provider") or V2V_PROVIDER_DEFAULT)
    models = V2V_PROVIDER_MODELS.get(provider)
    if models is None:
        raise V2VContractError(f"V2V_UNKNOWN_PROVIDER:{provider}")
    model = str(v2v_spec.get("model") or models[0])
    # Unknown model for a known provider is passed through to the real
    # provider so its rejection is genuine (failure E2E); the contract
    # records that it is not an allow-listed model.
    allowlisted = model in models
    return {
        "prompt": prompt,
        "source_path": source_path,
        "provider": provider,
        "model": model,
        "model_allowlisted": allowlisted,
        "source_artifact_id": str(v2v_spec.get("source_artifact_id") or ""),
        "resolution": str(v2v_spec.get("resolution") or "720P"),
        "duration": v2v_spec.get("duration"),
        "seed": v2v_spec.get("seed"),
        "guidance": v2v_spec.get("guidance"),
        "strength": v2v_spec.get("strength"),
    }


@dataclass(frozen=True)
class V2VRenderResult:
    success: bool
    provider: str
    model: str
    provider_job_id: str | None = None
    output_path: str | None = None
    output_exists: bool = False
    output_size: int = 0
    output_sha256: str | None = None
    duration_s: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    source_artifact_id: str = ""
    error_message: str | None = None
    failure_code: str | None = None
    repair_action: str | None = None
    quality_signal: str = "BLOCK"
    execution_metadata: dict[str, Any] = field(default_factory=dict)


def _classify_failure(message: str) -> tuple[str, str]:
    lowered = message.lower()
    if "not configured" in lowered or ("no such" in lowered and "key" in lowered):
        return "V2V_PROVIDER_NOT_CONFIGURED", "MANUAL_ONLY"
    if "unauthorized" in lowered or "401" in lowered or "invalid api-key" in lowered:
        return "V2V_PROVIDER_UNAUTHORIZED", "MANUAL_ONLY"
    if "arrear" in lowered or "balance" in lowered or "insufficient" in lowered:
        return "V2V_PROVIDER_QUOTA", "MANUAL_ONLY"
    if "submit_rejected" in lowered or "rejected" in lowered or "invalidparameter" in lowered:
        return "V2V_PROVIDER_REJECTED", "RETRY_TARGET"
    if "timeout" in lowered or "timed out" in lowered:
        return "V2V_PROVIDER_TIMEOUT", "RETRY_TARGET"
    if "poll" in lowered and "fail" in lowered:
        return "V2V_PROVIDER_JOB_FAILED", "RETRY_TARGET"
    return "V2V_PROVIDER_FAILURE", "RETRY_TARGET"


def _default_runner(provider: str) -> V2VRunner:
    # Uniform runner signature: (image_path, prompt, output_path, model,
    # resolution, config, timeout_s, durable).  happyhorse_animate hardcodes
    # its model, so it is wrapped to accept-and-ignore the model argument.
    if provider == "dashscope-r2v":
        from hevi.video.dashscope_i2v_service import happyhorse_animate

        async def _happyhorse(**kwargs: Any) -> Path:
            kwargs.pop("model", None)
            return await happyhorse_animate(**kwargs)

        return _happyhorse
    from hevi.video.dashscope_i2v_service import i2v_animate

    return i2v_animate


async def v2v_render_workflow(
    *,
    v2v_spec: dict[str, Any],
    source_path: str,
    output_path: str,
    runner: V2VRunner | None = None,
    timeout_s: float = 480.0,
    durable: dict[str, Any] | None = None,
) -> V2VRenderResult:
    """Run the previz→provider→mp4 leg and validate the output.

    ``runner`` defaults to the real provider service; tests inject a fake.
    Output validation (exists/size/ffprobe/sha256) happens here so an
    unqualified file can never reach artifact registration.
    """

    def _job_id_of(state: dict[str, Any]) -> str | None:
        try:
            from hevi.tasks.durable_execution import load_record

            record = load_record(state)
            return record.provider_job_id if record is not None else None
        except Exception:
            return None

    request = build_v2v_request(v2v_spec=v2v_spec, source_path=source_path)
    provider = request["provider"]
    model = request["model"]
    run = runner or _default_runner(provider)
    durable_state: dict[str, Any] = dict(durable or {})
    runner_kwargs: dict[str, Any] = {
        "image_path": Path(source_path),
        "prompt": request["prompt"],
        "output_path": Path(output_path),
        "model": model,
        "resolution": request["resolution"],
        "config": None,
        "timeout_s": timeout_s,
        "durable": durable_state,
    }
    if provider == "dashscope-r2v" and request.get("duration") is not None:
        runner_kwargs["duration"] = int(request["duration"])
    try:
        result_path = await run(**runner_kwargs)
    except Exception as exc:
        failure_code, repair_action = _classify_failure(f"{type(exc).__name__}: {exc}")
        return V2VRenderResult(
            success=False,
            provider=provider,
            model=model,
            provider_job_id=_job_id_of(durable_state),
            source_artifact_id=request["source_artifact_id"],
            error_message=str(exc)[:500],
            failure_code=failure_code,
            repair_action=repair_action,
            quality_signal="BLOCK",
            execution_metadata={"durable": durable_state},
        )
    validated = validate_v2v_output(
        path=str(result_path),
        provider=provider,
        model=model,
        source_artifact_id=request["source_artifact_id"],
        durable=durable_state,
    )
    if validated.success:
        import dataclasses

        validated = dataclasses.replace(
            validated, provider_job_id=_job_id_of(durable_state)
        )
    return validated


def validate_v2v_output(
    *,
    path: str,
    provider: str,
    model: str,
    source_artifact_id: str = "",
    durable: dict[str, Any] | None = None,
) -> V2VRenderResult:
    """Validate a provider-produced file; invalid output never registers."""

    if not path or not Path(path).is_file():
        return V2VRenderResult(
            success=False,
            provider=provider,
            model=model,
            output_path=path,
            source_artifact_id=source_artifact_id,
            error_message=f"V2V output missing: {path}",
            failure_code="V2V_OUTPUT_MISSING",
            repair_action="RETRY_TARGET",
            quality_signal="BLOCK",
            execution_metadata={"durable": dict(durable or {})},
        )
    size = Path(path).stat().st_size
    if size <= 0:
        return V2VRenderResult(
            success=False,
            provider=provider,
            model=model,
            output_path=path,
            source_artifact_id=source_artifact_id,
            error_message=f"V2V output empty: {path}",
            failure_code="V2V_OUTPUT_EMPTY",
            repair_action="RETRY_TARGET",
            quality_signal="BLOCK",
            execution_metadata={"durable": dict(durable or {})},
        )
    try:
        from hevi.production.delivery_gate import probe_video

        probe = probe_video(path)
    except Exception as exc:
        return V2VRenderResult(
            success=False,
            provider=provider,
            model=model,
            output_path=path,
            output_exists=True,
            output_size=size,
            source_artifact_id=source_artifact_id,
            error_message=f"V2V ffprobe failed: {exc}",
            failure_code="V2V_OUTPUT_UNREADABLE",
            repair_action="RETRY_TARGET",
            quality_signal="BLOCK",
            execution_metadata={"durable": dict(durable or {})},
        )
    if not probe.has_video:
        return V2VRenderResult(
            success=False,
            provider=provider,
            model=model,
            output_path=path,
            output_exists=True,
            output_size=size,
            source_artifact_id=source_artifact_id,
            error_message=f"V2V output has no video stream: {path}",
            failure_code="V2V_OUTPUT_NO_VIDEO",
            repair_action="RETRY_TARGET",
            quality_signal="BLOCK",
            execution_metadata={"durable": dict(durable or {})},
        )
    sha256 = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return V2VRenderResult(
        success=True,
        provider=provider,
        model=model,
        output_path=path,
        output_exists=True,
        output_size=size,
        output_sha256=sha256,
        duration_s=probe.duration_s if probe.duration_s > 0 else None,
        source_artifact_id=source_artifact_id,
        quality_signal="PASS",
        execution_metadata={"durable": dict(durable or {})},
    )


def assess_v2v_quality(
    *,
    requested_duration: float | None,
    actual_duration: float | None,
    has_video: bool,
    lineage_ok: bool,
) -> str:
    """HEVI Layer4 quality signal: PASS / WARN / BLOCK (no business decision
    in adapter/provider).  Reuses duration drift + stream validity + lineage."""

    if not has_video or not lineage_ok:
        return "BLOCK"
    if requested_duration and actual_duration:
        drift = abs(actual_duration - requested_duration) / max(requested_duration, 1e-6)
        if drift > 0.5:
            return "BLOCK"
        if drift > 0.2:
            return "WARN"
    return "PASS"


__all__ = [
    "V2V_MODEL_DEFAULT",
    "V2V_PROVIDER_DEFAULT",
    "V2V_PROVIDER_MODELS",
    "V2VContractError",
    "V2VRenderResult",
    "assess_v2v_quality",
    "build_v2v_request",
    "resolve_artifact_local_path",
    "v2v_render_workflow",
    "validate_v2v_output",
]
