"""Phase A 内化测试: failure_registry + replay_trace(来源 dramaclaw)。"""

from __future__ import annotations

import pytest

from hevi.verdict.failure_registry import (
    FailureMode,
    FailureRegistry,
    default_registry,
)
from hevi.verdict.replay_trace import (
    begin_trace,
    finalize,
    load_traces,
    record_gate,
    record_prompt_and_response,
    summary,
)

# ---- failure registry ----

def test_seed_registry_layers():
    reg = default_registry()
    assert len(reg.modes) == len(reg.modes)
    # 每种 layer 至少一条
    for layer in ("identity", "scene", "action", "assembly"):
        assert reg.by_layer(layer), layer


def test_negative_clause_by_layer_deterministic():
    reg = default_registry()
    clause = reg.build_negative_clause("action")
    assert clause.startswith("负面约束:")
    assert "手部结构正常" in clause
    assert reg.build_negative_clause("action") == clause  # 确定性
    assert reg.build_negative_clause("voice") == ""  # 无定义 → 空串


def test_registry_roundtrip_json(tmp_path):
    reg = default_registry()
    p = tmp_path / "defs.json"
    reg.save(p)
    loaded = FailureRegistry.load(p)
    assert loaded.modes.keys() == reg.modes.keys()
    assert loaded.get("bad_hands") == reg.get("bad_hands")


def test_registry_rejects_unknown_layer():
    reg = default_registry()
    with pytest.raises(ValueError):
        reg.add(FailureMode(code="x", layer="nope", description="", negative_clause=""))


def test_failure_hits_top():
    from hevi.verdict.failure_registry import FailureHits

    reg = default_registry()
    hits = FailureHits()
    hits.bump("bad_hands")
    hits.bump("bad_hands")
    hits.bump("face_morph")
    top = hits.top(reg)
    assert top[0][0].code == "bad_hands"
    assert top[0][1] == 2
    assert top[1][0].code == "face_morph"


# ---- replay trace ----

def test_four_stage_handshake(tmp_path):
    h = begin_trace(
        tmp_path,
        source_run_id="run-1",
        ref_type="shot",
        ref_id="shot_0003",
        phase="generation",
    )
    record_prompt_and_response(h, prompt="prompt-abc", response="response-xyz")
    record_gate(h, gate_result={"passed": False}, failure_codes=["bad_hands", "bad_hands"])
    finalize(h, final_status="reworked")

    traces = load_traces(tmp_path)
    assert len(traces) == 1
    t = traces[0]
    assert t["status"] == "done"
    assert t["final_status"] == "reworked"
    assert t["prompt_version"] == t["prompt_version"]  # 有指纹
    assert t["failure_codes"] == ["bad_hands"]  # 去重保序
    # 原文落盘(可回放)
    artifacts = list((tmp_path / "artifacts").glob("*.prompt.txt"))
    assert len(artifacts) == 1
    assert artifacts[0].read_text(encoding="utf-8") == "prompt-abc"


def test_summary_counts(tmp_path):
    h1 = begin_trace(tmp_path, source_run_id="r1", ref_type="episode", ref_id="e1", phase="gen")
    finalize(h1, final_status="accepted")
    h2 = begin_trace(tmp_path, source_run_id="r1", ref_type="episode", ref_id="e1", phase="gen")
    record_gate(h2, gate_result={}, failure_codes=["face_morph"])
    finalize(h2, final_status="reworked")

    s = summary(load_traces(tmp_path))
    assert s["total"] == 2
    assert s["by_status"]["accepted"] == 1
    assert s["by_status"]["reworked"] == 1
    assert s["failure_frequency"]["face_morph"] == 1


def test_replay_trace_best_effort_json(tmp_path):
    # 手写一个坏 json,load_traces 跳过不崩
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    assert load_traces(tmp_path) == []
