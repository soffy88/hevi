"""W3 fault matrix: 13 crash/interruption scenarios, zero duplicate submits."""

from __future__ import annotations

import pytest

from hevi.creative.layer4.provider_execution import (
    AcquisitionState,
    BillingState,
    ExecutionError,
    NextAction,
    ProviderExecutionRecord,
    RemoteState,
    apply_download_complete,
    apply_download_progress,
    apply_poll_failure,
    apply_poll_success,
    apply_remote_expired,
    assert_no_duplicate_submit,
    decide_next_action,
    download_plan,
    guarded_submit,
    new_record,
)


def _record(**kw) -> ProviderExecutionRecord:
    args: dict = {
        "provider": "maas_lock",
        "endpoint": "https://provider.example/v1/jobs",
        "model": "happyhorse-1.1",
        "request": {"prompt": "雨夜街景", "duration_s": 5},
        "production_revision": "rev-9",
        "target_artifact_id": "clip-1",
        "idempotency_key": "idem-1",
    }
    args.update(kw)
    return new_record(**args)


def _submitted() -> tuple[ProviderExecutionRecord, set[str]]:
    record = _record()
    log: set[str] = set()
    record, submitted = guarded_submit(record, log)
    assert submitted is True
    return record.touch(provider_job_id="job-1"), log


def test_fingerprint_stable_across_key_order_and_retry_surfaces() -> None:
    base = _record()
    twin = _record(request={"duration_s": 5, "prompt": "雨夜街景"})
    assert twin.request_fingerprint == base.request_fingerprint
    other_target = _record(target_artifact_id="clip-2")
    assert other_target.request_fingerprint != base.request_fingerprint
    other_rev = _record(production_revision="rev-10")
    assert other_rev.request_fingerprint != base.request_fingerprint


def test_submit_crash_before_job_id_means_safe_submit() -> None:
    """Crash before submit: nothing persisted -> SUBMIT is correct."""

    action, _ = decide_next_action(_record())
    assert action is NextAction.SUBMIT


def test_crash_after_submit_resumes_poll_never_resubmits() -> None:
    record, log = _submitted()
    action, reason = decide_next_action(record)
    assert action is NextAction.RESUME_POLL
    assert "never re-submit" in reason
    with pytest.raises(ExecutionError, match="EXECUTION_JOB_ALREADY_KNOWN_RESUME_INSTEAD"):
        guarded_submit(record, log)
    with pytest.raises(ExecutionError, match="EXECUTION_REMOTE_IN_FLIGHT_RESUME_INSTEAD"):
        guarded_submit(record.touch(provider_job_id=None), log)


def test_crash_during_poll_resumes_poll() -> None:
    record, _ = _submitted()
    record = apply_poll_failure(record, terminal=False, error="timeout")
    assert record.remote_state is RemoteState.POLLING
    assert record.poll_checkpoint == 1
    action, _ = decide_next_action(record)
    assert action is NextAction.RESUME_POLL


def test_crash_after_provider_finished_resumes_download_only() -> None:
    record, log = _submitted()
    record = apply_poll_success(record, remote_artifact_url="https://cdn.example/clip.mp4")
    assert record.remote_finished is True
    assert record.acquisition_state is AcquisitionState.DOWNLOAD_PENDING
    action, reason = decide_next_action(record)
    assert action is NextAction.RESUME_DOWNLOAD
    assert "acquire artifact only" in reason
    with pytest.raises(ExecutionError, match="EXECUTION_REMOTE_SUCCEEDED_NEVER_RESUBMIT"):
        guarded_submit(record, log)


def test_download_10_percent_crash_resumes_with_range() -> None:
    record, _ = _submitted()
    record = apply_poll_success(record, remote_artifact_url="https://cdn.example/clip.mp4")
    record = apply_download_progress(record, received_bytes=102_400, etag="etag-1")
    plan = download_plan(record, range_supported=True)
    assert plan.resume_from_byte == 102_400
    assert plan.etag == "etag-1"
    assert plan.restart_without_resubmit is False


def test_download_90_percent_crash_keeps_remote_success() -> None:
    record, _ = _submitted()
    record = apply_poll_success(record, remote_artifact_url="https://cdn.example/clip.mp4")
    record = apply_download_progress(record, received_bytes=9_000_000, etag="etag-1")
    action, _ = decide_next_action(record)
    assert action is NextAction.RESUME_DOWNLOAD
    assert record.remote_finished is True  # success never lost to a download crash


def test_checksum_failure_retries_download_keeps_remote_and_bill_clean() -> None:
    record, _ = _submitted()
    record = apply_poll_success(record, remote_artifact_url="https://cdn.example/clip.mp4")
    record = record.touch(expected_checksum="aaa")
    record = apply_download_complete(
        record, local_artifact_path="/v/clip.mp4", checksum="bbb", actual_cost=1.2
    )
    assert record.acquisition_state is AcquisitionState.DOWNLOAD_PENDING
    assert record.download_bytes == 0
    assert record.remote_finished is True
    assert record.billing_state is BillingState.UNBILLED
    assert "checksum mismatch" in (record.last_error or "")


def test_temporary_signed_url_expiry_uses_fresh_url_without_resubmit() -> None:
    record, _ = _submitted()
    record = apply_poll_success(record, remote_artifact_url="https://cdn.example/expired?sig=old")
    plan = download_plan(
        record, range_supported=True, fresh_url="https://cdn.example/clip.mp4?sig=new"
    )
    assert plan.url == "https://cdn.example/clip.mp4?sig=new"
    assert plan.resume_from_byte == 0


def test_http_range_unsupported_restarts_download_not_generation() -> None:
    record, _ = _submitted()
    record = apply_poll_success(record, remote_artifact_url="https://cdn.example/clip.mp4")
    record = apply_download_progress(record, received_bytes=500, etag=None)
    plan = download_plan(record, range_supported=False)
    assert plan.resume_from_byte == 0
    assert plan.restart_without_resubmit is True
    action, _ = decide_next_action(record)
    assert action is NextAction.RESUME_DOWNLOAD  # still download, never submit


def test_worker_duplicate_delivery_submits_once() -> None:
    record = _record()
    log: set[str] = set()
    first, ok_first = guarded_submit(record, log)
    assert ok_first is True
    with pytest.raises(ExecutionError, match="EXECUTION_REMOTE_IN_FLIGHT_RESUME_INSTEAD"):
        guarded_submit(first.touch(provider_job_id=None), log)
    assert len(log) == 1
    assert_no_duplicate_submit(tuple(log))


def test_two_workers_same_job_second_resumes() -> None:
    record, _ = _submitted()
    twin = record.model_copy(update={})
    assert decide_next_action(twin)[0] is NextAction.RESUME_POLL
    with pytest.raises(ExecutionError, match="EXECUTION_JOB_ALREADY_KNOWN_RESUME_INSTEAD"):
        guarded_submit(twin, set())


def test_sse_disconnect_and_db_reconnect_never_lose_completion() -> None:
    record, _ = _submitted()
    record = apply_poll_success(record, remote_artifact_url="https://cdn.example/clip.mp4")
    record = apply_download_complete(
        record, local_artifact_path="/v/clip.mp4", checksum="c9", actual_cost=0.45
    )
    # reconnect replays persisted state: done reads done, billed exactly once
    assert decide_next_action(record)[0] is NextAction.DONE
    assert record.billing_state is BillingState.BILLED
    assert record.actual_cost == 0.45
    assert record.local_artifact_path == "/v/clip.mp4"


def test_expired_remote_fails_explicitly_never_silent_resubmit() -> None:
    record, _ = _submitted()
    record = apply_remote_expired(record, error="provider: job not found (expired)")
    action, reason = decide_next_action(record)
    assert action is NextAction.EXPLICIT_FAIL
    assert "expired" in reason
    with pytest.raises(ExecutionError, match="EXECUTION_JOB_ALREADY_KNOWN_RESUME_INSTEAD"):
        guarded_submit(record, set())


def test_terminal_remote_failure_is_not_billed() -> None:
    record, _ = _submitted()
    record = apply_poll_failure(record, terminal=True, error="content rejected")
    action, _ = decide_next_action(record)
    assert action is NextAction.EXPLICIT_FAIL
    assert record.billing_state is BillingState.FAILED_NOT_BILLED


def test_download_before_remote_success_refused() -> None:
    record, _ = _submitted()
    with pytest.raises(ExecutionError, match="EXECUTION_DOWNLOAD_BEFORE_REMOTE_SUCCESS"):
        download_plan(record, range_supported=True)


def test_etag_change_restarts_download() -> None:
    record, _ = _submitted()
    record = apply_poll_success(record, remote_artifact_url="https://cdn.example/clip.mp4")
    record = apply_download_progress(record, received_bytes=100, etag="etag-1")
    with pytest.raises(ExecutionError, match="EXECUTION_DOWNLOAD_ETAG_CHANGED_RESTART"):
        apply_download_progress(record, received_bytes=200, etag="etag-2")


def test_gate_duplicate_provider_submits_zero() -> None:
    """DUPLICATE_PROVIDER_SUBMITS=0 / DUPLICATE_BILLING=0 over a mixed history."""

    assert_no_duplicate_submit(("fp-a", "fp-b", "fp-c"))
    with pytest.raises(ExecutionError, match="EXECUTION_DUPLICATE_SUBMIT"):
        assert_no_duplicate_submit(("fp-a", "fp-b", "fp-a"))


def test_false_success_and_lost_completion_impossible_by_construction() -> None:
    """FALSE_SUCCESS=0 / LOST_REMOTE_COMPLETION=0 / LOST_ARTIFACT=0.

    done requires both lifecycles; no path marks done early, and every
    crash state routes to an explicit resume or explicit fail.
    """

    record, _ = _submitted()
    assert decide_next_action(record)[0] is not NextAction.DONE
    record = apply_poll_success(record, remote_artifact_url="https://cdn.example/clip.mp4")
    assert decide_next_action(record)[0] is not NextAction.DONE
    assert decide_next_action(record)[0] is not NextAction.EXPLICIT_FAIL
    record = record.touch(acquisition_state=AcquisitionState.DOWNLOADING, download_bytes=10)
    assert record.remote_finished is True  # completion survives mid-download crash
    finished = apply_download_complete(record, local_artifact_path="/v/c.mp4", checksum="k")
    assert finished.done is True
    assert finished.local_artifact_path == "/v/c.mp4"
