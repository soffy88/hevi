"""Durable provider execution plane (Gap Closure W3, ARC-E08 P0).

Duplicate billing, duplicate side effects, and lost remote work all come
from one confusion: treating REMOTE GENERATION and LOCAL ARTIFACT
ACQUISITION as a single lifecycle. This module keeps two explicit
lifecycles on one persistent :class:`ProviderExecutionRecord`:

- remote: UNSENT -> SUBMITTING -> SUBMITTED -> POLLING ->
  REMOTE_SUCCEEDED | REMOTE_FAILED | REMOTE_EXPIRED
- acquisition: NOT_STARTED -> DOWNLOAD_PENDING -> DOWNLOADING ->
  DOWNLOAD_COMPLETE (+ VERIFY_FAILED loops back to DOWNLOAD_PENDING)

The critical invariant: REMOTE_SUCCEEDED + DOWNLOAD_PENDING must never
read as FAILED — otherwise a retry re-submits the provider job and bills
twice for work that already finished remotely.

Role split (one module, documented roles):

- OSERVI role: :class:`ProviderExecutionRecord`, :func:`decide_next_action`,
  :func:`guarded_submit`, poll/download appliers — generic durable logic.
  Persistence belongs to callers (task config_json / DB rows); records are
  serializable frozen models. No second scheduler: callers drive these
  decisions from the existing background_runs / Production Graph runtime.
- OPRIM/OBASE role (adapters, not here): single submit/poll/Range-download
  HTTP calls execute the plans this module emits
  (:class:`DownloadPlan` carries offset/etag/allowances).
- HEVI_LAYER4 role: business assembly maps task state to records and back.

Idempotency spans double-click, worker retry, SSE reconnect, HTTP retry,
and scheduler retry through one stable ``request_fingerprint`` over
(provider, endpoint, normalized request, production revision, target
artifact identity) plus an ``idempotency_key`` carried to the provider.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RemoteState(StrEnum):
    UNSENT = "unsent"
    SUBMITTING = "submitting"
    SUBMITTED = "submitted"
    POLLING = "polling"
    REMOTE_SUCCEEDED = "remote_succeeded"
    REMOTE_FAILED = "remote_failed"
    REMOTE_EXPIRED = "remote_expired"


class AcquisitionState(StrEnum):
    NOT_STARTED = "not_started"
    DOWNLOAD_PENDING = "download_pending"
    DOWNLOADING = "downloading"
    DOWNLOAD_COMPLETE = "download_complete"


class BillingState(StrEnum):
    UNBILLED = "unbilled"
    BILLED = "billed"
    FAILED_NOT_BILLED = "failed_not_billed"


class NextAction(StrEnum):
    SUBMIT = "submit"
    RESUME_POLL = "resume_poll"
    RESUME_DOWNLOAD = "resume_download"
    VERIFY = "verify"
    DONE = "done"
    EXPLICIT_FAIL = "explicit_fail"


class ExecutionError(ValueError):
    """Refusal with a stable machine code."""


def intent_fingerprint(
    *,
    provider: str,
    endpoint: str,
    request: Mapping[str, Any],
    production_revision: str,
    target_artifact_id: str,
) -> str:
    """Stable identity for one generation intent across all retry surfaces."""

    canonical = json.dumps(
        {
            "provider": provider,
            "endpoint": endpoint,
            "request": _normalize(request),
            "production_revision": production_revision,
            "target_artifact_id": target_artifact_id,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _normalize(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return value


class ProviderExecutionRecord(BaseModel):
    """Persistent execution state. Callers persist; this module decides."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1)
    endpoint: str = Field(min_length=1)
    model: str = Field(min_length=1)
    request_fingerprint: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    target_artifact_id: str = Field(min_length=1)
    remote_state: RemoteState = RemoteState.UNSENT
    provider_job_id: str | None = None
    poll_checkpoint: int = 0
    provider_terminal_state: str | None = None
    remote_artifact_url: str | None = None
    remote_artifact_ref: str | None = None
    acquisition_state: AcquisitionState = AcquisitionState.NOT_STARTED
    download_bytes: int = 0
    download_etag: str | None = None
    download_checksum: str | None = None
    expected_checksum: str | None = None
    local_artifact_path: str | None = None
    billing_state: BillingState = BillingState.UNBILLED
    actual_cost: float = 0.0
    attempt: int = 0
    last_error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def touch(self, **updates: Any) -> ProviderExecutionRecord:
        return self.model_copy(update={**updates, "updated_at": datetime.now(UTC)})

    @property
    def remote_finished(self) -> bool:
        return self.remote_state is RemoteState.REMOTE_SUCCEEDED

    @property
    def download_finished(self) -> bool:
        return self.acquisition_state is AcquisitionState.DOWNLOAD_COMPLETE

    @property
    def done(self) -> bool:
        return self.remote_finished and self.download_finished


class DownloadPlan(BaseModel):
    """What an OPRIM adapter must execute — resume offset, not regeneration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str
    resume_from_byte: int = Field(ge=0)
    etag: str | None = None
    range_supported: bool = True
    restart_without_resubmit: bool = False


def decide_next_action(record: ProviderExecutionRecord) -> tuple[NextAction, str]:
    """Restart/scheduler-safe decision. Never re-submits a known remote job."""

    if record.done:
        return NextAction.DONE, "remote succeeded and artifact acquired"
    if record.remote_state in (RemoteState.REMOTE_FAILED, RemoteState.REMOTE_EXPIRED):
        return NextAction.EXPLICIT_FAIL, f"remote terminal: {record.remote_state.value}"
    if record.remote_state is RemoteState.REMOTE_SUCCEEDED:
        if record.acquisition_state is AcquisitionState.DOWNLOAD_COMPLETE:
            return NextAction.VERIFY, "downloaded bytes await checksum verification"
        return NextAction.RESUME_DOWNLOAD, "remote succeeded; acquire artifact only"
    if record.provider_job_id is not None or record.remote_state in (
        RemoteState.SUBMITTING,
        RemoteState.SUBMITTED,
        RemoteState.POLLING,
    ):
        return NextAction.RESUME_POLL, "provider job known; poll, never re-submit"
    return NextAction.SUBMIT, "no provider job yet for this fingerprint"


def guarded_submit(
    record: ProviderExecutionRecord,
    submitted_fingerprints: set[str],
) -> tuple[ProviderExecutionRecord, bool]:
    """Submit exactly once per fingerprint while a remote job may be live.

    Returns ``(record, submitted)``. ``submitted`` is True only when this
    call is the one that must hit the provider. Any known job id, any
    non-terminal remote progress, or any prior submission of the same
    fingerprint refuses with ``submitted=False`` — the caller resumes
    instead. Double-clicks, worker retries, SSE reconnects, HTTP retries,
    and scheduler retries all funnel through here.
    """

    if record.remote_finished:
        raise ExecutionError("EXECUTION_REMOTE_SUCCEEDED_NEVER_RESUBMIT")
    if record.provider_job_id is not None:
        raise ExecutionError("EXECUTION_JOB_ALREADY_KNOWN_RESUME_INSTEAD")
    if record.remote_state not in (RemoteState.UNSENT,):
        raise ExecutionError("EXECUTION_REMOTE_IN_FLIGHT_RESUME_INSTEAD")
    if record.request_fingerprint in submitted_fingerprints:
        raise ExecutionError("EXECUTION_FINGERPRINT_ALREADY_SUBMITTED")
    submitted_fingerprints.add(record.request_fingerprint)
    return (
        record.touch(
            remote_state=RemoteState.SUBMITTED,
            attempt=record.attempt + 1,
            last_error=None,
        ),
        True,
    )


def apply_poll_success(
    record: ProviderExecutionRecord,
    *,
    remote_artifact_url: str | None = None,
    remote_artifact_ref: str | None = None,
    provider_terminal_state: str = "succeeded",
) -> ProviderExecutionRecord:
    return record.touch(
        remote_state=RemoteState.REMOTE_SUCCEEDED,
        provider_terminal_state=provider_terminal_state,
        remote_artifact_url=remote_artifact_url,
        remote_artifact_ref=remote_artifact_ref,
        acquisition_state=AcquisitionState.DOWNLOAD_PENDING
        if record.acquisition_state is AcquisitionState.NOT_STARTED
        else record.acquisition_state,
    )


def apply_poll_failure(
    record: ProviderExecutionRecord, *, terminal: bool, error: str
) -> ProviderExecutionRecord:
    if terminal:
        return record.touch(
            remote_state=RemoteState.REMOTE_FAILED,
            provider_terminal_state="failed",
            last_error=error,
            billing_state=BillingState.FAILED_NOT_BILLED,
        )
    return record.touch(
        remote_state=RemoteState.POLLING,
        poll_checkpoint=record.poll_checkpoint + 1,
        last_error=error,
    )


def apply_remote_expired(record: ProviderExecutionRecord, *, error: str) -> ProviderExecutionRecord:
    """Expired/missing remote jobs fail explicitly — never silent re-submit."""

    return record.touch(
        remote_state=RemoteState.REMOTE_EXPIRED,
        provider_terminal_state="expired",
        last_error=error,
    )


def download_plan(
    record: ProviderExecutionRecord, *, range_supported: bool, fresh_url: str | None = None
) -> DownloadPlan:
    """Resume the interrupted download; re-download is not re-generation."""

    if not record.remote_finished:
        raise ExecutionError("EXECUTION_DOWNLOAD_BEFORE_REMOTE_SUCCESS")
    url = fresh_url or record.remote_artifact_url or record.remote_artifact_ref or ""
    if not url:
        raise ExecutionError("EXECUTION_NO_REMOTE_ARTIFACT_LOCATION")
    if range_supported:
        return DownloadPlan(
            url=url, resume_from_byte=record.download_bytes, etag=record.download_etag
        )
    return DownloadPlan(
        url=url, resume_from_byte=0, etag=None, range_supported=False, restart_without_resubmit=True
    )


def apply_download_progress(
    record: ProviderExecutionRecord, *, received_bytes: int, etag: str | None
) -> ProviderExecutionRecord:
    if etag is not None and record.download_etag is not None and etag != record.download_etag:
        raise ExecutionError("EXECUTION_DOWNLOAD_ETAG_CHANGED_RESTART")
    return record.touch(
        acquisition_state=AcquisitionState.DOWNLOADING,
        download_bytes=received_bytes,
        download_etag=etag if etag is not None else record.download_etag,
    )


def apply_download_complete(
    record: ProviderExecutionRecord,
    *,
    local_artifact_path: str,
    checksum: str,
    actual_cost: float = 0.0,
) -> ProviderExecutionRecord:
    if record.expected_checksum is not None and checksum != record.expected_checksum:
        return record.touch(
            acquisition_state=AcquisitionState.DOWNLOAD_PENDING,
            download_bytes=0,
            download_etag=None,
            download_checksum=checksum,
            last_error="checksum mismatch; remote success kept, download retried",
        )
    return record.touch(
        acquisition_state=AcquisitionState.DOWNLOAD_COMPLETE,
        local_artifact_path=local_artifact_path,
        download_checksum=checksum,
        billing_state=BillingState.BILLED,
        actual_cost=actual_cost,
    )


def assert_no_duplicate_submit(submission_log: tuple[str, ...]) -> None:
    """DUPLICATE_PROVIDER_SUBMITS=0 gate over a fingerprint submission log."""

    seen: set[str] = set()
    for fingerprint in submission_log:
        if fingerprint in seen:
            raise ExecutionError(f"EXECUTION_DUPLICATE_SUBMIT:{fingerprint[:16]}")
        seen.add(fingerprint)


def new_record(
    *,
    provider: str,
    endpoint: str,
    model: str,
    request: Mapping[str, Any],
    production_revision: str,
    target_artifact_id: str,
    idempotency_key: str,
) -> ProviderExecutionRecord:
    return ProviderExecutionRecord(
        provider=provider,
        endpoint=endpoint,
        model=model,
        request_fingerprint=intent_fingerprint(
            provider=provider,
            endpoint=endpoint,
            request=request,
            production_revision=production_revision,
            target_artifact_id=target_artifact_id,
        ),
        idempotency_key=idempotency_key,
        target_artifact_id=target_artifact_id,
    )


__all__ = [
    "AcquisitionState",
    "BillingState",
    "DownloadPlan",
    "ExecutionError",
    "NextAction",
    "ProviderExecutionRecord",
    "RemoteState",
    "apply_download_complete",
    "apply_download_progress",
    "apply_poll_failure",
    "apply_poll_success",
    "apply_remote_expired",
    "assert_no_duplicate_submit",
    "decide_next_action",
    "download_plan",
    "guarded_submit",
    "intent_fingerprint",
    "new_record",
]
