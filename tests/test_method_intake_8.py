"""Tests for the 8 clean-room method-intake capabilities (369 list).

Every capability gets normal, boundary and illegal-input coverage.
All CPU only, no network, no keys, no model downloads, no rendering.
"""

import pytest

from hevi.capabilities.registry import CapabilityError, get
from hevi.capabilities.handpaint_narration import build_narration_plan
from hevi.capabilities.karaoke_vertical import build_karaoke_vertical
from hevi.capabilities.frame_review import build_frame_review
from hevi.capabilities.gsap_timeline import build_gsap_timeline
from hevi.capabilities.portrait_consent import gate_portrait
from hevi.capabilities.shot_continuity import check_shot_continuity
from hevi.capabilities.editable_project import build_project, apply_edit
from hevi.capabilities.word_appear import build_appear_plan, tts_slot, align_words_local


# ---------------------------------------------------------------- registry

def test_registry_names_all_eight():
    import hevi.capabilities  # noqa: F401  (wires the eight in)
    for name in (
        "animation.handpaint_narration_align",
        "edit.karaoke_vertical",
        "qa.frame_review",
        "animation.gsap_timeline_plan",
        "qa.portrait_consent_gate",
        "qa.shot_continuity_gate",
        "edit.editable_project",
        "explain.word_appear_plan",
    ):
        assert get(name).name == name


# ------------------------------------------------------- 1 handpaint narration

def _hp_plan(**over):
    plan = {
        "fps": 24,
        "narration": [
            {"id": "n1", "text": "Draw the house", "start_sec": 0.0, "end_sec": 2.0},
            {"id": "n2", "text": "Then the tree", "start_sec": 2.0, "end_sec": 4.0},
        ],
        "elements": [
            {"id": "house", "narration_id": "n1",
             "strokes": [{"id": "s1", "phase": "outline"}, {"id": "s2", "phase": "hatch"}, {"id": "s3", "phase": "detail"}],
             "fill": {"method": "diagonal_hatch", "angle_deg": 45}},
            {"id": "tree", "narration_id": "n2",
             "strokes": [{"id": "t1", "phase": "outline"}]},
        ],
        "camera_moves": [{"id": "c1", "kind": "push_in", "start_sec": 0.5, "end_sec": 1.5}],
        "transitions": [{"id": "x1", "kind": "wipe_brush", "at_sec": 2.0, "from_element": "house", "to_element": "tree"}],
    }
    plan.update(over)
    return plan


def test_hp_normal_cue_sheet():
    out = build_narration_plan(_hp_plan())
    assert out["render_status"] == "plan_only_no_render"
    assert out["cue_sheet"][0]["start_frame"] == 0
    assert out["cue_sheet"][0]["end_frame"] == 47
    phases = [e["phase"] for e in out["cue_sheet"][0]["stroke_events"]]
    assert phases == ["outline", "hatch", "detail"]
    assert all(e["at_frame"] < 48 for e in out["cue_sheet"][0]["stroke_events"])
    assert out["camera_moves"][0]["kind"] == "push_in"
    assert out["transitions"][0]["kind"] == "wipe_brush"


def test_hp_narration_first_no_event_before_start():
    out = build_narration_plan(_hp_plan())
    second = out["cue_sheet"][1]["stroke_events"]
    assert second and second[0]["at_frame"] >= 48


def test_hp_boundary_single_frame_line():
    plan = _hp_plan(narration=[{"id": "n1", "text": "Hi", "start_sec": 0.0, "end_sec": 1 / 24}],
                    elements=[{"id": "e", "narration_id": "n1", "strokes": [{"id": "s", "phase": "outline"}]}],
                    camera_moves=[], transitions=[])
    out = build_narration_plan(plan)
    assert out["cue_sheet"][0]["start_frame"] == out["cue_sheet"][0]["end_frame"] == 0


def test_hp_illegal_phase_order():
    plan = _hp_plan(elements=[{"id": "e", "narration_id": "n1",
                               "strokes": [{"id": "s1", "phase": "detail"}, {"id": "s2", "phase": "outline"}]}])
    with pytest.raises(CapabilityError):
        build_narration_plan(plan)


def test_hp_illegal_hatch_angles():
    for angle in (0, 90, 180):
        plan = _hp_plan(elements=[{"id": "e", "narration_id": "n1",
                                   "strokes": [{"id": "s", "phase": "outline"}],
                                   "fill": {"method": "diagonal_hatch", "angle_deg": angle}}])
        with pytest.raises(CapabilityError):
            build_narration_plan(plan)


def test_hp_illegal_overlap_unknown_camera_outside():
    bad = _hp_plan(narration=[{"id": "n1", "text": "a", "start_sec": 0.0, "end_sec": 2.0},
                              {"id": "n2", "text": "b", "start_sec": 1.0, "end_sec": 3.0}])
    with pytest.raises(CapabilityError):
        build_narration_plan(bad)
    with pytest.raises(CapabilityError):
        build_narration_plan(_hp_plan(camera_moves=[{"id": "c", "kind": "orbit_3d", "start_sec": 0.0, "end_sec": 1.0}]))
    with pytest.raises(CapabilityError):
        build_narration_plan(_hp_plan(camera_moves=[{"id": "c", "kind": "push_in", "start_sec": 3.5, "end_sec": 4.5}]))
    with pytest.raises(CapabilityError):
        build_narration_plan(_hp_plan(elements=[{"id": "e", "narration_id": "nope", "strokes": [{"id": "s", "phase": "outline"}]}]))


# ---------------------------------------------------------- 2 karaoke vertical

def _kv_words():
    return [
        {"word": "Draw", "start_sec": 0.0, "end_sec": 0.5},
        {"word": "the", "start_sec": 0.5, "end_sec": 0.8},
        {"word": "house", "start_sec": 0.8, "end_sec": 1.4},
    ]


def test_kv_normal():
    out = build_karaoke_vertical({"words": _kv_words(), "caption": {"title": "House", "topic": "drawing"}})
    assert out["vertical_spec"]["width"] == 1080 and out["vertical_spec"]["height"] == 1920
    assert out["vertical_spec"]["aspect"] == "9:16"
    assert out["word_events"][1]["active_start_sec"] == 0.5
    assert out["karaoke_line_count"] == 1
    assert out["caption_status"] == "ready"
    assert out["publish_status"] == "plan_only_not_posted"
    assert out["caption_templates"][0]["name"] == "hook"


def test_kv_boundary_line_split_at_10_words():
    words = [{"word": f"w{i}", "start_sec": i * 0.4, "end_sec": (i + 1) * 0.4} for i in range(11)]
    out = build_karaoke_vertical({"words": words})
    assert out["karaoke_line_count"] == 2
    assert out["karaoke_lines"][0]["word_count"] == 10


def test_kv_boundary_placeholders_without_caption():
    out = build_karaoke_vertical({"words": _kv_words()})
    assert out["caption_status"] == "template_placeholders_only"
    assert "[title]" in out["caption_templates"][0]["text"]


def test_kv_illegal():
    with pytest.raises(CapabilityError):
        build_karaoke_vertical({"words": []})
    with pytest.raises(CapabilityError):
        build_karaoke_vertical({"words": [
            {"word": "a", "start_sec": 0.0, "end_sec": 1.0},
            {"word": "b", "start_sec": 0.5, "end_sec": 1.5}]})
    with pytest.raises(CapabilityError):
        build_karaoke_vertical({"words": _kv_words(), "vertical": {"width": 1920, "height": 1080}})
    with pytest.raises(CapabilityError):
        build_karaoke_vertical({"words": _kv_words(), "vertical": {"margin_side_px": 600}})
    with pytest.raises(CapabilityError):
        build_karaoke_vertical({"words": _kv_words(), "source_duration_sec": 1.0})


# ------------------------------------------------------------ 3 frame review

def _fr_frames():
    return [
        {"frame_index": 100, "timecode": "00:00:10:00", "source_ref": "render_v3.mp4",
         "findings": [{"category": "framing", "severity": "minor", "note": "Headroom tight"}]},
        {"frame_index": 101, "timecode": "00:00:10:01", "source_ref": "render_v3.mp4", "findings": []},
        {"frame_index": 102, "timecode": "00:00:10:02", "source_ref": "render_v3.mp4",
         "findings": [{"category": "freeze", "severity": "blocker", "note": "Frame repeats previous"}]},
    ]


def test_fr_normal_fail_on_blocker():
    out = build_frame_review({"fps": 25, "start_timecode": "00:00:10:00", "frames": _fr_frames()})
    assert out["verdict"] == "fail"
    assert out["frame_count"] == 3
    assert out["model_visual_review"] == "not_performed"
    assert out["visual_evidence"] == "caller_supplied_frames_only"
    assert out["frame_table"][1]["seconds_from_start"] == 0.04
    assert out["model_report_entry"]["top_issues"][0]["category"] == "freeze"


def test_fr_boundary_pass_clean():
    out = build_frame_review({"fps": 25, "start_timecode": "00:00:10:00", "frames": [
        {"frame_index": 5, "timecode": "00:00:10:00", "source_ref": "a.mp4", "findings": []}]})
    assert out["verdict"] == "pass"


def test_fr_boundary_missing_source_needs_fix():
    out = build_frame_review({"fps": 25, "start_timecode": "00:00:10:00", "frames": [
        {"frame_index": 5, "timecode": "00:00:10:00", "findings": []}]})
    assert out["verdict"] == "needs_fix"
    assert out["frames_missing_source_ref"] == [5]


def test_fr_illegal():
    with pytest.raises(CapabilityError):
        build_frame_review({"fps": 25, "start_timecode": "00:00:10:00", "frames": [
            {"frame_index": 5, "timecode": "00:00:10:00", "findings": []},
            {"frame_index": 6, "timecode": "00:00:10:00", "findings": []}]})
    with pytest.raises(CapabilityError):
        build_frame_review({"fps": 25, "start_timecode": "00:00:10:00", "frames": [
            {"frame_index": 5, "timecode": "00:00:10:00", "findings": []},
            {"frame_index": 7, "timecode": "00:00:10:01", "findings": []}]})
    with pytest.raises(CapabilityError):
        build_frame_review({"fps": 25, "start_timecode": "00:00:10:00", "frames": [
            {"frame_index": 5, "timecode": "00:00:10:25", "findings": []}]})
    with pytest.raises(CapabilityError):
        build_frame_review({"fps": 25, "start_timecode": "00:00:10:00", "frames": [
            {"frame_index": 5, "timecode": "00:00:10:00",
             "findings": [{"category": "vibes", "severity": "minor", "note": "x"}]}]})
    with pytest.raises(CapabilityError):
        build_frame_review({"fps": 0, "start_timecode": "00:00:10:00", "frames": _fr_frames()})


# ------------------------------------------------------------ 4 gsap timeline

def _gsap_plan(**over):
    plan = {
        "duration_sec": 2.0, "fps": 10,
        "tweens": [
            {"id": "t1", "target": "box", "property": "x", "from_value": 0, "to_value": 100,
             "start_sec": 0.0, "end_sec": 2.0, "ease": "sine.inOut"},
            {"id": "t2", "target": "box", "property": "opacity", "from_value": 0, "to_value": 1,
             "start_sec": 0.0, "end_sec": 1.0, "ease": "none"},
        ],
        "source_points": [{"id": "s1", "at_sec": 1.0, "state": {"box.x": 50, "box.opacity": 1}}],
    }
    plan.update(over)
    return plan


def test_gsap_normal_frames_and_comparison():
    out = build_gsap_timeline(_gsap_plan())
    assert out["timeline_count"] == 1
    assert out["frame_count"] == 21
    assert out["frame_table"][0]["frame_id"] == "f0000"
    assert out["frame_table"][10]["values"]["box.x"] == pytest.approx(50.0)
    assert out["frame_table"][20]["values"]["box.x"] == pytest.approx(100.0)
    assert out["frame_table"][20]["values"]["box.opacity"] == pytest.approx(1.0)
    comp = out["source_comparisons"][0]
    assert comp["nearest_frame_id"] == "f0010"
    assert comp["deltas"]["box.x"]["delta"] == pytest.approx(0.0)
    assert out["media"] == "plan_only_no_video"


def test_gsap_boundary_hold_after_end():
    out = build_gsap_timeline(_gsap_plan())
    assert out["frame_table"][15]["values"]["box.opacity"] == pytest.approx(1.0)


def test_gsap_illegal():
    with pytest.raises(CapabilityError):
        build_gsap_timeline(_gsap_plan(tweens=[
            {"id": "a", "target": "box", "property": "x", "from_value": 0, "to_value": 10, "start_sec": 0.0, "end_sec": 1.5},
            {"id": "b", "target": "box", "property": "x", "from_value": 10, "to_value": 20, "start_sec": 1.0, "end_sec": 2.0}]))
    with pytest.raises(CapabilityError):
        build_gsap_timeline(_gsap_plan(tweens=[
            {"id": "a", "target": "box", "property": "x", "from_value": 0, "to_value": 10, "start_sec": 0.0, "end_sec": 1.0, "ease": "bounce"}]))
    with pytest.raises(CapabilityError):
        build_gsap_timeline(_gsap_plan(duration_sec=1000.0, fps=30))
    with pytest.raises(CapabilityError):
        build_gsap_timeline(_gsap_plan(source_points=[{"id": "s", "at_sec": 5.0, "state": {"box.x": 1}}]))


# -------------------------------------------------------- 5 portrait consent

def _pc_registry():
    return {"portraits": [
        {"portrait_id": "p1", "consent": "authorized", "scope": ["interview"], "expires_at": "2027-01-01"},
        {"portrait_id": "p2", "consent": "pending", "scope": []},
        {"portrait_id": "p3", "consent": "denied", "scope": ["interview"]},
    ]}


def test_pc_normal_allowed_and_styles():
    out = gate_portrait({"registry": _pc_registry(), "portrait_id": "p1", "intended_use": "interview", "as_of_date": "2026-10-27"})
    assert out["allowed"] is True and out["verdict"] == "allowed"
    assert out["styles_available"]
    assert out["supplier"] is None
    assert out["digital_human_generation"] == "not_offered_by_this_gate"
    assert "api_key" not in out and "key" not in out


def test_pc_boundary_no_expiry_no_date():
    reg = {"portraits": [{"portrait_id": "p9", "consent": "authorized", "scope": ["interview"]}]}
    out = gate_portrait({"registry": reg, "portrait_id": "p9", "intended_use": "interview"})
    assert out["allowed"] is True


def test_pc_pending_denied_expired_scope():
    assert gate_portrait({"registry": _pc_registry(), "portrait_id": "p2", "intended_use": "interview"})["verdict"] == "pending_no_authorisation"
    assert gate_portrait({"registry": _pc_registry(), "portrait_id": "p3", "intended_use": "interview"})["verdict"] == "refused_consent_denied"
    assert gate_portrait({"registry": _pc_registry(), "portrait_id": "p1", "intended_use": "ad"})["verdict"] == "pending_scope_not_granted"
    assert gate_portrait({"registry": _pc_registry(), "portrait_id": "p1", "intended_use": "interview", "as_of_date": "2027-06-01"})["verdict"] == "refused_expired"
    assert gate_portrait({"registry": _pc_registry(), "portrait_id": "ghost", "intended_use": "interview"})["verdict"] == "refused_unknown_portrait"
    for out in (gate_portrait({"registry": _pc_registry(), "portrait_id": "p2", "intended_use": "interview"}),
                gate_portrait({"registry": _pc_registry(), "portrait_id": "ghost", "intended_use": "interview"})):
        assert out["styles_available"] == []


def test_pc_illegal_keys_and_bad_inputs():
    with pytest.raises(CapabilityError):
        gate_portrait({"registry": _pc_registry(), "portrait_id": "p1", "intended_use": "interview", "api_key": "x"})
    with pytest.raises(CapabilityError):
        gate_portrait({"registry": {"portraits": [{"portrait_id": "p", "consent": "maybe", "scope": []}]},
                       "portrait_id": "p", "intended_use": "interview"})
    with pytest.raises(CapabilityError):
        gate_portrait({"registry": _pc_registry(), "portrait_id": "p1", "intended_use": "interview", "style": "supplier_x_look"})


# -------------------------------------------------------- 6 shot continuity

def _sc_shots():
    return [
        {"id": "s1", "duration_sec": 2.0, "camera": "pan",
         "elements": [{"element_id": "cup", "motion": "static", "continues": True}]},
        {"id": "s2", "duration_sec": 2.0, "camera": "static",
         "elements": [{"element_id": "cup", "motion": "moving", "carries_from": "cup", "changed_attributes": ["position"]}]},
    ]


def test_sc_normal_pass():
    out = check_shot_continuity({"shots": _sc_shots()})
    assert out["verdict"] == "pass"
    assert out["boundaries"][0]["verdict"] == "pass"
    assert out["oracle"]["slideshow_detected"] is False


def test_sc_boundary_carried_but_unchanged_major():
    shots = _sc_shots()
    shots[1]["elements"][0]["motion"] = "static"
    shots[1]["elements"][0]["changed_attributes"] = []
    out = check_shot_continuity({"shots": shots})
    assert out["verdict"] == "fail"
    assert out["boundaries"][0]["issues"][0]["kind"] == "carried_but_unchanged"


def test_sc_boundary_dropped_and_oracle():
    shots = _sc_shots()
    shots[1]["elements"] = [{"element_id": "other", "motion": "entering"}]
    out = check_shot_continuity({"shots": shots})
    assert any(i["kind"] == "element_dropped" for i in out["boundaries"][0]["issues"])
    static = [
        {"id": "a", "duration_sec": 1.0, "camera": "static", "elements": [{"element_id": "x", "motion": "static"}]},
        {"id": "b", "duration_sec": 1.0, "camera": "static", "elements": [{"element_id": "x", "motion": "static"}]},
        {"id": "c", "duration_sec": 1.0, "camera": "static", "elements": [{"element_id": "x", "motion": "static"}]},
        {"id": "d", "duration_sec": 1.0, "camera": "static", "elements": [{"element_id": "x", "motion": "static"}]},
    ]
    out2 = check_shot_continuity({"shots": static})
    assert out2["oracle"]["slideshow_detected"] is True
    assert out2["verdict"] == "fail"


def test_sc_boundary_single_shot_no_oracle():
    out = check_shot_continuity({"shots": [{"id": "only", "duration_sec": 1.0, "camera": "static",
                                            "elements": [{"element_id": "x", "motion": "static"}]}]})
    assert out["oracle"]["slideshow_detected"] is False
    assert out["boundaries"] == []


def test_sc_illegal():
    with pytest.raises(CapabilityError):
        check_shot_continuity({"shots": []})
    bad = _sc_shots()
    bad[1]["elements"][0]["carries_from"] = "ghost"
    with pytest.raises(CapabilityError):
        check_shot_continuity({"shots": bad})
    with pytest.raises(CapabilityError):
        check_shot_continuity({"shots": [{"id": "s", "duration_sec": 0, "camera": "static", "elements": []}]})


# -------------------------------------------------------- 7 editable project

def _ep_spec():
    return {
        "project_id": "proj1", "title": "Demo", "fps": 30, "duration_sec": 10.0,
        "resolution": {"width": 1920, "height": 1080},
        "tracks": [
            {"track_id": "v1", "kind": "video", "clips": [
                {"clip_id": "c1", "source_ref": "a.mp4", "timeline_start_sec": 0.0, "timeline_end_sec": 4.0,
                 "source_start_sec": 0.0, "source_end_sec": 8.0},
                {"clip_id": "c2", "source_ref": "b.mp4", "timeline_start_sec": 4.0, "timeline_end_sec": 8.0}]},
            {"track_id": "t1", "kind": "text", "clips": [
                {"clip_id": "tx1", "source_ref": None, "timeline_start_sec": 0.0, "timeline_end_sec": 2.0,
                 "edits": {"text": "Hello"}}]},
        ],
    }


def test_ep_normal_build_and_edits():
    proj = build_project(_ep_spec())
    assert proj["summary"] == {"track_count": 2, "clip_count": 3}
    renamed = apply_edit(proj, {"action": "rename_clip", "clip_id": "c1", "new_clip_id": "c1b"})
    assert renamed["edit_history"][0]["sequence"] == 1
    assert proj["tracks"][0]["clips"][0]["clip_id"] == "c1"
    split = apply_edit(proj, {"action": "split_clip", "clip_id": "c1", "at_sec": 2.0, "new_clip_id": "c1s"})
    assert split["summary"]["clip_count"] == 4
    halves = [c for c in split["tracks"][0]["clips"] if c["clip_id"] in ("c1", "c1s")]
    assert halves[0]["timeline_end_sec"] == 2.0 and halves[1]["timeline_start_sec"] == 2.0
    assert halves[0]["source_end_sec"] == pytest.approx(4.0)
    texted = apply_edit(proj, {"action": "set_clip_text", "clip_id": "tx1", "text": "World"})
    assert texted["tracks"][1]["clips"][0]["edits"]["text"] == "World"


def test_ep_boundary_touching_clips_ok():
    proj = build_project(_ep_spec())
    assert proj["tracks"][0]["clips"][1]["timeline_start_sec"] == 4.0


def test_ep_illegal():
    spec = _ep_spec()
    spec["tracks"][0]["clips"][1]["timeline_start_sec"] = 3.0
    with pytest.raises(CapabilityError):
        build_project(spec)
    proj = build_project(_ep_spec())
    with pytest.raises(CapabilityError):
        apply_edit(proj, {"action": "retime_clip", "clip_id": "c1", "timeline_start_sec": 3.0, "timeline_end_sec": 9.0})
    with pytest.raises(CapabilityError):
        apply_edit(proj, {"action": "move_clip", "clip_id": "c1", "target_track_id": "t1"})
    with pytest.raises(CapabilityError):
        apply_edit(proj, {"action": "split_clip", "clip_id": "c1", "at_sec": 4.0, "new_clip_id": "cx"})
    with pytest.raises(CapabilityError):
        apply_edit(proj, {"action": "explode", "clip_id": "c1"})
    with pytest.raises(CapabilityError):
        build_project({**_ep_spec(), "tracks": [
            {"track_id": "v1", "kind": "video", "clips": [
                {"clip_id": "c1", "timeline_start_sec": 0.0, "timeline_end_sec": 1.0, "edits": {"speed": 0}}]}]})


# ---------------------------------------------------------- 8 word appear

def _wa_words():
    return [
        {"word": "Draw", "start_sec": 0.0, "end_sec": 0.5},
        {"word": "the", "start_sec": 0.5, "end_sec": 0.8},
    ]


def test_wa_normal_supplied():
    out = build_appear_plan({"words": _wa_words()})
    assert out["alignment_status"] == "aligned_supplied"
    assert out["word_events"][0]["appear_at_sec"] == 0.0
    assert out["word_events"][1]["highlight_until_sec"] == 0.8
    assert out["line_count"] == 1


def test_wa_boundary_pending_null_not_fabricated():
    out = build_appear_plan({"words": [{"word": "Draw"}, {"word": "the"}]})
    assert out["alignment_status"] == "pending_alignment"
    assert all(e["appear_at_sec"] is None for e in out["word_events"])


def test_wa_local_align_pending_without_faster_whisper(tmp_path, monkeypatch):
    # Simulate a machine without faster-whisper: a None entry in
    # sys.modules makes the import raise ImportError.
    import sys
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"")
    out = align_words_local(str(audio), "hello world")
    assert out["status"] == "pending"
    assert out["reason"] == "faster_whisper_not_installed"
    assert out["words"] == []


def test_wa_local_align_missing_file_raises():
    with pytest.raises(CapabilityError):
        align_words_local("/definitely/not/here.wav", "hello world")


def test_wa_tts_slots():
    assert tts_slot(None)["status"] == "not_requested"
    assert tts_slot("kokoro")["status"] in ("ready", "pending")
    with pytest.raises(CapabilityError):
        tts_slot("elevenlabs")
    with pytest.raises(CapabilityError):
        tts_slot("mystery_tts")


def test_wa_illegal():
    with pytest.raises(CapabilityError):
        build_appear_plan({"words": []})
    with pytest.raises(CapabilityError):
        build_appear_plan({"words": [{"word": "a", "start_sec": 0.0, "end_sec": 1.0}, {"word": "b"}]})
    with pytest.raises(CapabilityError):
        build_appear_plan({"words": [
            {"word": "a", "start_sec": 0.0, "end_sec": 1.0},
            {"word": "b", "start_sec": 0.5, "end_sec": 1.5}]})
    with pytest.raises(CapabilityError):
        build_appear_plan({"words": _wa_words(), "api_key": "x"})
