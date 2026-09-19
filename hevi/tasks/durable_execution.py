"""TaskService durability wiring (Gap Closure W11).

The W3 durable provider plane reaches production here: execution records
live in ``task.config_json["provider_execution"]`` and submission counts
in ``config_json["provider_submissions"]``, persisted through the real
repository interface. A restarted worker (or a second delivery of the
same task) loads the record and resumes — poll, download, or explicit
fail — instead of re-submitting the provider job.

This module holds the pure config transforms; the three thin
``TaskService`` methods (``begin_durable_execution``,
``record_durable_event``, ``recover_durable_execution``) are the only
service surface and persist every transition. Legacy provider adapters
keep their behavior; new and migrated paths enter through here.
"""

from __future__ import annotations

from typing import Any

from hevi.creative.layer4.provider_execution import (
    NextAction,
    ProviderExecutionRecord,
    apply_download_complete,
    apply_download_progress,
    apply_poll_failure,
    apply_poll_success,
    apply_remote_expired,
    decide_next_action,
    guarded_submit,
    new_record,
)

EXECUTION_CONFIG_KEY = "provider_execution"
SUBMISSIONS_CONFIG_KEY = "provider_submissions"


class DurableExecutionError(ValueError):
    """Refusal with a stable machine code."""


def load_record(config: dict[str, Any]) -> ProviderExecutionRecord | None:
    raw = (config or {}).get(EXECUTION_CONFIG_KEY)
    if not raw:
        return None
    try:
        return ProviderExecutionRecord.model_validate(raw)
    except Exception as exc:
        raise DurableExecutionError("DURABLE_EXECUTION_RECORD_CORRUPT") from exc


def store_record(config: dict[str, Any], record: ProviderExecutionRecord) -> dict[str, Any]:
    return {**config, EXECUTION_CONFIG_KEY: record.model_dump(mode="json")}


def submission_count(config: dict[str, Any], fingerprint: str) -> int:
    submissions = (config or {}).get(SUBMISSIONS_CONFIG_KEY) or {}
    return int(submissions.get(fingerprint, 0))


def note_submission(config: dict[str, Any], fingerprint: str) -> dict[str, Any]:
    submissions = dict((config or {}).get(SUBMISSIONS_CONFIG_KEY) or {})
    submissions[fingerprint] = int(submissions.get(fingerprint, 0)) + 1
    return {**config, SUBMISSIONS_CONFIG_KEY: submissions}


def begin_execution(
    config: dict[str, Any],
    *,
    provider: str,
    endpoint: str,
    model: str,
    request: dict[str, Any],
    production_revision: str,
    target_artifact_id: str,
    idempotency_key: str,
) -> tuple[dict[str, Any], ProviderExecutionRecord, NextAction]:
    """Open (or re-enter) durable execution for one generation intent.

    A stored record with the same fingerprint resumes: the caller must
    follow ``decide_next_action`` and must NOT submit again. Only a fresh
    fingerprint yields SUBMIT, and the submission is counted at submit
    time by :func:`note_submission`, not here.
    """

    candidate = new_record(
        provider=provider,
        endpoint=endpoint,
        model=model,
        request=request,
        production_revision=production_revision,
        target_artifact_id=target_artifact_id,
        idempotency_key=idempotency_key,
    )
    existing = load_record(config)
    if existing is not None and existing.request_fingerprint == candidate.request_fingerprint:
        action, _ = decide_next_action(existing)
        return config, existing, action
    stored = store_record(config, candidate)
    return stored, candidate, NextAction.SUBMIT


def apply_execution_event(
    config: dict[str, Any], event: dict[str, Any]
) -> tuple[dict[str, Any], ProviderExecutionRecord]:
    """Apply one provider-side event and persist the resulting record."""

    record = load_record(config)
    if record is None:
        raise DurableExecutionError("DURABLE_EXECUTION_NO_RECORD")
    kind = str(event.get("kind") or "")
    if kind == "submitted":
        if submission_count(config, record.request_fingerprint):
            raise DurableExecutionError("DURABLE_EXECUTION_DUPLICATE_SUBMIT")
        updated, submitted = guarded_submit(record, set())
        if not submitted:  # pragma: no cover - guarded_submit raises instead
            raise DurableExecutionError("DURABLE_EXECUTION_SUBMIT_REFUSED")
        config = note_submission(config, record.request_fingerprint)
        record = updated.touch(provider_job_id=str(event.get("provider_job_id") or ""))
    elif kind == "poll_checkpoint":
        record = record.touch(
            poll_checkpoint=int(event.get("poll_checkpoint", record.poll_checkpoint + 1))
        )
    elif kind == "remote_success":
        record = apply_poll_success(
            record,
            remote_artifact_url=event.get("remote_artifact_url"),
            remote_artifact_ref=event.get("remote_artifact_ref"),
            provider_terminal_state=str(event.get("provider_terminal_state") or "succeeded"),
        )
    elif kind == "remote_failed":
        record = apply_poll_failure(
            record, terminal=True, error=str(event.get("error") or "provider failed")
        )
    elif kind == "remote_expired":
        record = apply_remote_expired(
            record, error=str(event.get("error") or "provider job expired")
        )
    elif kind == "download_progress":
        record = apply_download_progress(
            record,
            received_bytes=int(event.get("received_bytes", 0)),
            etag=event.get("etag"),
        )
    elif kind == "download_complete":
        if record.done:
            raise DurableExecutionError("DURABLE_EXECUTION_ALREADY_COMPLETE")
        record = apply_download_complete(
            record,
            local_artifact_path=str(event.get("local_artifact_path") or ""),
            checksum=str(event.get("checksum") or ""),
            actual_cost=float(event.get("actual_cost") or 0.0),
        )
    else:
        raise DurableExecutionError(f"DURABLE_EXECUTION_UNKNOWN_EVENT:{kind}")
    return store_record(config, record), record


def recover_execution(config: dict[str, Any]) -> tuple[NextAction, str]:
    """Restart recovery decision from persisted state. Never re-submits."""

    record = load_record(config)
    if record is None:
        return NextAction.SUBMIT, "no durable execution record yet"
    return decide_next_action(record)


def ensure_execution(
    config: dict[str, Any],
    *,
    provider: str,
    endpoint: str,
    model: str,
    request: dict[str, Any],
    production_revision: str,
    target_artifact_id: str,
) -> tuple[dict[str, Any], ProviderExecutionRecord, bool]:
    """Record task-level execution identity without gating re-execution.

    Unlike :func:`begin_execution`, this never refuses because a record
    exists — it is an observer for recovery/reporting, used by the task
    runtime which owns the retry decision. Returns (config, record, created).
    """

    candidate = new_record(
        provider=provider,
        endpoint=endpoint,
        model=model,
        request=request,
        production_revision=production_revision,
        target_artifact_id=target_artifact_id,
        idempotency_key="pending",
    )
    existing = load_record(config)
    if existing is not None and existing.request_fingerprint == candidate.request_fingerprint:
        return config, existing, False
    record = candidate.touch(idempotency_key=candidate.request_fingerprint[:32])
    return store_record(config, record), record, True


def reconcile_executions(
    tasks: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    """Startup reconciliation over non-terminal task rows.

    Pure: reports one decision per task carrying a durable execution record
    so a restarted worker resumes the right phase instead of blindly
    re-running or losing remote completion. Untracked tasks are reported as
    ``untracked`` (the worker keeps its existing behavior).
    """

    report: list[dict[str, Any]] = []
    for task in tasks:
        config = dict(task.get("config_json") or {})
        record = load_record(config)
        if record is None:
            report.append(
                {
                    "task_id": str(task.get("id") or ""),
                    "action": "untracked",
                    "provider_job_id": None,
                    "reason": "no durable execution record",
                }
            )
            continue
        action, reason = decide_next_action(record)
        report.append(
            {
                "task_id": str(task.get("id") or ""),
                "action": action.value,
                "provider_job_id": record.provider_job_id,
                "reason": reason,
                "remote_state": record.remote_state.value,
                "acquisition_state": record.acquisition_state.value,
                "billing_state": record.billing_state.value,
            }
        )
    return tuple(report)


__all__ = [
    "EXECUTION_CONFIG_KEY",
    "SUBMISSIONS_CONFIG_KEY",
    "DurableExecutionError",
    "apply_execution_event",
    "begin_execution",
    "ensure_execution",
    "load_record",
    "note_submission",
    "reconcile_executions",
    "recover_execution",
    "store_record",
    "submission_count",
]
