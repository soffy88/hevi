"""Tests for deferred animation-skills batch B: word-timing warp
contract (B3) and minimal line motif schema (B4). Contract
layer only; nothing renders.
"""

import pytest

from hevi.capabilities import minimal_line_motif_schema as b4
from hevi.capabilities import word_timing_warp_contract as b3
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import contains


def _words(scale=1.0, words=("hello", "world", "again")):
    out = []
    t = 0.0
    for word in words:
        out.append({"word": word, "start_s": t, "end_s": t + 0.4 * scale})
        t += 0.5 * scale
    return out


def _warp_plan(**overrides):
    plan = {
        "language": "en",
        "timing_model": {"name": "sherpa-parakeet", "english_only": True},
        "reference_words": _words(),
        "new_take_words": _words(scale=2.0),
        "shots": [
            {"id": "s1", "ref_start_s": 0.0, "ref_end_s": 0.4},
            {"id": "s2", "ref_start_s": 0.5, "ref_end_s": 1.4},
        ],
    }
    plan.update(overrides)
    return plan


def test_warp_contract_positive():
    contract = b3.compile_word_timing_warp_contract(_warp_plan())
    assert contract["words_unchanged"] is True
    assert contract["word_count"] == 3
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    s1, s2 = contract["shots"]
    assert s1["new_start_s"] == pytest.approx(0.0)
    assert s1["new_end_s"] == pytest.approx(0.8)
    assert s2["new_start_s"] == pytest.approx(1.0)
    assert s2["new_end_s"] == pytest.approx(2.8)


def test_warp_contract_script_change_refused():
    with pytest.raises(CapabilityError, match="script changed"):
        b3.compile_word_timing_warp_contract(_warp_plan(
            new_take_words=_words(words=("hello", "brave", "again")),
        ))
    with pytest.raises(CapabilityError, match="word boundaries"):
        b3.compile_word_timing_warp_contract(_warp_plan(shots=[
            {"id": "s1", "ref_start_s": 0.2, "ref_end_s": 0.4},
        ]))
    with pytest.raises(CapabilityError):
        b3.compile_word_timing_warp_contract(_warp_plan(shots=[
            {"id": "s1", "ref_start_s": 0.0, "ref_end_s": 9.9},
        ]))


def test_warp_contract_english_model_never_chinese():
    with pytest.raises(CapabilityError, match="English-only"):
        b3.compile_word_timing_warp_contract(_warp_plan(
            language="zh-CN",
            timing_model={"name": "sherpa-parakeet", "english_only": True},
        ))
    with pytest.raises(CapabilityError, match="English-only"):
        b3.compile_word_timing_warp_contract(_warp_plan(
            language="zh",
            timing_model={"name": "Parakeet", "english_only": False},
        ))
    with pytest.raises(CapabilityError):
        b3.compile_word_timing_warp_contract(_warp_plan(
            timing_model={"name": "some-model"},
        ))


def _motif_plan(**overrides):
    plan = {
        "motif": "steps_dot_ring",
        "meaning_kind": "steady_accumulation",
        "lines": ["small steps, every day.", "and it compounds."],
        "steps": 5,
        "light": True,
    }
    plan.update(overrides)
    return plan


def test_motif_schema_positive():
    contract = b4.compile_minimal_line_motif(_motif_plan())
    assert contract["motif"] == "steps_dot_ring"
    assert len(contract["stages"]) == 5
    assert contract["stages"][-1]["track_ring"] is True
    assert contract["stages"][-1]["spark"] is True
    assert contract["stages"][-1]["line_shown"] == "and it compounds."
    assert contract["stages"][0]["line_shown"] == "small steps, every day."
    assert contract["stages"][0]["track_ring"] is False
    assert contract["palette"] == "black_on_white"
    assert contract["executed_here"] is False
    assert contract["output_file"] is None


def test_motif_schema_text_and_range_rules():
    with pytest.raises(CapabilityError):
        b4.compile_minimal_line_motif(_motif_plan(steps=2))
    with pytest.raises(CapabilityError):
        b4.compile_minimal_line_motif(_motif_plan(steps=8))
    with pytest.raises(CapabilityError):
        b4.compile_minimal_line_motif(_motif_plan(
            lines=["Small steps, every day."]))
    with pytest.raises(CapabilityError):
        b4.compile_minimal_line_motif(_motif_plan(
            lines=["small steps, every day"]))
    with pytest.raises(CapabilityError):
        b4.compile_minimal_line_motif(_motif_plan(
            lines=["small steps, every day!"]))
    with pytest.raises(CapabilityError):
        b4.compile_minimal_line_motif(_motif_plan(
            meaning_kind="epic_battle"))
    with pytest.raises(CapabilityError):
        b4.compile_minimal_line_motif(_motif_plan(lines=[
            "small steps, every day.", "and it compounds.",
            "one more line.",
        ]))


def test_batch5_registered():
    assert contains("video.word_timing_warp_contract")
    assert contains("video.minimal_line_motif_schema")
