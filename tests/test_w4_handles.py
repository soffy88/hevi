"""W4: handles in specs + PixStag packages + beat-dependent tails.

Offline, pure functions only: no paid chain, no network.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from hevi.production.shot_spec import ShotSpec
from hevi.production.timeline_ir import (
    TimelineClip,
    TimelineIRError,
    TrackKind,
    validate_timeline,
)
from hevi.storyfilm.pipeline import (
    build_pixstag_package,
    compute_pixstag_timing,
    infer_beat_kind,
    tail_for_beat,
)

DRAFT = {"title": "t", "hook": "h", "characters": [], "beats": []}


def _shot(**over):
    base = {
        "shot_id": "S01",
        "first_frame": "/job/images/shot_01.png",
        "motion_prompt": "slow push-in",
        "duration_s": 3.5,
        "narration": "n",
    }
    return {**base, **over}


def _pkg(shots):
    return build_pixstag_package(
        premise="p", draft=DRAFT, shots=shots, aspect="9:16",
        narration_path=Path("/job/n.wav"), alignment_path=Path("/job/a.json"),
    )


# -- 1. ShotSpec handles ----------------------------------------------------

def test_shotspec_handles_default_zero_backwards_compatible():
    spec = ShotSpec(duration=4.0)
    assert spec.handle_head_s == 0.0 and spec.handle_tail_s == 0.0
    assert spec.requested_generation_duration_s() == 4.0
    assert spec.to_dict()["handle_head_s"] == 0.0


def test_shotspec_requested_generation_duration_adds_handles():
    spec = ShotSpec(duration=4.0, handle_head_s=0.5, handle_tail_s=0.7)
    assert spec.requested_generation_duration_s() == pytest.approx(5.2)
    # explicit use duration overrides spec.duration
    assert spec.requested_generation_duration_s(2.0) == pytest.approx(3.2)


def test_shotspec_requested_duration_unknown_use_is_none():
    assert ShotSpec(handle_head_s=0.5).requested_generation_duration_s() is None


def test_shotspec_negative_handle_rejected():
    with pytest.raises(ValidationError):
        ShotSpec(duration=1.0, handle_head_s=-0.1)
    with pytest.raises(ValidationError):
        ShotSpec(duration=1.0, handle_tail_s=-1.0)


# -- 2. PixStag package timing ----------------------------------------------

def test_pixstag_timing_default_handles_and_ceil():
    t = compute_pixstag_timing(3.5)
    assert t == {
        "use_duration_s": 3.5, "handle_head_s": 0.5, "handle_tail_s": 0.5,
        "source_in_s": 0.5, "duration": 5, "handles_clipped": False,
    }


def test_pixstag_timing_min_clamp_keeps_handles():
    t = compute_pixstag_timing(1.0)
    assert t["duration"] == 4 and t["handles_clipped"] is False
    assert t["source_in_s"] == 0.5


def test_pixstag_timing_max_clamp_preserves_use_and_clips_handles():
    t = compute_pixstag_timing(29.5)
    assert t["duration"] == 30
    assert t["handles_clipped"] is True
    assert t["handle_head_s"] == 0.5 and t["handle_tail_s"] == 0.0
    assert t["source_in_s"] == 0.5
    over = compute_pixstag_timing(31.0)
    assert over["duration"] == 30 and over["handles_clipped"] is True
    assert over["handle_head_s"] == 0.0 and over["handle_tail_s"] == 0.0


def test_pixstag_timing_rejects_bad_input():
    from hevi.storyfilm.pipeline import StoryFilmError

    with pytest.raises(StoryFilmError):
        compute_pixstag_timing(0)
    with pytest.raises(StoryFilmError):
        compute_pixstag_timing(3.0, handle_head_s=-0.5)


def test_build_pixstag_package_carries_handle_fields():
    only = _pkg([_shot()])["shots"][0]
    assert only["duration_s"] == 3.5  # used duration, backwards compatible
    assert only["use_duration_s"] == 3.5
    assert only["duration"] == 5  # ceil(3.5 + 0.5 + 0.5)
    assert only["handle_head_s"] == 0.5 and only["handle_tail_s"] == 0.5
    assert only["source_in_s"] == 0.5
    assert only["handles_clipped"] is False


def test_build_pixstag_package_shot_handles_win_over_defaults():
    only = _pkg([_shot(handle_head_s=1.0, handle_tail_s=0.0)])["shots"][0]
    assert only["handle_head_s"] == 1.0 and only["handle_tail_s"] == 0.0
    assert only["source_in_s"] == 1.0
    assert only["duration"] == 5  # ceil(3.5 + 1.0 + 0.0)


# -- 3. Beat-dependent tails --------------------------------------------------

def test_tail_mapping_explicit_beat_type():
    assert tail_for_beat({"beat_type": "reaction"}) == 0.8
    assert tail_for_beat({"beat_type": "emotion"}) == 0.8
    assert tail_for_beat({"beat_type": "result"}) == 0.5
    assert tail_for_beat({"beat_type": "establishing"}) == 0.35
    assert tail_for_beat({}) == 0.35


def test_tail_last_shot_floor():
    assert tail_for_beat({}, is_last=True) == 1.2
    assert tail_for_beat({"beat_type": "reaction"}, is_last=True) == 1.2


def test_tail_inference_from_existing_fields():
    close_up = {"motion_prompt": "static warm close-up", "visual_en": "a kitten",
                "narration": "咪咪看着家门。"}
    assert infer_beat_kind(close_up) == "reaction"
    assert tail_for_beat(close_up) == 0.8
    result = {"motion_prompt": "slow push-in", "visual_en": "a doorway",
              "narration": "终于，咪咪回到了家。"}
    assert infer_beat_kind(result) == "result"
    assert tail_for_beat(result) == 0.5
    plain = {"motion_prompt": "gentle pan right", "visual_en": "a lamp",
             "narration": "远处有一盏灯。"}
    assert infer_beat_kind(plain) == "default"
    assert tail_for_beat(plain) == 0.35


# -- 4. TimelineClip source duration -------------------------------------------

def _clip(**over):
    base = dict(clip_id="v1", track=TrackKind.VIDEO, source_path="a.mp4",
                duration_ms=2000, source_in_ms=500)
    return TimelineClip(**{**base, **over})


def test_timeline_clip_without_source_duration_is_unvalidated():
    clip = _clip()
    assert clip.source_duration_ms is None
    assert clip.source_out_ms == 2500
    assert clip.to_dict()["source_duration_ms"] is None


def test_timeline_clip_within_source_duration_ok():
    clip = _clip(source_duration_ms=2500)
    assert clip.source_out_ms == 2500


def test_timeline_clip_exceeding_source_duration_rejected():
    with pytest.raises(TimelineIRError, match="EXCEEDS_SOURCE_DURATION"):
        _clip(source_duration_ms=2499)
    with pytest.raises(TimelineIRError):
        _clip(source_duration_ms=0)
    with pytest.raises(TimelineIRError):
        _clip(source_duration_ms=2500.0)  # float ms rejected, not coerced


def test_timeline_source_duration_round_trips_through_validation():
    payload = {
        "project_id": "p", "timeline_id": "t", "revision_id": "r",
        "canvas": {"width": 720, "height": 1280, "fps": 24},
        "clips": [{
            "clip_id": "v1", "track": "video", "source_path": "a.mp4",
            "duration_ms": 2000, "start_ms": 0, "order": 0,
            "source_in_ms": 500, "source_duration_ms": 4000,
        }],
        "source_assets": ["a.mp4"],
    }
    tl = validate_timeline(payload)
    assert tl.clips[0].source_duration_ms == 4000
    restored = validate_timeline(tl.to_dict())
    assert restored.content_hash() == tl.content_hash()
