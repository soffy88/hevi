"""Tests for video.motion_beat_chart: thesis, completeness, 80% gate."""

from __future__ import annotations

from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.motion_beat_chart import (
    gate_chart,
    to_downstream_plan,
)

THESIS = {
    "visual_metaphor": "a seed grows into a tree",
    "from_state": "one seed on empty soil",
    "to_state": "a full tree with branches",
    "claim": "small habits compound",
}


def _beat(i: int, kind: str) -> dict:
    return {
        "start_sec": float(i * 2), "end_sec": float(i * 2 + 2),
        "action": f"beat {i} moves", "mover": "seed",
        "state_change": "the seed grows taller",
        "camera": "static", "text": "grow", "asset": "seed.png",
        "change_kind": kind,
    }


def _chart(kinds: list[str]) -> dict:
    return {"thesis": dict(THESIS), "beats": [_beat(i, k) for i, k in enumerate(kinds)]}


def test_four_of_five_real_passes_at_exactly_80_percent() -> None:
    report = gate_chart(_chart(["grow", "gather", "draw_path", "morph", "fade_in"]))
    assert report["real_change_ratio"] == 0.8
    assert report["verdict"] == "pass"


def test_below_80_percent_fails_and_names_fade_beats() -> None:
    report = gate_chart(_chart(["grow", "gather", "morph", "fade_in", "slide_in"]))
    assert report["real_change_ratio"] == 0.6
    assert report["verdict"] == "fail"
    assert report["non_real_beats"] == [3, 4]
    assert any(p["kind"] == "anti_still_picture" for p in report["problems"])


def test_missing_thesis_and_missing_field_fail() -> None:
    chart = _chart(["grow"] * 5)
    chart["thesis"] = {"visual_metaphor": "", "from_state": "a", "to_state": "b", "claim": "c"}
    report = gate_chart(chart)
    assert report["verdict"] == "fail"
    assert any(p["kind"] == "thesis" for p in report["problems"])
    bad = _chart(["grow"] * 5)
    del bad["beats"][0]["mover"]
    report2 = gate_chart(bad)
    assert report2["verdict"] == "fail"
    assert any("mover" in p["detail"] for p in report2["problems"])


def test_emoji_text_and_empty_beats() -> None:
    chart = _chart(["grow"] * 5)
    chart["beats"][0]["text"] = "grow \U0001f600"
    report = gate_chart(chart)
    assert report["verdict"] == "fail"
    with pytest.raises(CapabilityError):
        gate_chart({"thesis": dict(THESIS), "beats": []})


def test_downstream_plan_is_plain_data_for_renderers(tmp_path: Path) -> None:
    plan = to_downstream_plan(_chart(["grow", "gather", "draw_path", "morph", "fade_in"]))
    assert plan["gate_verdict"] == "pass"
    assert len(plan["beats"]) == 5
    assert plan["beats"][0]["mover"] == "seed"
    assert plan["beats"][0]["change_kind"] == "grow"
    assert plan["thesis"]["claim"] == "small habits compound"


def test_registry_gate(tmp_path: Path) -> None:
    cap = caps.get("video.motion_beat_chart")
    result = cap.render_safe(
        {"chart": _chart(["grow", "gather", "draw_path", "morph", "fade_in"])},
        tmp_path / "out", duration=0.0, aspect="16:9", seed=1,
    )
    assert result.qa["verdict"] == "pass"
    assert result.qa["real_change_ratio"] == 0.8
