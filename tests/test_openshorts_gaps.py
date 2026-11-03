"""Offline tests for the openshorts method intake. CPU only, no network, no keys."""

import pytest

from hevi.capabilities.clip_moments import select_moments
from hevi.capabilities.publish_plan import build_publish_plan, record_publish_result
from hevi.capabilities.vertical_reframe import plan_reframe
from hevi.capabilities.webhook_final import check_duplicate, make_final_event, verify_final_event
from hevi.capabilities.word_subtitle_contract import build_contract
from hevi.capabilities.registry import CapabilityError, get


def _words():
    words = []
    t = 0.0
    for i in range(40):
        words.append({"word": f"w{i}", "start_sec": t, "end_sec": t + 1.0})
        t += 1.0
    return words


def test_registry_names():
    from hevi.capabilities import (  # noqa: F401  (self-register)
        clip_moments, publish_plan, vertical_reframe, webhook_final, word_subtitle_contract,
    )
    for name in (
        "edit.clip_moments",
        "edit.vertical_reframe",
        "edit.word_subtitle_contract",
        "edit.publish_plan",
        "edit.webhook_final",
    ):
        assert get(name).name == name


# --- clip moments ---

def test_clip_moments_picks_in_range_scored_windows():
    plan = {
        "source_duration_sec": 120.0,
        "transcript_words": _words() + [
            {"word": "secret", "start_sec": 60.0, "end_sec": 61.0},
            {"word": "secret", "start_sec": 61.0, "end_sec": 62.0},
        ],
        "scene_boundaries_sec": [40.0, 80.0],
        "hook_words": ["secret"],
        "min_clips": 3,
        "max_clips": 15,
    }
    # Words above run 0-40; add words for the other two scenes.
    extra = []
    t = 40.0
    for i in range(80):
        extra.append({"word": f"x{i}", "start_sec": t, "end_sec": t + 1.0})
        t += 1.0
    plan["transcript_words"] = _words() + extra
    result = select_moments(plan)
    assert result["status"] == "ok"
    assert 3 <= result["clip_count"] <= 15
    for c in result["clips"]:
        assert 15.0 <= c["duration_sec"] <= 60.0
        assert c["model_score"] == "pending"
    starts = [c["start_sec"] for c in result["clips"]]
    assert starts == sorted(starts)


def test_clip_moments_no_window_crosses_scene_boundary():
    plan = {
        "source_duration_sec": 90.0,
        "transcript_words": _words() + [
            {"word": f"y{i}", "start_sec": 40.0 + i, "end_sec": 41.0 + i} for i in range(50)
        ],
        "scene_boundaries_sec": [40.0],
        "min_clips": 1,
        "max_clips": 15,
    }
    result = select_moments(plan)
    for c in result["clips"]:
        assert not (c["start_sec"] < 40.0 < c["end_sec"])


def test_clip_moments_insufficient_is_pending_not_fabricated():
    plan = {
        "source_duration_sec": 20.0,
        "transcript_words": [{"word": f"w{i}", "start_sec": float(i), "end_sec": float(i + 1)} for i in range(20)],
        "scene_boundaries_sec": [],
        "min_clips": 3,
        "max_clips": 15,
    }
    result = select_moments(plan)
    assert result["status"] == "insufficient"
    assert result["clip_count"] <= 1


def test_clip_moments_invalid_inputs():
    with pytest.raises(CapabilityError):
        select_moments({"source_duration_sec": 60.0, "transcript_words": []})
    with pytest.raises(CapabilityError):
        select_moments({
            "source_duration_sec": 60.0,
            "transcript_words": [
                {"word": "a", "start_sec": 5.0, "end_sec": 6.0},
                {"word": "b", "start_sec": 4.0, "end_sec": 5.0},
            ],
        })


# --- vertical reframe ---

def _reframe_base(**over):
    plan = {
        "source_width": 1920.0,
        "source_height": 1080.0,
        "window": {"start_sec": 0.0, "end_sec": 20.0},
        "speakers": [{"id": "a", "speaking_intervals": [[0.0, 20.0]]}],
        "face_tracks": [{"speaker_id": "a", "x": 0.4, "y": 0.2, "w": 0.2, "h": 0.3, "start_sec": 0.0, "end_sec": 20.0}],
    }
    plan.update(over)
    return plan


def test_reframe_track_follows_face():
    result = plan_reframe(_reframe_base())
    assert result["layout"] == "TRACK"
    assert result["crop"]["w"] == pytest.approx(0.3164, abs=0.001)
    assert result["video_render"] == "pending"


def test_reframe_general_when_nobody_speaks():
    plan = _reframe_base(speakers=[{"id": "a", "speaking_intervals": []}], face_tracks=[])
    result = plan_reframe(plan)
    assert result["layout"] == "GENERAL"
    assert result["blurred_background"] is True


def test_reframe_split_gate_and_silent_speaker_fallback():
    speakers = [
        {"id": "a", "speaking_intervals": [[0.0, 5.0], [10.0, 15.0]]},
        {"id": "b", "speaking_intervals": [[5.0, 10.0], [15.0, 20.0]]},
    ]
    result = plan_reframe(_reframe_base(speakers=speakers, face_tracks=[]))
    assert result["layout"] == "SPLIT"
    assert result["subtitle_seam"] is not None
    silent = _reframe_base(speakers=[
        {"id": "a", "speaking_intervals": [[0.0, 20.0]]},
        {"id": "b", "speaking_intervals": []},
    ], face_tracks=[])
    assert plan_reframe(silent)["layout"] == "TRACK"


def test_reframe_screencast_pip():
    plan = _reframe_base(screen_share=True)
    result = plan_reframe(plan)
    assert result["layout"] == "SCREENCAST"
    assert result["pip"]["speaker_id"] == "a"


def test_reframe_invalid_face_box():
    plan = _reframe_base(face_tracks=[{"speaker_id": "a", "x": 0.9, "y": 0.2, "w": 0.2, "h": 0.3, "start_sec": 0.0, "end_sec": 20.0}])
    with pytest.raises(CapabilityError):
        plan_reframe(plan)


# --- word subtitle contract ---

def test_contract_lines_and_paragraphs():
    transcript = {
        "source_duration_sec": 30.0,
        "words": [
            {"word": "hello", "start_sec": 0.0, "end_sec": 0.5, "paragraph_id": "p0"},
            {"word": "world", "start_sec": 0.5, "end_sec": 1.0, "paragraph_id": "p0"},
            {"word": "again", "start_sec": 2.0, "end_sec": 2.5, "paragraph_id": "p1"},
        ],
    }
    result = build_contract(transcript)
    assert result["word_count"] == 3
    assert result["timestamp_basis"] == "absolute source seconds"
    assert [p["paragraph_id"] for p in result["paragraphs"]] == ["p0", "p1"]
    assert result["karaoke_lines"][0]["text"] == "hello world"


def test_contract_rejects_overlap_order_and_paragraph_return():
    base = [
        {"word": "a", "start_sec": 0.0, "end_sec": 1.0, "paragraph_id": "p0"},
        {"word": "b", "start_sec": 1.0, "end_sec": 2.0, "paragraph_id": "p0"},
    ]
    with pytest.raises(CapabilityError):
        build_contract({"words": [base[1], base[0]]})
    with pytest.raises(CapabilityError):
        build_contract({"words": [
            {"word": "a", "start_sec": 0.0, "end_sec": 1.5, "paragraph_id": "p0"},
            {"word": "b", "start_sec": 1.0, "end_sec": 2.0, "paragraph_id": "p0"},
        ]})
    with pytest.raises(CapabilityError):
        build_contract({"words": base + [
            {"word": "c", "start_sec": 2.0, "end_sec": 3.0, "paragraph_id": "p1"},
            {"word": "d", "start_sec": 3.0, "end_sec": 4.0, "paragraph_id": "p0"},
        ]})


# --- publish plan ---

def test_publish_plan_dry_run_and_writeback():
    plan = build_publish_plan({
        "title": "Test short",
        "description": "A test",
        "platforms": ["tiktok", "youtube"],
        "clips": [{"clip_id": "c1"}],
        "thumbnail": {"text": "Hi"},
        "scheduled_at": "2027-01-01T10:00:00Z",
    })
    assert plan["publish_status"] == "dry_run_not_posted"
    assert all(p["status"] == "awaiting_credentials" for p in plan["per_platform"])
    assert plan["thumbnail"]["status"] == "image_pending"
    updated = record_publish_result(plan, "tiktok", "post_1", "2027-01-01T10:05:00Z")
    assert updated["publish_status"] == "partially_posted"
    updated = record_publish_result(updated, "youtube", "post_2", "2027-01-01T10:06:00Z")
    assert updated["publish_status"] == "posted"


def test_publish_plan_invalid_inputs():
    with pytest.raises(CapabilityError):
        build_publish_plan({"title": "", "platforms": ["tiktok"], "clips": [{"clip_id": "c1"}]})
    with pytest.raises(CapabilityError):
        build_publish_plan({"title": "x", "platforms": ["unknown"], "clips": [{"clip_id": "c1"}]})
    with pytest.raises(CapabilityError):
        build_publish_plan({"title": "x", "platforms": ["tiktok"], "clips": [{"clip_id": "c1"}, {"clip_id": "c1"}]})
    plan = build_publish_plan({"title": "x", "platforms": ["tiktok"], "clips": [{"clip_id": "c1"}]})
    with pytest.raises(CapabilityError):
        record_publish_result(plan, "youtube", "p1", "2027-01-01T10:00:00Z")


# --- webhook final ---

def test_webhook_sign_verify_and_tamper():
    event = make_final_event({"job_id": "job_1", "status": "completed", "payload": {"clips": 3}}, "s3cr3t")
    assert event["event"] == "job.completed"
    assert event["dedup_key"] == "job_1:job.completed"
    assert "s3cr3t" not in str(event)
    assert verify_final_event(event, "s3cr3t") is True
    tampered = dict(event)
    tampered["payload"] = {"clips": 99}
    assert verify_final_event(tampered, "s3cr3t") is False
    assert verify_final_event(event, "wrong") is False
    assert check_duplicate(["job_1:job.completed"], event) is True
    assert check_duplicate([], event) is False


def test_webhook_rejects_non_terminal():
    with pytest.raises(CapabilityError):
        make_final_event({"job_id": "job_1", "status": "running", "payload": {}}, "s3cr3t")
    with pytest.raises(CapabilityError):
        make_final_event({"job_id": "", "status": "completed", "payload": {}}, "s3cr3t")
