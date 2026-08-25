"""provider_scoring 测试 —— 7 维评分 + 决策日志(差距 A1)。

覆盖: 加权总分/降序/边界钳制/非法值/explain/决策日志写读/能力行构造/空候选。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hevi.providers.scoring import (
    DEFAULT_WEIGHTS,
    CapabilityRow,
    ProviderScore,
    choose_provider,
    read_decision_log,
    score_candidates_from_capabilities,
    score_providers,
)


def _candidates() -> list[dict]:
    return [
        {
            "provider": "h3_local",
            "task_fit": 0.9,
            "output_quality": 0.6,
            "control": 0.8,
            "reliability": 0.7,
            "cost_efficiency": 0.9,
            "latency": 0.8,
            "continuity": 0.5,
        },
        {
            "provider": "wan_2_7_maas",
            "task_fit": 0.7,
            "output_quality": 0.9,
            "control": 0.5,
            "reliability": 0.9,
            "cost_efficiency": 0.3,
            "latency": 0.4,
            "continuity": 0.8,
        },
    ]


def test_weighted_score_matches_hand_computation():
    s = ProviderScore(
        tool_name="video/shot",
        provider="h3_local",
        task_fit=1.0,
        output_quality=0.0,
        control=0.0,
        reliability=0.0,
        cost_efficiency=0.0,
        latency=0.0,
        continuity=0.0,
    )
    assert s.weighted_score == pytest.approx(0.30)
    expected = (
        1.0 * DEFAULT_WEIGHTS["task_fit"]
        + 0.0 * DEFAULT_WEIGHTS["output_quality"]
    )
    assert s.weighted_score == pytest.approx(expected)


def test_weighted_score_full_marks_is_one():
    kw = dict.fromkeys(DEFAULT_WEIGHTS, 1.0)
    s = ProviderScore(tool_name="t", provider="p", **kw)
    assert s.weighted_score == pytest.approx(1.0)


def test_score_ordering_descending():
    scored = score_providers("video/shot", _candidates())
    assert [s.provider for s in scored] == ["h3_local", "wan_2_7_maas"]
    assert scored[0].weighted_score >= scored[1].weighted_score


def test_clamp_out_of_range():
    scored = score_providers(
        "video/shot",
        [{"provider": "p", "task_fit": 5.0, "latency": -1.0}],
    )
    assert scored[0].task_fit == 1.0
    assert scored[0].latency == 0.0


def test_invalid_score_raises():
    with pytest.raises(ValueError):
        ProviderScore(tool_name="t", provider="p", task_fit=1.5)


def test_skips_candidates_without_provider():
    scored = score_providers("t", [{"task_fit": 1.0}, {"provider": "ok"}])
    assert [s.provider for s in scored] == ["ok"]


def test_default_scores_applied():
    scored = score_providers(
        "t",
        [{"provider": "p"}],
        default_scores={"reliability": 0.5, "continuity": 0.4},
    )
    assert scored[0].reliability == 0.5
    assert scored[0].continuity == 0.4
    assert scored[0].task_fit == 0.0


def test_explain_mentions_dimensions():
    s = ProviderScore(tool_name="tts/narration", provider="f5", reliability=1.0)
    text = s.explain()
    assert "tts/narration@f5" in text
    assert "weighted=" in text
    assert "reliability=1.00" in text


def test_choose_provider_empty_returns_none():
    assert choose_provider("t", []) is None


def test_choose_provider_writes_decision_log(tmp_path: Path):
    log = tmp_path / "decisions.jsonl"
    winner = choose_provider(
        "video/shot",
        _candidates(),
        decision_log=log,
        reason="预算熔断后回退",
    )
    assert winner is not None
    assert winner.provider == "h3_local"
    records = read_decision_log(log)
    assert len(records) == 1
    rec = records[0]
    assert rec["tool_name"] == "video/shot"
    assert rec["reason"] == "预算熔断后回退"
    assert rec["winner"]["provider"] == "h3_local"
    assert len(rec["candidates"]) == 2
    # 无 PII: 记录字段只含 provider/tool_name/维度分/总分
    assert all(k not in rec for k in ("user_id", "phone", "name"))


def test_read_decision_log_limit(tmp_path: Path):
    log = tmp_path / "decisions.jsonl"
    for i in range(3):
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"i": i}) + "\n")
    records = read_decision_log(log, limit=2)
    assert [r["i"] for r in records] == [1, 2]


def test_read_decision_log_missing_file(tmp_path: Path):
    assert read_decision_log(tmp_path / "nope.jsonl") == []


def test_capability_rows_filter_by_tool():
    rows = [
        CapabilityRow("h3_local", "video/shot", {"task_fit": 0.9}),
        CapabilityRow("f5", "tts/narration", {"task_fit": 0.8}),
    ]
    scored = score_candidates_from_capabilities(rows, "video/shot")
    assert [s.provider for s in scored] == ["h3_local"]
    assert scored[0].task_fit == 0.9


def test_capability_rows_dict_input():
    rows = [
        {"provider": "a", "tool_name": "x", "scores": {"task_fit": 0.5}},
        {"provider": "b", "tool_name": "y", "scores": {"task_fit": 0.7}},
    ]
    scored = score_candidates_from_capabilities(rows, "x")
    assert [s.provider for s in scored] == ["a"]


def test_custom_weights():
    weights = dict.fromkeys(DEFAULT_WEIGHTS, 0.0)
    weights["cost_efficiency"] = 1.0
    scored = score_providers(
        "t",
        [
            {"provider": "cheap", "cost_efficiency": 1.0, "output_quality": 0.0},
            {"provider": "quality", "cost_efficiency": 0.0, "output_quality": 1.0},
        ],
        weights=weights,
    )
    assert scored[0].provider == "cheap"
