"""Tests for video.gesture_risk_gate: tiers, vocabulary, range, anchors, opening."""

from __future__ import annotations

import hevi.capabilities as caps
from hevi.capabilities.gesture_risk_gate import gate_gestures


def _beat(i: int, name: str, tier: str, zone: str, anchor: str) -> dict:
    return {
        "start_sec": float(i * 2), "end_sec": float(i * 2 + 2),
        "gesture": {"name": name, "tier": tier, "zone": zone, "anchor": anchor},
    }


def _plan(beats: list, **extra) -> dict:
    plan = {
        "opening_structure": "person_first",
        "first_frame": "person",
        "beats": beats,
    }
    plan.update(extra)
    return plan


def _details(report: dict) -> list:
    return [p["detail"] for p in report["problems"]]


def test_low_and_medium_pass() -> None:
    report = gate_gestures(_plan([
        _beat(0, "low_open", "low", "off_frame", "Do you also...?"),
        _beat(1, "symmetric_open", "medium", "chest", "I summed it up."),
    ]))
    assert report["verdict"] == "pass"
    assert report["tier_counts"] == {"low": 1, "medium": 1, "high": 0}
    assert report["distinct_gesture_count"] == 2


def test_flat_beat_shape_passes() -> None:
    plan = _plan([{
        "start_sec": 0.0, "end_sec": 2.0, "gesture": "low_open",
        "tier": "low", "zone": "low", "anchor": "Do you also...?",
    }])
    assert gate_gestures(plan)["verdict"] == "pass"


def test_high_tier_warns_with_downgrade_but_does_not_fail() -> None:
    report = gate_gestures(_plan([
        _beat(0, "two_index", "high", "chest_to_cheek", "First, second."),
    ]))
    assert report["verdict"] == "pass"
    assert len(report["warnings"]) == 1
    assert report["warnings"][0]["kind"] == "high_tier_gesture"
    assert len(report["suggestions"]) == 1
    assert report["suggestions"][0]["gesture"] == "two_index"
    assert "low-tier" in report["suggestions"][0]["suggestion"]


def test_untiered_gesture_fails_and_is_named() -> None:
    beat = _beat(0, "mystery", "low", "chest", "Hello.")
    del beat["gesture"]["tier"]
    report = gate_gestures(_plan([beat]))
    assert report["verdict"] == "fail"
    assert any("no tier" in d for d in _details(report))
    assert any("mystery" in d for d in _details(report))


def test_unknown_tier_fails() -> None:
    report = gate_gestures(_plan([
        _beat(0, "weird", "extreme", "chest", "Hello."),
    ]))
    assert report["verdict"] == "fail"
    assert any("no tier" in d for d in _details(report))


def test_more_than_seven_distinct_gestures_fails_naming_extras() -> None:
    beats = [_beat(i, f"g{i}", "low", "low", f"Line {i}.") for i in range(8)]
    report = gate_gestures(_plan(beats))
    assert report["verdict"] == "fail"
    assert report["distinct_gesture_count"] == 8
    assert any("g7" in d for d in _details(report))
    assert any("vocabulary" in p["kind"] or "distinct gestures" in p["detail"]
               for p in report["problems"])


def test_seven_distinct_gestures_passes() -> None:
    beats = [_beat(i, f"g{i}", "low", "low", f"Line {i}.") for i in range(7)]
    assert gate_gestures(_plan(beats))["verdict"] == "pass"


def test_repeated_gesture_counts_once() -> None:
    beats = [_beat(i, "low_open", "low", "low", f"Line {i}.") for i in range(3)]
    report = gate_gestures(_plan(beats))
    assert report["distinct_gesture_count"] == 1
    assert report["verdict"] == "pass"


def test_zone_outside_chest_to_cheek_fails() -> None:
    report = gate_gestures(_plan([
        _beat(0, "overhead", "medium", "above_head", "Look up."),
    ]))
    assert report["verdict"] == "fail"
    assert any("above_head" in d for d in _details(report))


def test_zone_inside_band_passes() -> None:
    for zone in ("off_frame", "low", "chest", "chest_to_cheek", "cheek"):
        report = gate_gestures(_plan([
            _beat(0, "g", "low", zone, "Line."),
        ]))
        assert report["verdict"] == "pass", zone


def test_gesture_without_anchor_fails() -> None:
    beat = _beat(0, "low_open", "low", "low", "")
    report = gate_gestures(_plan([beat]))
    assert report["verdict"] == "fail"
    assert any("no anchor" in d for d in _details(report))


def test_evidence_first_requires_evidence_frame_and_seam_note() -> None:
    good = _plan(
        [_beat(0, "low_open", "low", "low", "Look at this.")],
        opening_structure="evidence_first", first_frame="evidence",
        seam_cover_note="Cut away on the result shot so the seam is covered.",
    )
    assert gate_gestures(good)["verdict"] == "pass"
    bad_frame = _plan(
        [_beat(0, "low_open", "low", "low", "Look at this.")],
        opening_structure="evidence_first", first_frame="person",
        seam_cover_note="Cut away on the result shot.",
    )
    assert gate_gestures(bad_frame)["verdict"] == "fail"
    assert any("first_frame" in d for d in _details(gate_gestures(bad_frame)))
    no_note = _plan(
        [_beat(0, "low_open", "low", "low", "Look at this.")],
        opening_structure="evidence_first", first_frame="evidence",
    )
    assert gate_gestures(no_note)["verdict"] == "fail"
    assert any("seam_cover_note" in d for d in _details(gate_gestures(no_note)))


def test_person_first_with_wrong_frame_fails() -> None:
    report = gate_gestures(_plan(
        [_beat(0, "low_open", "low", "low", "Hello.")],
        first_frame="evidence",
    ))
    assert report["verdict"] == "fail"


def test_missing_opening_structure_fails() -> None:
    plan = {"beats": [_beat(0, "low_open", "low", "low", "Hello.")]}
    report = gate_gestures(plan)
    assert report["verdict"] == "fail"
    assert any("opening_structure" in d for d in _details(report))


def test_capability_registered() -> None:
    assert "video.gesture_risk_gate" in caps.names()
