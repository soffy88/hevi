"""W4 gates: per-call evidence, secret safety, reconciliation, analytics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from hevi.creative.layer4.usage_ledger import (
    CallStatus,
    UsageError,
    aggregate,
    begin_call,
    cancel_call,
    complete_call,
    detect_attention,
    fail_call,
    find_call,
    reconcile_pending,
    redact_secrets,
)


def _call(**kw):
    args: dict = {
        "project_ref": "proj-a",
        "provider": "maas_lock",
        "model": "happyhorse-1.1",
        "operation_type": "video_generate",
        "estimated_cost": 0.5,
    }
    args.update(kw)
    return begin_call(**args)


def test_call_row_links_source_and_estimate() -> None:
    record = _call(task_ref="t-1", artifact_ref="clip-1", production_run_ref="r-1")
    assert record.status is CallStatus.PENDING
    assert record.task_ref == "t-1"
    assert record.estimated_cost == 0.5
    assert record.actual_cost is None


def test_secrets_never_enter_the_ledger() -> None:
    record = _call(
        request_summary="call with api_key: SECRET123 and Authorization: Bearer eyJhbGciOiJIUzI1NiJ9"
    )
    assert "SECRET123" not in record.request_summary
    assert "eyJhbGciOiJIUzI1NiJ9" not in record.request_summary
    assert "[REDACTED]" in record.request_summary
    assert "sk-abcdefgh12345678" not in redact_secrets("key sk-abcdefgh12345678 here")
    done = complete_call(record, actual_cost=0.4, response_summary="ok sk-abcdefgh12345678")
    assert "sk-abcdefgh12345678" not in done.response_summary


def test_complete_and_fail_carry_evidence() -> None:
    done = complete_call(_call(), actual_cost=0.42, output_units=10.0, video_units=1.0)
    assert done.status is CallStatus.SUCCEEDED
    assert done.actual_cost == 0.42
    assert done.latency_ms is not None and done.completed_at is not None
    failed = fail_call(
        _call(),
        provider_error_code="429",
        normalized_error_code="RATE_LIMITED",
        safe_error_message="provider busy, retry later",
    )
    assert failed.status is CallStatus.FAILED
    assert failed.normalized_error_code == "RATE_LIMITED"
    with pytest.raises(UsageError, match="USAGE_ALREADY_TERMINAL"):
        complete_call(done, actual_cost=0.1)


def test_cancel_is_not_failure() -> None:
    cancelled = cancel_call(_call())
    assert cancelled.status is CallStatus.CANCELLED
    assert cancelled.normalized_error_code is None
    analytics = aggregate((cancelled,))
    assert analytics.failed == 0
    assert analytics.cancelled == 1


def test_reconcile_moves_every_pending_to_terminal() -> None:
    ok = complete_call(_call(), actual_cost=0.1)
    p1, p2, p3 = _call(), _call(), _call()
    out = reconcile_pending(
        (ok, p1, p2, p3),
        {
            str(p1.call_id): ("succeeded", "provider confirms success"),
            str(p2.call_id): ("failed", "TIMEOUT"),
            str(p3.call_id): ("unknown-verdict", "no trace"),
        },
    )
    assert [r.status for r in out] == [
        CallStatus.SUCCEEDED,
        CallStatus.RECONCILED,
        CallStatus.FAILED,
        CallStatus.ABANDONED,
    ]
    assert out[2].normalized_error_code == "TIMEOUT"
    assert all(r.status is not CallStatus.PENDING for r in out)


def test_unreconciled_pending_refuses() -> None:
    with pytest.raises(UsageError, match="USAGE_UNRECONCILED_PENDING"):
        reconcile_pending((_call(),), {})


def test_aggregation_splits_cost_and_rates() -> None:
    a = complete_call(_call(project_ref="pa", operation_type="video_generate"), actual_cost=1.0)
    b = complete_call(
        _call(project_ref="pa", operation_type="tts", provider="f5", model="f5-base"),
        actual_cost=0.2,
    )
    c = fail_call(
        _call(project_ref="pb", operation_type="video_generate"),
        provider_error_code="500",
        normalized_error_code="SERVER_ERROR",
        safe_error_message="provider failed",
        retry_count=2,
    )
    analytics = aggregate((a, b, c))
    assert analytics.total_calls == 3
    assert analytics.succeeded == 2
    assert analytics.failed == 1
    assert analytics.success_rate == pytest.approx(2 / 3)
    assert analytics.retry_rate == pytest.approx(2 / 3)
    assert analytics.cost_by_project["pa"].actual == pytest.approx(1.2)
    assert analytics.cost_by_project["pb"].calls == 1
    assert analytics.cost_by_capability["tts"].actual == pytest.approx(0.2)
    assert analytics.cost_by_provider_model["maas_lock/happyhorse-1.1"].calls == 2
    assert analytics.avg_latency_ms >= 0


def test_multi_currency_never_folded() -> None:
    a = complete_call(_call(), actual_cost=1.0)
    b = complete_call(_call(currency="CNY"), actual_cost=7.0)
    with pytest.raises(UsageError, match="USAGE_MULTI_CURRENCY_NOT_FOLDED"):
        aggregate((a, b))


def test_trend_buckets_per_day() -> None:
    then = datetime.now(UTC) - timedelta(days=1)
    old = begin_call(
        project_ref="pa", provider="p", model="m", operation_type="op", estimated_cost=0.0
    ).model_copy(update={"started_at": then})
    old = complete_call(old, actual_cost=2.0)
    new = complete_call(_call(), actual_cost=3.0)
    trend = aggregate((old, new)).cost_trend_per_day
    assert len(trend) == 2
    assert sum(trend.values()) == pytest.approx(5.0)


def test_attention_flags_group_and_streak() -> None:
    good = [
        complete_call(_call(provider="steady", model="s1", operation_type="t"), actual_cost=0.1)
        for _ in range(6)
    ]
    bad = [
        fail_call(
            _call(provider="flaky", model="f9", operation_type="t"),
            provider_error_code="500",
            normalized_error_code="SERVER_ERROR",
            safe_error_message="down",
        )
        for _ in range(3)
    ]
    flags = detect_attention(tuple(good + bad))
    kinds = {(f.kind, f.subject) for f in flags}
    assert ("group_failure", "flaky/f9") in kinds
    assert ("consecutive_failures", "flaky/f9/t") in kinds
    assert detect_attention(tuple(good)) == ()


def test_deep_link_lookup() -> None:
    record = complete_call(_call(), actual_cost=0.3)
    assert find_call((record,), record.call_id).actual_cost == 0.3
    assert find_call((record,), str(record.call_id)).call_id == record.call_id
    with pytest.raises(UsageError, match="USAGE_CALL_NOT_FOUND"):
        find_call((record,), "00000000-0000-4000-8000-000000000000")


def test_terminal_evidence_validated() -> None:
    with pytest.raises(ValidationError, match="USAGE_FAILURE_NEEDS_NORMALIZED_CODE"):
        fail_call(
            _call(),
            provider_error_code="500",
            normalized_error_code="",
            safe_error_message="x",
        )
