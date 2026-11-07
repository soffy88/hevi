"""Tests for the HyperFrames engine-discipline graft (A1/A2/A3/B1/B3)."""

import hashlib

import pytest

from hevi.capabilities.beats_schema_gate import check_beats
from hevi.capabilities.deterministic_render_gate import (
    check_lock_change,
    check_render_plan,
    check_render_reproducibility,
    frame_time,
)
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.frame_adapter_contract import (
    check_adapter_plan,
    check_frame_sequence,
    check_renderer_protocols,
)
from hevi.capabilities.frozen_picture_gate import (
    check_blur_settle,
    check_frozen_picture,
    frame_diff,
)
from hevi.capabilities.render_lint import lint_composition, lint_template
from hevi.video.hf_adapter import FrameAdapter, frame_time_seconds, settle_capture


def _good_adapter():
    return {
        "protocol": "__hf",
        "methods": ["getDurationFrames", "seekFrame", "destroy"],
        "settle": {"mode": "confirmation", "max_wait_ms": 1000},
        "arbitrary_order": True,
    }


# --- A1: frame adapter contract -------------------------------------------

def test_adapter_plan_pass():
    result = check_adapter_plan({"adapter": _good_adapter()})
    assert result["verdict"] == "pass"
    assert result["issues"] == []


def test_adapter_plan_missing_method_fails():
    adapter = _good_adapter()
    adapter["methods"] = ["seekFrame"]
    result = check_adapter_plan({"adapter": adapter})
    assert result["verdict"] == "fail"
    assert any(i["code"] == "method_missing" for i in result["issues"])


def test_adapter_plan_fixed_wait_fails():
    adapter = _good_adapter()
    adapter["settle"] = {"mode": "fixed_wait", "max_wait_ms": 40}
    result = check_adapter_plan({"adapter": adapter})
    assert result["verdict"] == "fail"
    assert any(i["code"] == "settle_not_confirmed" for i in result["issues"])


def test_adapter_plan_legacy_protocol_fails_without_shim():
    adapter = _good_adapter()
    adapter["protocol"] = "__timelines"
    result = check_adapter_plan({"adapter": adapter})
    assert result["verdict"] == "fail"
    assert any(i["code"] == "legacy_protocol" for i in result["issues"])


def test_adapter_plan_legacy_shim_deprecated_warning():
    adapter = _good_adapter()
    adapter["protocol"] = "HF"
    result = check_adapter_plan({"adapter": adapter}, allow_legacy_shim=True)
    assert result["verdict"] == "pass"
    assert any(w["code"] == "legacy_protocol_deprecated" for w in result["warnings"])


def test_renderer_protocols_must_converge():
    result = check_renderer_protocols(
        [
            {"name": "csk", "protocol": "__hf"},
            {"name": "seek", "protocol": "HF"},
        ]
    )
    assert result["verdict"] == "fail"
    assert result["issues"][0]["name"] == "seek"
    assert check_renderer_protocols([{"name": "a", "protocol": "__hf"}])["verdict"] == "pass"


def test_frame_sequence_unsettled_fails_and_reproducible_passes():
    frames = [
        {"frame": 0, "sha256": "aa", "settled": True},
        {"frame": 1, "sha256": "bb", "settled": False},
    ]
    assert check_frame_sequence(frames)["verdict"] == "fail"
    assert check_frame_sequence([{"frame": 0, "sha256": "aa", "settled": True}])["verdict"] == "pass"
    dup = [
        {"frame": 0, "sha256": "aa", "settled": True},
        {"frame": 0, "sha256": "cc", "settled": True},
    ]
    result = check_frame_sequence(dup)
    assert any(i["code"] == "frame_not_reproducible" for i in result["issues"])


def test_hf_adapter_settle_capture_and_frame_time():
    values = iter([b"a", b"b", b"c", b"c", b"c"])

    def capture():
        return next(values)

    # First stable pair is (c, c): settle returns the settled frame.
    assert settle_capture(capture, max_attempts=5) == b"c"

    counter = {"n": 0}

    def never_settles():
        counter["n"] += 1
        return f"frame-{counter['n']}".encode()

    with pytest.raises(RuntimeError):
        settle_capture(never_settles, max_attempts=3)
    assert frame_time_seconds(7, 24) == 7 / 24
    adapter = FrameAdapter(10, 24, seek=lambda n: None, capture=lambda: b"f")
    assert adapter.get_duration_frames() == 10
    assert adapter.seek_frame(3) == b"f"


# --- A2: deterministic render gate ----------------------------------------

def _good_plan():
    return {
        "fps": 24,
        "width": 1080,
        "height": 1920,
        "locked_before_frame_0": True,
        "wall_clock_sources": [],
        "randomness": {"seeded": True, "seed": 7},
        "fetch_during_render": False,
        "atomic_capture": True,
        "encoder": {"chunk_order": "sequential", "hash_check": True},
    }


def test_render_plan_pass_and_wall_clock_fails():
    assert check_render_plan(_good_plan())["verdict"] == "pass"
    plan = _good_plan()
    plan["wall_clock_sources"] = ["Date.now"]
    assert check_render_plan(plan)["verdict"] == "fail"
    plan = _good_plan()
    plan["randomness"] = {"seeded": False}
    assert any(
        i["code"] == "unseeded_random" for i in check_render_plan(plan)["issues"]
    )
    plan = _good_plan()
    plan["atomic_capture"] = False
    assert any(
        i["code"] == "capture_not_atomic" for i in check_render_plan(plan)["issues"]
    )


def test_frame_time_integer_math():
    from fractions import Fraction

    assert frame_time(25, 24) == Fraction(25, 24)
    assert frame_time(0, 30) == 0
    with pytest.raises(CapabilityError):
        frame_time(1, 0)


def test_reproducibility_and_lock():
    hashes = [hashlib.sha256(bytes([i])).hexdigest() for i in range(3)]
    assert check_render_reproducibility(hashes, list(hashes))["verdict"] == "pass"
    other = list(hashes)
    other[1] = "different"
    result = check_render_reproducibility(hashes, other)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["frame"] == 1
    assert check_lock_change({"lock_changed": True}, 0)["verdict"] == "pass"
    assert check_lock_change({"lock_changed": True}, 5)["verdict"] == "fail"


# --- A3: render lint --------------------------------------------------------

def test_lint_template_wall_clock_random_fetch():
    assert lint_template("const t = frame / fps;")["verdict"] == "pass"
    result = lint_template("const now = Date.now();")
    assert any(i["code"] == "wall_clock_date_now" for i in result["issues"])
    result = lint_template("const r = Math.random();")
    assert any(i["code"] == "unseeded_random" for i in result["issues"])
    assert lint_template("const r = mulberry32(seed)();")["verdict"] == "pass"
    result = lint_template("await fetch('/x.json');")
    assert any(i["code"] == "render_fetch" for i in result["issues"])
    assert lint_template("await fetch('/x.json');", fetch_phase="setup")["verdict"] == "pass"
    result = lint_template("const fps = 24;\nconst fps = 30;")
    assert any(i["code"] == "variable_relock" for i in result["issues"])


def test_lint_composition_missing_attributes():
    html = '<div class="clip" data-start="0" data-duration="2"></div>'
    result = lint_composition(html)
    assert result["verdict"] == "fail"
    assert any(i["attribute"] == "data-track-index" for i in result["issues"])
    good = '<div class="clip" data-start="0" data-duration="2" data-track-index="0"></div>'
    assert lint_composition(good)["verdict"] == "pass"


# --- B1: frozen picture + blur settle ---------------------------------------

def test_frozen_picture_declared_and_unexpected():
    frames = [
        {"frame": 0, "diff_to_prev": 10.0},
        {"frame": 1, "diff_to_prev": 0.0},
        {"frame": 2, "diff_to_prev": 0.0},
        {"frame": 3, "diff_to_prev": 5.0},
    ]
    result = check_frozen_picture(frames, declared_frozen=[[1, 2]])
    assert result["verdict"] == "pass"
    assert result["frozen_runs"] == [{"start": 1, "end": 2}]
    result = check_frozen_picture(frames)
    assert any(i["code"] == "unexpected_frozen" for i in result["issues"])
    changing = [
        {"frame": 1, "diff_to_prev": 3.0},
        {"frame": 2, "diff_to_prev": 4.0},
    ]
    result = check_frozen_picture(changing, declared_frozen=[[1, 2]])
    assert any(i["code"] == "frozen_not_frozen" for i in result["issues"])
    assert frame_diff(b"\x00\x00", b"\x00\x00") == 0.0
    assert frame_diff(b"\x00", b"\xff") == 255.0


def test_blur_settle_pending_and_fail():
    frames = [{"frame": 0, "blur_score": 0.9, "settled": False, "waited_ms": 100.0}]
    result = check_blur_settle(frames, settle_deadline_ms=1000.0)
    assert result["verdict"] == "pending"
    assert result["pending_frames"] == [0]
    frames[0]["waited_ms"] = 1500.0
    result = check_blur_settle(frames, settle_deadline_ms=1000.0)
    assert result["verdict"] == "fail"
    assert any(i["code"] == "blur_not_settled" for i in result["issues"])
    settled = [{"frame": 0, "blur_score": 0.9, "settled": True, "waited_ms": 100.0}]
    assert check_blur_settle(settled)["verdict"] == "pass"
    clear = [{"frame": 0, "blur_score": 0.1, "settled": False, "waited_ms": 0.0}]
    assert check_blur_settle(clear)["verdict"] == "pass"


# --- B3: beats schema ---------------------------------------------------------

def test_beats_schema_good_and_missing_field_named():
    content = {
        "name": "demo",
        "beats": [
            {"type": "chapter", "title": "Intro", "num": "01"},
            {"type": "list", "head": "Points", "items": [["a", "1"], ["b", "2"]]},
            {"type": "stat", "value": "42", "unit": "items"},
        ],
    }
    assert check_beats(content)["verdict"] == "pass"
    bad = {"name": "demo", "beats": [{"type": "list", "title": "Wrong field"}]}
    result = check_beats(bad)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["code"] == "missing_field"
    assert result["issues"][0]["field"] == "head"
    assert result["issues"][0]["beat_index"] == 0
    bare = {
        "name": "demo",
        "beats": [{"type": "list", "head": "H", "items": ["only-label"]}],
    }
    result = check_beats(bare)
    assert result["verdict"] == "pass"
    assert any(w["code"] == "bare_string_item" for w in result["warnings"])
    unknown = {"beats": [{"type": "video"}]}
    assert check_beats(unknown)["issues"][0]["code"] == "unknown_beat_type"
    with pytest.raises(CapabilityError):
        check_beats({"name": "no beats"})
    with pytest.raises(CapabilityError):
        check_beats([{"type": "list"}])
