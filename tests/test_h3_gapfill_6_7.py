"""Tests for H3 exemplar gapfill 6+7: beat floor policy and handoff_kind.

Gap 6: the 1.0s default beat floor rejects five exemplar segments'
sub-second match-on-action opening beats (0.573-0.8s). The remedy
is an explicit reviewed floor (with a recorded reason) or merging
the short beat into its neighbour with an audit trail. The default
floor itself never moves.

Gap 7: the segment match schema gains ``handoff_kind`` (closed
vocabulary); element/fabric hand-offs name their element in
``element_name`` and never stuff it into ``direction``.

Placeholder bindings reuse the v2 empirical run's placeholder
files and real sha256 of those placeholder bytes; no real Picture
1-3 or audio bytes exist. Structure evidence only.
"""

import hashlib

import pytest

from hevi.capabilities.beat_floor_policy import (
    DEFAULT_BEAT_FLOOR_S,
    authorize_beat_floor,
    check_beat_floor,
    merge_short_beats,
    resolve_beat_floor,
)
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.prompt_compiler import (
    MIN_BEAT_S,
    compile_generation_ready_episode,
)
from hevi.capabilities.segment_match_gate import (
    HANDOFF_KINDS,
    authorize_segment_match,
    check_segment_match,
)

PIC_SHA = {
    "pic1.jpg": "e113a8307382f20f796ec302507446a43f45a12e8084fd816f918e41a24800d6",
    "pic2.jpg": "ae9835bd4f398cc1a3310e099d92beaf90b50ff6ac0b6c97140382f9de044b8b",
    "pic3.jpg": "9ff359dcda724dcfad96b97ac35228f127b644e1218a890dfc99ca1fcc6612ac",
}
P1 = "/data/soffy/h3-exemplar/pic1.jpg"
P2 = "/data/soffy/h3-exemplar/pic2.jpg"
P3 = "/data/soffy/h3-exemplar/pic3.jpg"
ANCHORS = {
    "heroine": {
        "name": "heroine",
        "confirmed": True,
        "look": "purple xianxia costume, silver hairpin",
        "file": P1,
        "reference_file": P1,
        "sha256": PIC_SHA["pic1.jpg"],
    }
}
BINDINGS = {
    1: {"file": P1, "sha256": PIC_SHA["pic1.jpg"]},
    2: {"file": P2, "sha256": PIC_SHA["pic2.jpg"]},
    3: {"file": P3, "sha256": PIC_SHA["pic3.jpg"]},
}


def _sha(name):
    return hashlib.sha256(name.encode()).hexdigest()


def _cam(height, distance, axis, path):
    return {"height": height, "distance": distance,
            "optical_axis": axis, "path": path}


# ---------------------------------------------------------------- gap 6: floor


def test_default_floor_equals_compiler_min_beat():
    assert DEFAULT_BEAT_FLOOR_S == MIN_BEAT_S == 1.0


def test_default_floor_rejects_subsecond_beat():
    beats = [{"t_start_s": 0.0, "t_end_s": 0.8, "action": "hand crosses lens"}]
    report = check_beat_floor(beats)
    assert report["verdict"] == "fail"
    assert report["floor_s"] == 1.0
    assert report["reviewed"] is False
    assert any(i["code"] == "beat_under_floor" for i in report["issues"])
    with pytest.raises(CapabilityError):
        authorize_beat_floor(beats)


def test_default_floor_accepts_one_second_beat():
    beats = [{"t_start_s": 0.0, "t_end_s": 1.0, "action": "hold"}]
    assert check_beat_floor(beats)["verdict"] == "pass"


def test_reviewed_lower_floor_needs_reason():
    beats = [{"t_start_s": 0.0, "t_end_s": 0.8, "action": "hand crosses lens"}]
    resolved = resolve_beat_floor({"beat_floor_s": 0.5})
    assert resolved["ok"] is False
    assert any(i["code"] == "floor_review_reason_missing"
               for i in resolved["issues"])
    report = check_beat_floor(beats, {"beat_floor_s": 0.5})
    assert report["verdict"] == "fail"


def test_reviewed_lower_floor_with_reason_passes():
    beats = [{"t_start_s": 0.0, "t_end_s": 0.8, "action": "hand crosses lens"}]
    policy = {
        "beat_floor_s": 0.5,
        "reason": "match-on-action opening beat, exemplar seg02 0.8s",
    }
    report = check_beat_floor(beats, policy)
    assert report["verdict"] == "pass", report["issues"]
    assert report["reviewed"] is True
    assert report["reason"] == policy["reason"]
    assert report["floor_s"] == 0.5


def test_reviewed_floor_still_rejects_below_reviewed_floor():
    beats = [{"t_start_s": 0.0, "t_end_s": 0.4, "action": "blink"}]
    policy = {"beat_floor_s": 0.5, "reason": "match-on-action opening"}
    assert check_beat_floor(beats, policy)["verdict"] == "fail"


def test_invalid_floor_values_fail():
    for bad in (0, -1.0, "fast", None):
        resolved = resolve_beat_floor({"beat_floor_s": bad, "reason": "x"})
        assert resolved["ok"] is False, bad
        assert any(i["code"] == "invalid_beat_floor"
                   for i in resolved["issues"])
    assert resolve_beat_floor("not an object")["ok"] is False


def test_floor_above_default_needs_no_reason():
    beats = [{"t_start_s": 0.0, "t_end_s": 1.5, "action": "hold"}]
    report = check_beat_floor(beats, {"beat_floor_s": 1.5})
    assert report["verdict"] == "pass"
    assert report["reviewed"] is False


# ---------------------------------------------------------------- gap 6: merge


def test_merge_folds_short_opening_beat_forward():
    beats = [
        {"t_start_s": 0.0, "t_end_s": 0.8, "action": "hand crosses lens",
         "camera": _cam("eye height", "close", "level", "static")},
        {"t_start_s": 0.8, "t_end_s": 3.44, "action": "pipa plucking gestures",
         "camera": _cam("upper torso height", "close", "diagonal", "tracking")},
        {"t_start_s": 3.44, "t_end_s": 5.0, "action": "brows lift"},
    ]
    result = merge_short_beats(beats)
    assert result["ok"] is True
    assert len(result["beats"]) == 2
    merged = result["beats"][0]
    assert merged["t_start_s"] == 0.0 and merged["t_end_s"] == 3.44
    assert "hand crosses lens" in merged["action"]
    assert "pipa plucking gestures" in merged["action"]
    assert "merged" in merged["action"]
    assert result["total_duration_s"] == pytest.approx(5.0)
    assert result["all_above_floor"] is True
    assert len(result["audit"]) == 1
    assert result["audit"][0]["folded_window"] == {
        "t_start_s": 0.8, "t_end_s": 3.44}
    # Tiling preserved: contiguous, starts at 0, ends at total.
    assert result["beats"][1]["t_start_s"] == 3.44
    assert result["beats"][-1]["t_end_s"] == 5.0


def test_merge_preserves_camera_text_and_notes_divergent_cameras():
    beats = [
        {"t_start_s": 0.0, "t_end_s": 0.65, "action": "fabric clears",
         "camera_move": "static",
         "camera": _cam("shoulder height", "close", "side", "static")},
        {"t_start_s": 0.65, "t_end_s": 2.387, "action": "palm outward",
         "camera_move": "glide",
         "camera": _cam("upper torso height", "close", "front", "glide")},
    ]
    result = merge_short_beats(beats)
    assert result["ok"] is True
    merged = result["beats"][0]
    assert "static" in str(merged["camera_move"])
    assert "glide" in str(merged["camera_move"])
    assert "merged_camera_note" in merged


def test_merge_short_final_beat_folds_backwards():
    beats = [
        {"t_start_s": 0.0, "t_end_s": 2.0, "action": "turn"},
        {"t_start_s": 2.0, "t_end_s": 2.5, "action": "final flick"},
    ]
    result = merge_short_beats(beats)
    assert result["ok"] is True
    assert len(result["beats"]) == 1
    assert result["beats"][0]["t_end_s"] == 2.5
    assert "final flick" in result["beats"][0]["action"]
    assert result["audit"][0]["merged_into_index"] == 0


def test_merge_noop_when_all_above_floor():
    beats = [
        {"t_start_s": 0.0, "t_end_s": 1.5, "action": "a"},
        {"t_start_s": 1.5, "t_end_s": 3.0, "action": "b"},
    ]
    result = merge_short_beats(beats)
    assert result["ok"] is True
    assert result["audit"] == []
    assert result["beats"] == beats


def test_merge_single_beat_under_floor_reports_honestly():
    beats = [{"t_start_s": 0.0, "t_end_s": 0.5, "action": "blink"}]
    result = merge_short_beats(beats)
    assert result["ok"] is False
    assert result["all_above_floor"] is False
    assert result["total_duration_s"] == pytest.approx(0.5)
    assert any(i["code"] == "single_beat_under_floor"
               for i in result["issues"])


def test_merge_untiled_input_refused():
    beats = [
        {"t_start_s": 0.0, "t_end_s": 1.0, "action": "a"},
        {"t_start_s": 1.5, "t_end_s": 2.5, "action": "b"},
    ]
    result = merge_short_beats(beats)
    assert result["ok"] is False
    assert any(i["code"] == "beats_not_tiled" for i in result["issues"])
    assert result["beats"] == beats


def test_merge_with_reviewed_policy():
    beats = [
        {"t_start_s": 0.0, "t_end_s": 0.8, "action": "hand crosses lens"},
        {"t_start_s": 0.8, "t_end_s": 1.5, "action": "settle"},
    ]
    policy = {"beat_floor_s": 0.5, "reason": "match-on-action opening"}
    result = merge_short_beats(beats, policy=policy)
    assert result["ok"] is True
    assert result["audit"] == []  # nothing under the reviewed floor


# ---------------------------------------------------------------- gap 6: 14-seg re-run (5 blocked segments)


def _compiler_episode(seg_id, duration, shots):
    beats = [
        {"beat_no": f"B{i + 1}", "t_start_s": s, "t_end_s": e,
         "action": a, "sound": "", "camera": c}
        for i, (s, e, a, c) in enumerate(shots)
    ]
    return {
        "episode_no": 1, "title": seg_id, "target_duration_s": duration,
        "aspect": "9:16", "style": "cinematic xianxia",
        "characters": [{"name": "heroine"}],
        "shots": [{
            "shot_no": "S1", "scene": "purple flower pavilion",
            "duration_s": duration,
            "camera": {
                "shot_size": "中景", "angle": "平视",
                "movement": "tracking_shot",
                "start_frame": {"state_kind": "trigger_in_progress",
                                "text": "in progress"},
                "end_frame": {"text": "end"},
            },
            "beats": beats,
            "continuity": {"entry_state": {"pose": "in progress"},
                           "exit_state": {"pose": "match out"}},
        }],
    }


# Gap-closed tilings from the v2 driver (gaps closed by extending the
# previous beat's end to the next beat's start; total durations and
# lyric windows unchanged -- merging only re-cuts beats, never times).
_BLOCKED = {
    "seg02": (11.470, [
        (0.0, 0.8, "hand crossing lower-left to upper-right clears lens",
         _cam("eye height", "close", "level", "static")),
        (0.8, 3.857, "pipa plucking gestures in air, cloud-arm path",
         _cam("upper torso height", "close", "diagonal across forearms", "hand-path tracking")),
        (3.857, 5.857, "brows lift, small smile",
         _cam("eye height", "very close", "three-quarter", "curved slide")),
        (5.857, 7.815, "eyes travel, focus pull to eyes",
         _cam("eye height", "close", "level", "lateral move")),
        (7.815, 11.47, "palm extends, cover step, sleeve wipe right to left",
         _cam("medium close", "half step back", "front", "short arc")),
    ]),
    "seg03": (12.780, [
        (0.0, 0.65, "fabric clears right to left, side step",
         _cam("shoulder height", "close", "side", "static")),
        (0.65, 2.387, "palm outward to empty space, fingertips curl",
         _cam("upper torso height", "arm's length", "three-quarter", "glide")),
        (2.387, 4.345, "push-in, hands scoop inward",
         _cam("upper torso height", "close", "front", "push-in")),
        (4.345, 7.762, "cloud-arm thread-palm turn chain",
         _cam("waist to shoulder height", "close", "side", "parallel tracking")),
        (7.762, 9.095, "arms settle, fingertip insert",
         _cam("hand height", "close", "level", "static")),
        (9.095, 11.095, "three accents: wrist flick, palm turn, torso",
         _cam("upper torso height", "close", "front", "tiny lateral reframes")),
        (11.095, 12.78, "flat turn, sleeve wipe left to right",
         _cam("medium", "close", "front", "matching arc")),
    ]),
    "seg04": (11.815, [
        (0.0, 0.65, "sleeve clears left to right, empty room reveal",
         _cam("shoulder height", "close", "behind gauze", "static")),
        (0.65, 3.815, "diagonal withdraw, eyes to empty entrance",
         _cam("shoulder height", "medium", "diagonal", "withdraw")),
        (3.815, 5.565, "waiting, hand rises then stops",
         _cam("seated eye height", "close", "profile", "parallel tracking")),
        (5.565, 7.607, "gauze drifts, wrist wave",
         _cam("shoulder height", "close", "behind gauze", "lateral slide")),
        (7.607, 9.857, "lifts curtain, finds no one, lets it fall",
         _cam("close", "close", "over shoulder", "static")),
        (9.857, 11.815, "eyes lower, gauze covers lens",
         _cam("side-front", "close", "level", "static")),
    ]),
    "seg10": (12.007, [
        (0.0, 0.715, "reflection to face, tilt up from floor",
         _cam("floor level", "close", "low", "tilt up")),
        (0.715, 2.757, "plucking-like finger phrase, slowing",
         _cam("hand height", "tight close", "level", "tracking")),
        (2.757, 4.715, "lattice window light, rack focus to cheek",
         _cam("window height", "close", "side", "lateral move")),
        (4.715, 8.257, "hand traces line, gathers memory",
         _cam("shoulder height", "close", "front", "short arc")),
        (8.257, 10.007, "turns to empty entrance, hand lifts and pauses",
         _cam("behind shoulder", "close", "rear", "static")),
        (10.007, 12.007, "sleeve descends across foreground",
         _cam("close", "close", "front", "tracking fabric")),
    ]),
    "seg12": (12.573, [
        (0.0, 0.573, "hand to floor transition, pedestal down",
         _cam("arm height", "close", "side", "pedestal down")),
        (0.573, 2.823, "glide above floor, reflections and gauze shadow",
         _cam("floor level", "close", "low", "lateral glide")),
        (2.823, 4.573, "slow gliding arm phrase, floating",
         _cam("waist height", "close", "side", "parallel tracking")),
        (4.573, 8.573, "three travelling steps, half pivot",
         _cam("medium", "medium", "front", "pull back")),
        (8.573, 10.573, "hands unfold from bud to open palms",
         _cam("hand height", "close", "level", "static")),
        (10.573, 12.573, "wrists fold, hands gather into sleeve",
         _cam("front", "close", "three-quarter", "curved move")),
    ]),
}


def test_blocked_segments_fail_default_floor_before_merge():
    for seg_id, (duration, shots) in _BLOCKED.items():
        episode = _compiler_episode(seg_id, duration, shots)
        with pytest.raises(Exception):
            compile_generation_ready_episode(
                episode, provider="fasth3_local",
                anchors=ANCHORS, reference_bindings=BINDINGS)


def test_blocked_segments_pass_after_merge():
    for seg_id, (duration, shots) in _BLOCKED.items():
        beats = [
            {"beat_no": f"B{i + 1}", "t_start_s": s, "t_end_s": e,
             "action": a, "sound": "", "camera": c}
            for i, (s, e, a, c) in enumerate(shots)
        ]
        merged = merge_short_beats(beats)
        assert merged["ok"] is True, (seg_id, merged["issues"])
        assert merged["total_duration_s"] == pytest.approx(duration)
        merged_shots = [
            (b["t_start_s"], b["t_end_s"], b["action"], b.get("camera"))
            for b in merged["beats"]
        ]
        episode = _compiler_episode(seg_id, duration, merged_shots)
        result = compile_generation_ready_episode(
            episode, provider="fasth3_local",
            anchors=ANCHORS, reference_bindings=BINDINGS)
        assert result["total_duration_s"] == pytest.approx(duration)


# ---------------------------------------------------------------- gap 7: handoff_kind


def _two_segment_plan(**overrides):
    plan = {
        "segments": [
            {"segment_id": "seg01",
             "outgoing": {
                 "gesture": "hand sweeps across lens",
                 "direction": "lower-left to upper-right",
                 "speed": "fast",
                 "end_state": "hand across lens",
                 "handoff_kind": "gesture",
             }},
            {"segment_id": "seg02",
             "incoming": {
                 "gesture": "hand sweeps across lens",
                 "direction": "lower-left to upper-right",
                 "speed": "fast",
                 "start_state": "hand across lens",
                 "handoff_kind": "gesture",
             }},
        ],
    }
    for key, value in overrides.items():
        plan[key] = value
    return plan


def test_handoff_kinds_closed_vocabulary():
    assert HANDOFF_KINDS == ("gesture", "wipe", "element",
                             "rotation", "fabric", "gaze")


def test_handoff_kind_match_passes():
    report = check_segment_match(_two_segment_plan())
    assert report["verdict"] == "pass", report["issues"]
    assert report["boundaries"][0]["checks"]["handoff_kind"] is True


def test_plans_without_handoff_kind_still_pass():
    plan = _two_segment_plan()
    del plan["segments"][0]["outgoing"]["handoff_kind"]
    del plan["segments"][1]["incoming"]["handoff_kind"]
    report = check_segment_match(plan)
    assert report["verdict"] == "pass", report["issues"]
    assert report["boundaries"][0]["checks"]["handoff_kind"] is None


def test_unknown_handoff_kind_fails():
    plan = _two_segment_plan()
    plan["segments"][0]["outgoing"]["handoff_kind"] = "teleport"
    report = check_segment_match(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "unknown_handoff_kind" for i in report["issues"])


def test_handoff_kind_mismatch_fails():
    plan = _two_segment_plan()
    plan["segments"][1]["incoming"]["handoff_kind"] = "wipe"
    report = check_segment_match(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "handoff_kind_mismatch" for i in report["issues"])
    with pytest.raises(CapabilityError):
        authorize_segment_match(plan)


def test_element_handoff_requires_element_name():
    plan = _two_segment_plan()
    for segment, side in ((0, "outgoing"), (1, "incoming")):
        plan["segments"][segment][side]["handoff_kind"] = "fabric"
    report = check_segment_match(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "element_name_missing" for i in report["issues"])


def test_element_name_without_element_kind_fails():
    plan = _two_segment_plan()
    for segment, side in ((0, "outgoing"), (1, "incoming")):
        plan["segments"][segment][side]["element_name"] = "gauze"
    report = check_segment_match(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "handoff_kind_missing_for_element"
               for i in report["issues"])


def test_element_name_mismatch_fails():
    plan = _two_segment_plan()
    plan["segments"][0]["outgoing"].update(
        {"handoff_kind": "fabric", "element_name": "gauze"})
    plan["segments"][1]["incoming"].update(
        {"handoff_kind": "fabric", "element_name": "sleeve"})
    report = check_segment_match(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "element_name_mismatch" for i in report["issues"])


def test_element_handoff_with_matching_names_passes():
    plan = _two_segment_plan()
    plan["segments"][0]["outgoing"].update(
        {"handoff_kind": "fabric", "element_name": "gauze"})
    plan["segments"][1]["incoming"].update(
        {"handoff_kind": "fabric", "element_name": "gauze"})
    report = check_segment_match(plan)
    assert report["verdict"] == "pass", report["issues"]
    assert report["boundaries"][0]["checks"]["element_name"] is True


def test_direction_containing_element_name_fails():
    for stretched in ("gauze texture", "floor reflection", "into sleeve"):
        plan = _two_segment_plan()
        plan["segments"][0]["outgoing"]["direction"] = stretched
        plan["segments"][1]["incoming"]["direction"] = stretched
        report = check_segment_match(plan)
        assert report["verdict"] == "fail", stretched
        assert any(i["code"] == "direction_contains_element_name"
                   for i in report["issues"]), stretched


def test_occlusion_direction_containing_element_name_fails():
    plan = _two_segment_plan()
    plan["segments"][0]["outgoing"]["occlusion_direction"] = "gauze texture"
    plan["segments"][1]["incoming"]["occlusion_direction"] = "gauze texture"
    report = check_segment_match(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "direction_contains_element_name"
               for i in report["issues"])


# ---------------------------------------------------------------- gap 7: 13-boundary re-run


def _boundary_chain():
    """13 boundaries, corrected forms: direction holds travel only;
    gauze/reflection/sleeve live in element_name/gesture, never in
    direction. States/speeds follow the v2 driver values."""
    def seg(seg_id, outgoing=None, incoming=None):
        entry = {"segment_id": seg_id}
        if outgoing is not None:
            entry["outgoing"] = outgoing
        if incoming is not None:
            entry["incoming"] = incoming
        return entry

    def out(direction, speed, end_state, kind, gesture=None,
            element_name=None, occlusion=None, rotation=None):
        side = {"direction": direction, "speed": speed,
                "end_state": end_state, "handoff_kind": kind}
        if gesture is not None:
            side["gesture"] = gesture
        if element_name is not None:
            side["element_name"] = element_name
        if occlusion is not None:
            side["occlusion_direction"] = occlusion
        if rotation is not None:
            side["rotation_phase"] = rotation
        return side

    def inc(direction, speed, start_state, kind, gesture=None,
            element_name=None, occlusion=None, rotation=None):
        side = {"direction": direction, "speed": speed,
                "start_state": start_state, "handoff_kind": kind}
        if gesture is not None:
            side["gesture"] = gesture
        if element_name is not None:
            side["element_name"] = element_name
        if occlusion is not None:
            side["occlusion_direction"] = occlusion
        if rotation is not None:
            side["rotation_phase"] = rotation
        return side

    return {"segments": [
        seg("seg01", outgoing=out(
            "lower-left to upper-right", "same speed",
            "hand crossing rightward, soft motion blur", "gesture",
            gesture="hand sweeps across lens")),
        seg("seg02", incoming=inc(
            "lower-left to upper-right", "same speed",
            "hand crossing rightward, soft motion blur", "gesture",
            gesture="hand sweeps across lens"),
            outgoing=out(
            "right to left", "soft fabric wipe",
            "fabric fills frame, soft wipe", "wipe",
            gesture="sleeve or gauze sweeps across lens",
            occlusion="right to left")),
        seg("seg03", incoming=inc(
            "right to left", "soft fabric wipe",
            "fabric fills frame, soft wipe", "wipe",
            gesture="sleeve or gauze sweeps across lens",
            occlusion="right to left"),
            outgoing=out(
            "left to right", "sleeve sweep",
            "sleeve fills frame left to right", "wipe",
            gesture="sleeve spin wipe", occlusion="left to right")),
        seg("seg04", incoming=inc(
            "left to right", "sleeve sweep",
            "sleeve fills frame left to right", "wipe",
            gesture="sleeve spin wipe", occlusion="left to right"),
            outgoing=out(
            "toward lens", "gentle drift",
            "gauze texture fills frame", "fabric",
            gesture="gauze moves close to lens", element_name="gauze")),
        seg("seg05", incoming=inc(
            "toward lens", "gentle drift",
            "gauze texture fills frame", "fabric",
            gesture="gauze moves close to lens", element_name="gauze"),
            outgoing=out(
            "clockwise", "matching rotational speed",
            "clockwise half-turn in progress, right shoulder toward lens",
            "rotation", rotation="clockwise half-turn in progress")),
        seg("seg06", incoming=inc(
            "clockwise", "matching rotational speed",
            "clockwise half-turn in progress, right shoulder toward lens",
            "rotation", rotation="clockwise half-turn in progress"),
            outgoing=out(
            "upward", "slow rise",
            "back-facing, arms partway overhead", "gesture")),
        seg("seg07", incoming=inc(
            "upward", "slow rise",
            "back-facing, arms partway overhead", "gesture"),
            outgoing=out(
            "downward", "soft fold",
            "hands descending toward chest", "gesture")),
        seg("seg08", incoming=inc(
            "downward", "soft fold",
            "hands descending toward chest", "gesture"),
            outgoing=out(
            "frame-left", "slow gaze shift",
            "gaze toward frame-left, camera behind shoulder", "gaze")),
        seg("seg09", incoming=inc(
            "frame-left", "slow gaze shift",
            "gaze toward frame-left, camera behind shoulder", "gaze"),
            outgoing=out(
            "vertical", "slow tilt",
            "warm-violet floor reflection in frame", "element",
            element_name="floor reflection")),
        seg("seg10", incoming=inc(
            "vertical", "slow tilt",
            "warm-violet floor reflection in frame", "element",
            element_name="floor reflection"),
            outgoing=out(
            "vertical", "gentle fall",
            "gauze across upper frame", "fabric",
            element_name="gauze")),
        seg("seg11", incoming=inc(
            "vertical", "gentle fall",
            "gauze across upper frame", "fabric",
            element_name="gauze"),
            outgoing=out(
            "diagonally upward", "tracked rise",
            "hand and sleeve diagonal upper-right", "gesture")),
        seg("seg12", incoming=inc(
            "diagonally upward", "tracked rise",
            "hand and sleeve diagonal upper-right", "gesture"),
            outgoing=out(
            "inward", "soft gather",
            "hands gathered into sleeve", "gesture",
            gesture="hands gather into sleeve")),
        seg("seg13", incoming=inc(
            "inward", "soft gather",
            "hands gathered into sleeve", "gesture",
            gesture="hands gather into sleeve"),
            outgoing=out(
            "clockwise", "matching rotational speed",
            "mid-turn, arms beginning to rise", "rotation",
            rotation="clockwise turn in progress")),
        seg("seg14", incoming=inc(
            "clockwise", "matching rotational speed",
            "mid-turn, arms beginning to rise", "rotation",
            rotation="clockwise turn in progress")),
    ]}


def test_thirteen_boundaries_pass_with_handoff_kinds():
    report = check_segment_match(_boundary_chain())
    assert report["verdict"] == "pass", report["issues"]
    assert len(report["boundaries"]) == 13
    for boundary in report["boundaries"]:
        assert boundary["checks"]["direction"] is True
        assert boundary["checks"]["handoff_kind"] is True
    element_boundaries = [report["boundaries"][i] for i in (3, 8, 9)]
    for boundary in element_boundaries:
        assert boundary["checks"]["element_name"] is True
