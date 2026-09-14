"""Gold behaviour for token, cost, and latency analytics."""

from __future__ import annotations

import pytest

from hevi.creative.omodul import UsageRecord, calculate_analytics


def test_usage_records_aggregate_token_cost_latency() -> None:
    analytics = calculate_analytics(
        texts=(),
        audits=(),
        runs=(),
        revision_count=0,
        usage=(
            UsageRecord(model="local", prompt_tokens=10, completion_tokens=5, latency_ms=100.0),
            UsageRecord(model="remote", prompt_tokens=5, completion_tokens=5, cost_usd=0.5),
        ),
    )
    assert analytics.token_usage == {"local": 15, "remote": 10}
    assert analytics.model_usage == {"local": 1, "remote": 1}
    assert analytics.prompt_tokens == 15
    assert analytics.completion_tokens == 10
    assert analytics.cost_usd == 0.5
    assert analytics.latency_ms_total == 100.0
    assert analytics.latency_ms_avg == 50.0


def test_negative_usage_is_rejected() -> None:
    with pytest.raises(ValueError, match="ANALYTICS_INPUT_INVALID"):
        calculate_analytics(
            texts=(),
            audits=(),
            runs=(),
            revision_count=0,
            usage=(UsageRecord(model="bad", prompt_tokens=-1),),
        )
