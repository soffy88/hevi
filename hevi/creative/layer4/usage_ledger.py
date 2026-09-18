"""Call-level provider usage ledger (Gap Closure W4, ARC-N05/N06).

Not another billing total: one evidence row per model/provider call with
source linkage (project / run / task / artifact refs), redacted
request/response summaries, unit counts, estimated vs actual cost, and
machine + safe-human error codes. Crash-pending rows reconcile to a
terminal state — nothing stays pending forever. Pure aggregation powers
cost/latency/rate analytics, trend buckets, attention flags, and
call_id deep-links for the Layer4 dashboard.

Privacy contract: the ledger never stores API keys, Authorization
headers, or raw credentials. Prompts/inputs enter only as
caller-redacted summaries (hash/reference accepted); :func:`redact_secrets`
is a second net, not the first. Summaries are length-capped.

Role split (one module, documented roles):

- OBASE role: :class:`ProviderCallRecord`, :class:`CallStatus` — raw
  usage/cost primitives.
- OSERVI role: :func:`begin_call`, :func:`complete_call`,
  :func:`fail_call`, :func:`cancel_call`, :func:`reconcile_pending` —
  ingest/reconciliation runtime. Persistence stays with callers.
- OSKILL role: :func:`aggregate`, :func:`detect_attention`,
  :func:`find_call` — deterministic aggregation algorithms.
- HEVI_LAYER4 role: dashboard/API renders these structures.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

SUMMARY_MAX_LEN = 2000

_SECRET_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)([A-Za-z0-9\-._~+/=]+)"),
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)([^\s,;]+)"),
    re.compile(r"(?i)(authorization\s*:\s*)([^\s,;]+)"),
    re.compile(r"\bsk-[A-Za-z0-9]{8,}\b"),
)


def _redact_match(match: re.Match[str]) -> str:
    if match.lastindex:
        return f"{match.group(1)}[REDACTED]"
    return "[REDACTED]"


def redact_secrets(text: str) -> str:
    """Second-net redaction of credential-looking content."""

    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(_redact_match, redacted)
    return redacted[:SUMMARY_MAX_LEN]


class CallStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"
    RECONCILED = "reconciled"


class UsageError(ValueError):
    """Refusal with a stable machine code."""


class ProviderCallRecord(BaseModel):
    """One provider call. Terminal states carry full evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: UUID = Field(default_factory=uuid4)
    project_ref: str = Field(min_length=1)
    production_run_ref: str = ""
    task_ref: str = ""
    artifact_ref: str = ""
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    endpoint: str = ""
    operation_type: str = Field(min_length=1)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    latency_ms: int | None = None
    request_summary: str = ""
    response_summary: str = ""
    input_units: float = 0.0
    output_units: float = 0.0
    duration_units: float = 0.0
    image_units: float = 0.0
    video_units: float = 0.0
    currency: str = "USD"
    estimated_cost: float = 0.0
    actual_cost: float | None = None
    status: CallStatus = CallStatus.PENDING
    provider_error_code: str | None = None
    normalized_error_code: str | None = None
    safe_error_message: str | None = None
    retry_count: int = 0

    @model_validator(mode="after")
    def _terminal_states_carry_evidence(self) -> ProviderCallRecord:
        if self.status in (CallStatus.SUCCEEDED, CallStatus.RECONCILED) and (
            self.completed_at is None or self.latency_ms is None
        ):
            raise UsageError("USAGE_TERMINAL_NEEDS_COMPLETION_EVIDENCE")
        if self.status is CallStatus.FAILED and not self.normalized_error_code:
            raise UsageError("USAGE_FAILURE_NEEDS_NORMALIZED_CODE")
        if self.status is CallStatus.PENDING and (
            self.completed_at is not None or self.actual_cost is not None
        ):
            raise UsageError("USAGE_PENDING_CARRIES_NO_OUTCOME")
        return self


def begin_call(
    *,
    project_ref: str,
    provider: str,
    model: str,
    operation_type: str,
    request_summary: str = "",
    estimated_cost: float = 0.0,
    currency: str = "USD",
    production_run_ref: str = "",
    task_ref: str = "",
    artifact_ref: str = "",
    endpoint: str = "",
    input_units: float = 0.0,
) -> ProviderCallRecord:
    return ProviderCallRecord(
        project_ref=project_ref,
        production_run_ref=production_run_ref,
        task_ref=task_ref,
        artifact_ref=artifact_ref,
        provider=provider,
        model=model,
        endpoint=endpoint,
        operation_type=operation_type,
        request_summary=redact_secrets(request_summary),
        estimated_cost=estimated_cost,
        currency=currency,
        input_units=input_units,
    )


def _finish(
    record: ProviderCallRecord,
    status: CallStatus,
    completed_at: datetime | None = None,
    **updates: Any,
) -> ProviderCallRecord:
    if record.status is not CallStatus.PENDING:
        raise UsageError(f"USAGE_ALREADY_TERMINAL:{record.status.value}")
    done = completed_at or datetime.now(UTC)
    latency_ms = updates.pop("latency_ms", None)
    if latency_ms is None:
        latency_ms = max(0, int((done - record.started_at).total_seconds() * 1000))
    transitioned = record.model_copy(
        update={"status": status, "completed_at": done, "latency_ms": latency_ms, **updates}
    )
    # model_copy skips validation: re-validate so terminal-evidence rules
    # fail closed on every transition, not just construction.
    return ProviderCallRecord.model_validate(transitioned.model_dump())


def complete_call(
    record: ProviderCallRecord,
    *,
    actual_cost: float,
    response_summary: str = "",
    output_units: float = 0.0,
    duration_units: float = 0.0,
    image_units: float = 0.0,
    video_units: float = 0.0,
    retry_count: int = 0,
) -> ProviderCallRecord:
    return _finish(
        record,
        CallStatus.SUCCEEDED,
        actual_cost=actual_cost,
        response_summary=redact_secrets(response_summary),
        output_units=output_units,
        duration_units=duration_units,
        image_units=image_units,
        video_units=video_units,
        retry_count=retry_count,
    )


def fail_call(
    record: ProviderCallRecord,
    *,
    provider_error_code: str | None,
    normalized_error_code: str,
    safe_error_message: str,
    retry_count: int = 0,
) -> ProviderCallRecord:
    return _finish(
        record,
        CallStatus.FAILED,
        provider_error_code=provider_error_code,
        normalized_error_code=normalized_error_code,
        safe_error_message=safe_error_message,
        retry_count=retry_count,
    )


def cancel_call(record: ProviderCallRecord) -> ProviderCallRecord:
    """Cancels never count as failures (they carry no error code)."""

    return _finish(record, CallStatus.CANCELLED)


def reconcile_pending(
    records: tuple[ProviderCallRecord, ...],
    findings: dict[str, tuple[str, str | None]],
) -> tuple[ProviderCallRecord, ...]:
    """Crash reconciliation: every pending row reaches a terminal state.

    ``findings`` maps ``str(call_id)`` to ``(verdict, detail)`` where
    verdict is one of ``succeeded`` (detail = evidence note, cost unknown),
    ``failed`` (detail = normalized code), or anything else -> ABANDONED
    with the detail preserved. Unknown ids raise; nothing stays pending.
    """

    reconciled: list[ProviderCallRecord] = []
    for record in records:
        if record.status is not CallStatus.PENDING:
            reconciled.append(record)
            continue
        try:
            verdict, detail = findings[str(record.call_id)]
        except KeyError:
            raise UsageError(f"USAGE_UNRECONCILED_PENDING:{record.call_id}") from None
        if verdict == "succeeded":
            reconciled.append(
                _finish(
                    record,
                    CallStatus.RECONCILED,
                    response_summary=f"reconciled after restart: {detail or 'no detail'}",
                )
            )
        elif verdict == "failed":
            reconciled.append(
                _finish(
                    record,
                    CallStatus.FAILED,
                    provider_error_code=None,
                    normalized_error_code=detail or "UNKNOWN",
                    safe_error_message="reconciled after restart",
                )
            )
        else:
            reconciled.append(
                _finish(
                    record,
                    CallStatus.ABANDONED,
                    response_summary=f"abandoned after restart: {detail or 'no detail'}",
                )
            )
    return tuple(reconciled)


def find_call(records: tuple[ProviderCallRecord, ...], call_id: UUID | str) -> ProviderCallRecord:
    """Deep-link lookup: the call_id is the stable link target."""

    wanted = str(call_id)
    for record in records:
        if str(record.call_id) == wanted:
            return record
    raise UsageError("USAGE_CALL_NOT_FOUND")


class CostBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    estimated: float = 0.0
    actual: float = 0.0
    calls: int = 0


class UsageAnalytics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    total_calls: int = 0
    succeeded: int = 0
    failed: int = 0
    cancelled: int = 0
    abandoned: int = 0
    reconciled: int = 0
    success_rate: float = 0.0
    failure_rate: float = 0.0
    retry_rate: float = 0.0
    avg_latency_ms: float = 0.0
    cost_by_project: dict[str, CostBreakdown] = Field(default_factory=dict)
    cost_by_capability: dict[str, CostBreakdown] = Field(default_factory=dict)
    cost_by_provider_model: dict[str, CostBreakdown] = Field(default_factory=dict)
    cost_trend_per_day: dict[str, float] = Field(default_factory=dict)


def _add(breakdown: CostBreakdown | None, record: ProviderCallRecord) -> CostBreakdown:
    base = breakdown or CostBreakdown()
    return CostBreakdown(
        estimated=base.estimated + record.estimated_cost,
        actual=base.actual + (record.actual_cost or 0.0),
        calls=base.calls + 1,
    )


def aggregate(records: tuple[ProviderCallRecord, ...]) -> UsageAnalytics:
    """Deterministic rollups. Multi-currency amounts are never folded together."""

    currencies = {record.currency for record in records}
    if len(currencies) > 1:
        raise UsageError("USAGE_MULTI_CURRENCY_NOT_FOLDED")
    total = len(records)
    succeeded = sum(1 for r in records if r.status is CallStatus.SUCCEEDED)
    failed = sum(1 for r in records if r.status is CallStatus.FAILED)
    latencies = [r.latency_ms for r in records if r.latency_ms is not None]
    by_project: dict[str, CostBreakdown] = {}
    by_capability: dict[str, CostBreakdown] = {}
    by_provider_model: dict[str, CostBreakdown] = {}
    trend: dict[str, float] = {}
    for record in records:
        by_project[record.project_ref] = _add(by_project.get(record.project_ref), record)
        by_capability[record.operation_type] = _add(
            by_capability.get(record.operation_type), record
        )
        key = f"{record.provider}/{record.model}"
        by_provider_model[key] = _add(by_provider_model.get(key), record)
        day = record.started_at.date().isoformat()
        trend[day] = trend.get(day, 0.0) + (record.actual_cost or 0.0)
    retries = sum(r.retry_count for r in records)
    return UsageAnalytics(
        total_calls=total,
        succeeded=succeeded,
        failed=failed,
        cancelled=sum(1 for r in records if r.status is CallStatus.CANCELLED),
        abandoned=sum(1 for r in records if r.status is CallStatus.ABANDONED),
        reconciled=sum(1 for r in records if r.status is CallStatus.RECONCILED),
        success_rate=(succeeded / total) if total else 0.0,
        failure_rate=(failed / total) if total else 0.0,
        retry_rate=(retries / total) if total else 0.0,
        avg_latency_ms=(sum(latencies) / len(latencies)) if latencies else 0.0,
        cost_by_project=by_project,
        cost_by_capability=by_capability,
        cost_by_provider_model=by_provider_model,
        cost_trend_per_day=dict(sorted(trend.items())),
    )


class AttentionFlag(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str
    subject: str
    detail: str


def detect_attention(records: tuple[ProviderCallRecord, ...]) -> tuple[AttentionFlag, ...]:
    """Attention, not alarms: surfaces only on evidence.

    - group_failure: a (provider, model) group's failure rate is at least
      2x the overall rate (minimum 3 calls in the group).
    - consecutive_failures: 3+ consecutive failures for one
      (provider, model, operation_type) in start order.
    Silence (no flags) is the normal case.
    """

    terminal = [r for r in records if r.status in (CallStatus.SUCCEEDED, CallStatus.FAILED)]
    if not terminal:
        return ()
    overall = sum(1 for r in terminal if r.status is CallStatus.FAILED) / len(terminal)
    flags: list[AttentionFlag] = []
    groups: dict[str, list[ProviderCallRecord]] = {}
    for record in terminal:
        groups.setdefault(f"{record.provider}/{record.model}", []).append(record)
    for subject, rows in sorted(groups.items()):
        if len(rows) >= 3:
            rate = sum(1 for r in rows if r.status is CallStatus.FAILED) / len(rows)
            if rate >= max(2 * overall, 0.01) and rate > 0:
                flags.append(
                    AttentionFlag(
                        kind="group_failure",
                        subject=subject,
                        detail=f"failure rate {rate:.0%} vs overall {overall:.0%} over {len(rows)} calls",
                    )
                )
    streaks: dict[str, int] = {}
    for record in sorted(terminal, key=lambda r: r.started_at):
        key = f"{record.provider}/{record.model}/{record.operation_type}"
        if record.status is CallStatus.FAILED:
            streaks[key] = streaks.get(key, 0) + 1
            if streaks[key] == 3:
                flags.append(
                    AttentionFlag(
                        kind="consecutive_failures", subject=key, detail="3 consecutive failures"
                    )
                )
        else:
            streaks[key] = 0
    return tuple(flags)


__all__ = [
    "AttentionFlag",
    "CallStatus",
    "CostBreakdown",
    "ProviderCallRecord",
    "UsageAnalytics",
    "UsageError",
    "aggregate",
    "begin_call",
    "cancel_call",
    "complete_call",
    "detect_attention",
    "fail_call",
    "find_call",
    "reconcile_pending",
    "redact_secrets",
]
