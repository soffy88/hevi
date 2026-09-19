"""Declarative endpoint real execution (Gap Closure W12).

W5 proved definitions can be declared, validated, previewed, and
admitted. This module proves a definition can *drive* a production run:
validate state, admit capability, submit over real HTTP, poll to a
terminal state, download artifact bytes, record usage evidence, register
a manifest entry, and resolve a presentation selection — with secrets
resolved at call time from a caller-supplied mapping, never stored in
the definition.

3O placement decision (explicit): this executor stays HEVI Layer4. The
single HTTP submit/poll/fetch primitives are httpx calls shaped by W5
extraction paths, but the orchestration (W3 records, W4 usage, manifest,
presentation) is HEVI-specific assembly, not a cross-project reusable
unit. No new canonical OPRIM/OBASE asset is created for the audit's
sake; if a second project needs it, extraction starts here.

The executor never touches databases or task rows: persistence is the
caller's job (W11 methods). Reports carry everything needed to persist.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from hevi.creative.layer4.endpoint_lifecycle import (
    AdmissionVerdict,
    CapabilityRequirement,
    DeclarativeEndpointDefinition,
    EndpointError,
    EndpointState,
    check_capability,
    preview_request,
    preview_result,
    resolve_secret_reference,
    validate_definition,
)
from hevi.creative.layer4.presentation import snapshot_for_serving
from hevi.creative.layer4.provider_execution import (
    ProviderExecutionRecord,
    apply_download_complete,
    apply_download_progress,
    apply_poll_failure,
    apply_poll_success,
    decide_next_action,
    guarded_submit,
    intent_fingerprint,
    new_record,
)
from hevi.creative.layer4.usage_ledger import begin_call, complete_call, fail_call
from hevi.production.artifacts import Artifact, ArtifactManifest


class EndpointExecutionError(ValueError):
    """Refusal or runtime failure with a stable machine code."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class ExecutionReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    test_only: bool = False
    submitted: bool = False
    polls_used: int = 0
    terminal_status: str = ""
    provider_job_id: str | None = None
    artifact_local_path: str | None = None
    artifact_sha256: str | None = None
    bytes_downloaded: int = 0
    fingerprint: str = ""
    execution_record: dict[str, Any] = Field(default_factory=dict)
    call_record: dict[str, Any] = Field(default_factory=dict)
    manifest: dict[str, Any] = Field(default_factory=dict)
    presentation: dict[str, Any] = Field(default_factory=dict)
    completed_at: str = ""


def _resolve_headers(
    definition: DeclarativeEndpointDefinition, secrets: dict[str, str]
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for header, value in definition.headers_template.items():
        try:
            resolved[header] = resolve_secret_reference(value, secrets)
        except EndpointError as exc:
            if "ENDPOINT_VALUE_IS_NOT_A_SECRET_REFERENCE" in str(exc):
                resolved[header] = value
            else:
                raise EndpointExecutionError(str(exc)) from exc
    return resolved


def _requirement_from_params(
    definition: DeclarativeEndpointDefinition, params: dict[str, Any]
) -> CapabilityRequirement:
    references = params.get("reference_images") or params.get("references") or []
    return CapabilityRequirement(
        media_type=definition.capability.media_type,
        duration_s=params.get("duration_s"),
        resolution=params.get("resolution"),
        references=len(references) if isinstance(references, (list, tuple)) else 0,
        start_end_frame=bool(params.get("start_frame") or params.get("end_frame")),
        native_audio=bool(params.get("native_audio")),
        async_job=definition.capability.async_job,
    )


def execute_endpoint(
    definition: DeclarativeEndpointDefinition,
    params: dict[str, Any],
    secrets: dict[str, str],
    out_dir: str | Path,
    *,
    test_only: bool = False,
    max_polls: int = 30,
    timeout_s: float = 30.0,
    project_ref: str = "endpoint-smoke",
    operation_type: str = "video_generate",
    task_ref: str = "",
    existing_record: ProviderExecutionRecord | None = None,
) -> ExecutionReport:
    """Run one declarative endpoint end to end over real HTTP."""

    if test_only:
        if definition.state is not EndpointState.TESTED:
            raise EndpointExecutionError("ENDPOINT_TRIAL_REQUIRES_TESTED")
    elif definition.state is not EndpointState.ENABLED:
        raise EndpointExecutionError(f"ENDPOINT_NOT_ENABLED:{definition.state.value}")
    report = validate_definition(definition)
    if not report.valid:
        raise EndpointExecutionError(
            "ENDPOINT_VALIDATION_FAILED:" + ",".join(f.code for f in report.findings if f.blocking)
        )
    verdict: AdmissionVerdict = check_capability(
        definition, _requirement_from_params(definition, params)
    )
    if not verdict.admitted:
        raise EndpointExecutionError("ENDPOINT_ADMISSION_BLOCKED:" + ";".join(verdict.reasons))

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    planned = preview_request(definition, params)
    headers = _resolve_headers(definition, secrets)
    fingerprint = intent_fingerprint(
        provider=definition.provider_family,
        endpoint=definition.name,
        request=planned.body,
        production_revision=params.get("production_revision", "rev-1"),
        target_artifact_id=params.get("target_artifact_id", definition.name),
    )
    call = begin_call(
        project_ref=project_ref,
        provider=definition.provider_family,
        model=definition.name,
        operation_type=operation_type,
        request_summary=f"endpoint {definition.name} v{definition.version}",
        endpoint=planned.url,
        task_ref=task_ref,
    )
    record = existing_record
    submitted = False
    if record is None:
        record = new_record(
            provider=definition.provider_family,
            endpoint=definition.name,
            model=definition.name,
            request=planned.body,
            production_revision=params.get("production_revision", "rev-1"),
            target_artifact_id=params.get("target_artifact_id", definition.name),
            idempotency_key=params.get("idempotency_key", fingerprint[:32]),
        )
        record, submitted = guarded_submit(record, set())
    elif record.provider_job_id is None and not record.remote_finished:
        record, submitted = guarded_submit(record, set())

    polls_used = 0
    terminal_status = ""
    artifact_bytes = b""
    try:
        with httpx.Client(timeout=timeout_s) as client:
            if record.provider_job_id is None:
                response = client.request(
                    planned.method, planned.url, headers=headers, json=planned.body
                )
                response.raise_for_status()
                submit_view = preview_result(definition, response.json())
                if definition.sync_mode.value == "sync":
                    artifact_url = submit_view.artifact_url
                    terminal_status = submit_view.status or "succeeded"
                    record = apply_poll_success(
                        record,
                        remote_artifact_url=artifact_url,
                        provider_terminal_state="succeeded",
                    )
                else:
                    if not submit_view.job_id:
                        raise EndpointExecutionError("ENDPOINT_SUBMIT_RETURNED_NO_JOB_ID")
                    record = record.touch(provider_job_id=submit_view.job_id)
            if definition.sync_mode.value != "sync" and not record.remote_finished:
                poll_url = definition.poll_path_template.replace(
                    "{{job_id}}", record.provider_job_id or ""
                )
                while polls_used < max_polls:
                    response = client.get(poll_url, headers=headers)
                    response.raise_for_status()
                    poll_view = preview_result(definition, response.json())
                    polls_used += 1
                    status = poll_view.status or ""
                    if status in definition.success_states:
                        record = apply_poll_success(
                            record,
                            remote_artifact_url=poll_view.artifact_url,
                            provider_terminal_state=status,
                        )
                        terminal_status = status
                        break
                    if status in definition.failure_states:
                        record = apply_poll_failure(
                            record,
                            terminal=True,
                            error=poll_view.error_message or poll_view.error_code or status,
                        )
                        raise EndpointExecutionError(f"ENDPOINT_REMOTE_FAILED:{status}")
                else:
                    raise EndpointExecutionError("ENDPOINT_POLL_BUDGET_EXCEEDED")
                if not record.remote_finished:
                    raise EndpointExecutionError("ENDPOINT_POLL_BUDGET_EXCEEDED")
            location = record.remote_artifact_url or record.remote_artifact_ref or ""
            if not location:
                raise EndpointExecutionError("ENDPOINT_NO_ARTIFACT_LOCATION")
            with client.stream("GET", location, headers=headers) as stream:
                stream.raise_for_status()
                chunks: list[bytes] = []
                received = 0
                for chunk in stream.iter_bytes(chunk_size=65536):
                    chunks.append(chunk)
                    received += len(chunk)
                    record = apply_download_progress(record, received_bytes=received, etag=None)
                artifact_bytes = b"".join(chunks)
    except EndpointExecutionError:
        raise
    except Exception as exc:
        failed_call = fail_call(
            call,
            provider_error_code=None,
            normalized_error_code="TRANSPORT_ERROR",
            safe_error_message=str(exc)[:300],
        )
        raise EndpointExecutionError(
            f"ENDPOINT_TRANSPORT_FAILED:{exc}",
            details={"call_record": failed_call.model_dump(mode="json")},
        ) from exc

    import hashlib

    digest = hashlib.sha256(artifact_bytes).hexdigest()
    local_path = out_path / f"{definition.name}-artifact.bin"
    local_path.write_bytes(artifact_bytes)
    record = apply_download_complete(
        record, local_artifact_path=str(local_path), checksum=digest, actual_cost=0.0
    )
    done_call = complete_call(
        call, actual_cost=0.0, response_summary=f"job {record.provider_job_id}"
    )
    action, _ = decide_next_action(record)
    if action.value != "done":
        raise EndpointExecutionError("ENDPOINT_EXECUTION_NOT_DONE")

    media_type = (
        "video/mp4" if definition.capability.media_type == "video" else "application/octet-stream"
    )
    manifest = ArtifactManifest(
        production_id=params.get("production_run_id"),
        revision_id=params.get("production_revision"),
        artifacts=[
            Artifact(
                artifact_id=record.target_artifact_id,
                kind=definition.capability.media_type,
                path=str(local_path),
                media_type=media_type,
                primary=True,
                logical_role="endpoint_artifact",
            )
        ],
    )
    presentation_view: dict[str, Any] = {}
    if not test_only:
        from hevi.production.delivery_gate import probe_manifest_durations_ms

        try:
            snapshot = snapshot_for_serving(
                manifest,
                probe_durations_ms=probe_manifest_durations_ms(manifest),
                project_id=project_ref,
                production_run_id=params.get("production_run_id", "unknown"),
                revision_id=params.get("production_revision", "rev-1"),
            )
        except Exception:
            # Artifact download already succeeded; an unprobeable file stays a
            # registered artifact without a presentation selection.
            snapshot = None
        if snapshot is not None:
            presentation_view = snapshot.model_dump(mode="json")
    return ExecutionReport(
        test_only=test_only,
        submitted=submitted,
        polls_used=polls_used,
        terminal_status=terminal_status or "succeeded",
        provider_job_id=record.provider_job_id,
        artifact_local_path=str(local_path),
        artifact_sha256=digest,
        bytes_downloaded=len(artifact_bytes),
        fingerprint=fingerprint,
        execution_record=record.model_dump(mode="json"),
        call_record=done_call.model_dump(mode="json"),
        manifest=manifest.model_dump(mode="json"),
        presentation=presentation_view,
        completed_at=datetime.now(UTC).isoformat(),
    )


__all__ = ["EndpointExecutionError", "ExecutionReport", "execute_endpoint"]
