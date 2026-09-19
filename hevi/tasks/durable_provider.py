"""Durable async-provider driver (Gap Closure W16, ARC-E08).

Legacy adapters each hand-rolled submit -> while-poll -> write_bytes with
the provider job id living only in memory: any crash between remote
success and local download forced a re-submit (duplicate billing) or lost
the work. This driver runs the generic lifecycle over the W3 record:

- single-flight submit keyed by request fingerprint (W11 counting);
- submit retries ONLY on HTTP error-status rejections (proof the provider
  created nothing); transport ambiguity surfaces for explicit resume;
- poll checkpoints persisted; poll transport errors tolerated;
- download with Range resume (ETag-guarded; restart-from-zero without
  re-submit when Range is unsupported);
- REMOTE_SUCCEEDED + DOWNLOAD_FAILED retries/resumes download only.

Adapters keep provider specifics (request shape, response parsing, status
normalization, artifact-URL extraction) in two callbacks; everything
generic lives here. No second scheduler: callers persist configs via the
``persist`` hook (task_service update_task in production, dict capture in
tests).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx

from hevi.tasks.durable_execution import (
    apply_execution_event,
    begin_execution,
    store_record,
)

PollState = Literal["running", "succeeded", "failed", "expired"]


@dataclass(frozen=True)
class JobPoll:
    state: PollState
    artifact_url: str | None = None
    error: str | None = None
    terminal: str | None = None


class SubmitRejected(Exception):
    """HTTP error-status rejection: proof nothing was created, safe to retry."""

    def __init__(self, status_code: int | None, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class PollTransient(Exception):
    """Poll transport error: tolerated, checkpointed, polling continues."""


class DurableProviderError(ValueError):
    """Terminal driver failure with a stable machine code."""


def _normalized_error_code(message: str) -> str:
    """Map a driver failure message to a stable analytics code (single source)."""

    from hevi.creative.layer4.plan_projection import classify_failure_code

    return classify_failure_code(message)


async def download_with_resume(
    url: str,
    dest: Path,
    *,
    start_byte: int = 0,
    etag: str | None = None,
    timeout_s: float = 300.0,
    min_bytes: int = 1,
    client: httpx.AsyncClient | None = None,
) -> tuple[int, str | None]:
    """Fetch a URL with Range resume. Never re-submits anything.

    Returns (total_bytes, response_etag). ETag change restarts from zero;
    missing Range support restarts from zero; both without touching the
    provider job. min_bytes guards empty/placeholder payloads.
    """

    dest.parent.mkdir(parents=True, exist_ok=True)
    if start_byte < 0:
        start_byte = 0
    close_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=httpx.Timeout(timeout_s))
        close_client = True
    try:
        headers: dict[str, str] = {}
        if start_byte > 0:
            headers["Range"] = f"bytes={start_byte}-"
            if etag:
                headers["If-Match"] = etag
        response = await client.get(url, headers=headers)
        if response.status_code == 412:
            start_byte = 0
            response = await client.get(url)
        elif response.status_code == 416:
            return start_byte, etag
        elif response.status_code not in (200, 206):
            raise DurableProviderError(f"DURABLE_DOWNLOAD_HTTP_{response.status_code}")
        if start_byte > 0 and response.status_code == 200:
            start_byte = 0  # server ignored Range: restart, still no resubmit
        mode = "ab" if start_byte > 0 and response.status_code == 206 else "wb"
        if mode == "wb":
            start_byte = 0
        with dest.open(mode) as stream:
            async for chunk in response.aiter_bytes(chunk_size=65536):
                stream.write(chunk)
                start_byte += len(chunk)
        response_etag = response.headers.get("etag", etag)
        if start_byte < min_bytes:
            raise DurableProviderError("DURABLE_DOWNLOAD_EMPTY")
        return start_byte, response_etag
    finally:
        if close_client:
            await client.aclose()


async def run_durable_provider_job(
    *,
    config: dict[str, Any],
    provider: str,
    endpoint: str,
    model: str,
    request: dict[str, Any],
    production_revision: str,
    target_artifact_id: str,
    idempotency_key: str | None = None,
    output_path: Path,
    submit: Callable[[], Awaitable[str]],
    poll: Callable[[str], Awaitable[JobPoll]],
    poll_interval_s: float = 5.0,
    timeout_s: float = 600.0,
    initial_poll_delay_s: float = 0.0,
    submit_max_attempts: int = 5,
    submit_backoff_s: tuple[float, ...] = (4.0, 8.0, 16.0, 30.0, 30.0),
    min_bytes: int = 1024,
    download_timeout_s: float = 300.0,
    download_client: httpx.AsyncClient | None = None,
    actual_cost: float = 0.0,
    error_factory: Callable[[str], Exception] | None = None,
    persist: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    live_state: dict[str, Any] | None = None,
    project_ref: str = "unknown",
    operation_type: str = "generate",
) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    """Run one provider job durably. Returns (config, local_path, record_dump)."""

    def _fail(message: str) -> Exception:
        return error_factory(message) if error_factory else DurableProviderError(message)

    async def _persist(current: dict[str, Any]) -> None:
        if live_state is not None:
            live_state.clear()
            live_state.update(current)
        if persist is not None:
            await persist(current)

    config, record, action = begin_execution(
        config,
        provider=provider,
        endpoint=endpoint,
        model=model,
        request=request,
        production_revision=production_revision,
        target_artifact_id=target_artifact_id,
        idempotency_key=idempotency_key or "pending",
    )
    if not idempotency_key:
        # Stable per intent: same fingerprint always re-derives the same key.
        record = record.touch(idempotency_key=record.request_fingerprint[:32])
        config = store_record(config, record)
    await _persist(config)
    if action.value == "done":
        path = Path(record.local_artifact_path or "")
        if path.is_file():
            return config, path, record.model_dump(mode="json")
        # Artifact file lost after completion: re-download, never re-submit.
        action_value = "resume_download"
    else:
        action_value = action.value
    if action_value == "explicit_fail":
        raise _fail(f"DURABLE_JOB_EXPLICIT_FAIL:{record.last_error or 'unknown'}")

    from hevi.creative.layer4.usage_ledger import begin_call, complete_call, fail_call

    call = begin_call(
        project_ref=project_ref,
        provider=provider,
        model=model,
        operation_type=operation_type,
        request_summary=f"{endpoint} v{record.request_fingerprint[:12]}",
        endpoint=endpoint,
    )

    def _store() -> Any:  # best-effort ledger emission; never blocks the provider path
        from hevi.creative.layer4.authority_stores import CallLedgerStore

        return CallLedgerStore()

    def _emit_ok(cost: float) -> None:
        with contextlib.suppress(Exception):  # ledger must not fail the call
            _store().append(
                complete_call(
                    call, actual_cost=cost, response_summary=str(record.provider_job_id)
                ).model_dump(mode="json")
            )

    def _emit_fail(message: str) -> None:
        with contextlib.suppress(Exception):
            _store().append(
                fail_call(
                    call,
                    provider_error_code=None,
                    normalized_error_code=_normalized_error_code(message),
                    safe_error_message=message[:300],
                ).model_dump(mode="json")
            )

    try:
        if action_value == "submit":
            job_id: str | None = None
            last_rejection: str = "no attempts"
            for attempt in range(max(1, submit_max_attempts)):
                try:
                    job_id = await submit()
                    break
                except SubmitRejected as exc:
                    last_rejection = f"HTTP {exc.status_code}: {exc}"
                    if attempt + 1 < max(1, submit_max_attempts):
                        await asyncio.sleep(
                            submit_backoff_s[min(attempt, len(submit_backoff_s) - 1)]
                        )
                        continue
                    raise _fail(f"DURABLE_SUBMIT_REJECTED:{last_rejection}") from exc
            if job_id is None:  # pragma: no cover - loop always breaks or raises
                raise _fail(f"DURABLE_SUBMIT_REJECTED:{last_rejection}")
            config, record = apply_execution_event(
                config, {"kind": "submitted", "provider_job_id": job_id}
            )
            await _persist(config)
        else:
            job_id = record.provider_job_id
            if job_id is None:
                raise _fail("DURABLE_RESUME_WITHOUT_JOB_ID")

        if action_value in ("submit", "resume_poll"):
            if initial_poll_delay_s > 0:
                await asyncio.sleep(initial_poll_delay_s)
            elapsed = 0.0
            while elapsed < timeout_s:
                await asyncio.sleep(poll_interval_s)
                elapsed += poll_interval_s
                try:
                    result = await poll(job_id)
                except PollTransient:
                    # Poll transport errors mutate nothing: checkpoint and continue.
                    config, record = apply_execution_event(
                        config,
                        {"kind": "poll_checkpoint", "poll_checkpoint": record.poll_checkpoint + 1},
                    )
                    await _persist(config)
                    continue
                if result.state == "running":
                    config, record = apply_execution_event(
                        config,
                        {"kind": "poll_checkpoint", "poll_checkpoint": record.poll_checkpoint + 1},
                    )
                    await _persist(config)
                    continue
                if result.state == "succeeded":
                    config, record = apply_execution_event(
                        config,
                        {
                            "kind": "remote_success",
                            "remote_artifact_url": result.artifact_url,
                            "provider_terminal_state": result.terminal or "succeeded",
                        },
                    )
                    await _persist(config)
                    break
                if result.state == "expired":
                    config, record = apply_execution_event(
                        config, {"kind": "remote_expired", "error": result.error or "expired"}
                    )
                    await _persist(config)
                    raise _fail(f"DURABLE_JOB_EXPIRED:{result.error or ''}")
                config, record = apply_execution_event(
                    config, {"kind": "remote_failed", "error": result.error or "failed"}
                )
                await _persist(config)
                raise _fail(f"DURABLE_JOB_FAILED:{result.error or ''}")
            else:
                raise _fail(f"DURABLE_POLL_TIMEOUT:{timeout_s}s")

        location = record.remote_artifact_url or record.remote_artifact_ref or ""
        if not location:
            raise _fail("DURABLE_NO_ARTIFACT_LOCATION")
        try:
            total, response_etag = await download_with_resume(
                location,
                output_path,
                start_byte=record.download_bytes,
                etag=record.download_etag,
                timeout_s=download_timeout_s,
                min_bytes=min_bytes,
                client=download_client,
            )
        except DurableProviderError as exc:
            raise _fail(str(exc)) from exc
        config, record = apply_execution_event(
            config,
            {
                "kind": "download_progress",
                "received_bytes": total,
                "etag": response_etag,
            },
        )
        await _persist(config)
        digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
        config, record = apply_execution_event(
            config,
            {
                "kind": "download_complete",
                "local_artifact_path": str(output_path),
                "checksum": digest,
                "actual_cost": actual_cost,
            },
        )
        await _persist(config)
        _emit_ok(actual_cost)
        return config, output_path, record.model_dump(mode="json")
    except Exception as exc:
        _emit_fail(str(exc))
        raise


__all__ = [
    "DurableProviderError",
    "JobPoll",
    "PollTransient",
    "SubmitRejected",
    "download_with_resume",
    "run_durable_provider_job",
]
