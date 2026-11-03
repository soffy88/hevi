"""Tests for pipeline.stable_film_assembly (B1-B7 baseline).

Free-route only: no paid channel, no network, no GPU. Full-assembly
tests use tiny synthetic sine audio and 270x480 frames so they run
in seconds; the real 197-second rerun lives outside this file.
"""

import math
import struct
import wave

import pytest
from PIL import Image, ImageDraw, ImageFont

from hevi.capabilities import mix_recipe as mr
from hevi.capabilities import stable_film_pipeline as sfp
from hevi.capabilities import subtitle_discipline as sd


PRE = {"confirmed": True, "stage": "pre_synthesis", "by": "test"}
POST = {"confirmed": True, "stage": "post_gate", "by": "test"}


def _sine_wav(path, seconds, freq=440.0, amp=0.3, rate=22050):
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = b"".join(
        struct.pack("<h", int(amp * 32767 * math.sin(2 * math.pi * freq * i / rate)))
        for i in range(int(seconds * rate)))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)
    return path


def _segments():
    return [
        {"segment_id": "s01", "title": "SEG 1", "text": "白天抬头看天，星星去哪儿了？", "duration_sec": 2.0},
        {"segment_id": "s02", "title": "SEG 2", "text": "太阳太亮，把它们的光盖住了。", "duration_sec": 2.0},
    ]


def _ship_review():
    axes = ("Hook", "Clarity", "Readability", "Motion quality",
            "Rhythm and variety", "Composition and look", "Continuity",
            "Truth", "Sound sync")
    return {"axes": {a: {"score": 9, "evidence": "at 0.5s frame #3: clear"}
                     for a in axes},
            "defects": [], "fix_round": 0}


# ------------------------------------------------------------ B6 confirmations

def test_pre_confirmation_requires_exact_true_and_stage():
    cap = {"total_chars": 10}
    rows = [{"shot_id": "s01-1"}]
    assert sfp.check_pre_synthesis(rows, cap, PRE)["allowed"] is True
    for bad in ({"confirmed": False, "stage": "pre_synthesis"},
                {"confirmed": "yes", "stage": "pre_synthesis"},
                {"confirmed": 1, "stage": "pre_synthesis"},
                {"confirmed": True, "stage": "post_gate"},
                {"confirmed": True},
                None, "continue"):
        assert sfp.check_pre_synthesis(rows, cap, bad)["allowed"] is False


def test_post_confirmation_only_advances_its_own_stage():
    report = {"status": "review", "gates": [
        {"gate": "audio.mix_recipe", "verdict": "fail", "detail": "too quiet"},
        {"gate": "qa.final_qc_gate", "verdict": "pass", "detail": "ok"},
    ]}
    # Pre-synthesis confirmation does not satisfy the post-gate point.
    assert sfp.confirm_post_gate(report, PRE)["released"] is False
    # Unacknowledged failures are not releasable.
    assert sfp.confirm_post_gate(report, POST)["released"] is False
    # Acknowledged failures release as review, never as finished.
    ok = sfp.confirm_post_gate(report, POST, acknowledged=["audio.mix_recipe"])
    assert ok["released"] is True
    assert ok["release_status"] == "review"
    assert ok["released_as"] == "可审版"


# ------------------------------------------------------------ B4 subtitles + safe zone

def test_long_breath_unit_rebreaks_without_deleting_characters():
    text = "用双筒望远镜对着天上最亮的那几颗星星的方向看，你能在白天找到它们。"
    built = sfp.build_subtitle_events(
        [{"segment_id": "s10", "text": text, "duration_sec": 4.0, "start_sec": 0.0}])
    events = built["events"]
    assert "".join(e["text"] for e in events) == text
    assert all(len(e["text"]) <= 15 for e in events)
    assert built["resplits"], "the over-budget unit must be recorded as a re-break"
    gate = sd.validate_events(
        [{"start_sec": e["start_sec"], "end_sec": e["end_sec"], "text": e["text"]}
         for e in events],
        duration_sec=4.0, transcript_source="", glossary={})
    forced = [f for f in gate["failures"] if f["kind"] == "phrase_split_forced"]
    assert forced == []


def test_caption_bbox_measured_from_real_frame_and_blank_is_undetermined(tmp_path):
    frame = tmp_path / "cap.png"
    img = Image.new("RGB", (540, 960), (18, 32, 64))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 653, 540, 758], fill=(0, 0, 0))
    try:
        font = ImageFont.truetype("/home/soffy/.local/share/fonts/wqy-zenhei.ttc", 26)
    except Exception:
        font = ImageFont.load_default()
    draw.text((16, 660), "白天看不到星星", fill=(255, 255, 255), font=font)
    img.save(frame)
    measured = sfp.measure_caption_bbox(frame)
    assert measured["measured"] is True
    assert 0.70 <= measured["bottom_fraction"] <= 0.80
    assert measured["safe_zone_pass"] is True
    assert "edge" in measured["method"]

    blank = tmp_path / "blank.png"
    Image.new("RGB", (540, 960), (18, 32, 64)).save(blank)
    und = sfp.measure_caption_bbox(blank)
    assert und["measured"] is False
    assert und["status"] == "undetermined"
    assert und["bottom_fraction"] is None


# ------------------------------------------------------------ B1 missing gates named

def test_gate_all_names_missing_gates_instead_of_passing():
    combined = sfp.gate_all(
        segment_plan={"segment_count": 1, "total_sec": 2.0, "cap_sec": 15.0},
        segment_plan_error=None, motion_gate=None, subtitle_gate=None,
        safe_zone=None, loudness=None, final_qc_report=None,
        asset_check={"ready": True, "pending_material": [], "pending_shot_ids": [],
                     "generation_shot_ids": ["s01-1"], "missing": None},
        missing_segments=[])
    assert combined["status"] == "review"
    for name in ("video.motion_beat_chart", "edit.subtitle_discipline",
                 "vertical_caption_safe_zone_measured", "audio.mix_recipe",
                 "qa.final_qc_gate"):
        assert name in combined["missing_gates"]


def test_segment_plan_failure_names_the_shot():
    segs = [{"segment_id": "s01", "text": "这是一个很长的句子，超过十五秒的配音时长。",
             "duration_sec": 20.0}]
    shots = sfp.build_sentence_shots(segs)
    from hevi.capabilities import segment_assembly as sa
    from hevi.capabilities.errors import CapabilityError
    with pytest.raises(CapabilityError, match="s01-1"):
        sa.plan_segments([{"scene_id": "main", "shots": shots}])


# ------------------------------------------------------------ B2 / B5 placeholder exclusion

def test_placeholder_beats_excluded_from_motion_ratio_and_drive_partial():
    segs = [
        {"segment_id": "s01", "title": "A", "text": "甲", "duration_sec": 2.0, "start_sec": 0.0},
        {"segment_id": "s02", "title": "B", "text": "乙", "duration_sec": 2.0, "start_sec": 2.0},
    ]
    info = sfp.build_beats(segs, {"s02"})
    assert info["placeholder_beats"][0]["change_kind"] == "static"
    from hevi.capabilities import motion_beat_chart as mb
    gate = mb.gate_chart({"thesis": info["thesis"], "beats": info["motion_beats"]})
    assert gate["verdict"] == "pass"
    assert gate["real_change_ratio"] == 1.0
    combined = sfp.gate_all(
        segment_plan={"segment_count": 1, "total_sec": 4.0, "cap_sec": 15.0},
        segment_plan_error=None, motion_gate=gate,
        subtitle_gate={"verdict": "pass", "event_count": 2, "failures": []},
        safe_zone={"measured": True, "bottom_fraction": 0.76, "safe_zone_pass": True},
        loudness={"verdict": "pass", "detail": "ok"},
        final_qc_report={"verdict": "pass", "failed_checks": [], "skipped_checks": [], "checks": {}},
        asset_check={"ready": False,
                     "pending_material": [{"shot_id": "s02-1", "asset_id": "sky",
                                           "reason": "scene image not generated"}],
                     "pending_shot_ids": ["s02-1"], "generation_shot_ids": ["s01-1"],
                     "missing": None},
        missing_segments=[])
    assert combined["status"] == "partial"
    assert sfp.delivery_filename("film", "partial") == "film_部分完成.mp4"
    assert sfp.delivery_filename("film", "finished") == "film_成片.mp4"
    assert sfp.delivery_filename("film", "review") == "film_可审版.mp4"


# ------------------------------------------------------------ B3 loudness + ducking

def test_mix_recipe_ducking_is_fixed_and_voice_keyed():
    recipe = mr.recipe()
    assert recipe["target_lufs"] == -14.0
    assert recipe["lufs_tolerance"] == 2.0
    assert recipe["true_peak_ceiling_db"] == -1.0
    assert recipe["ducking"] == {"threshold": 0.03, "ratio": 8, "attack": 20, "release": 300}
    assert recipe["ducking_key"] == "voice"
    assert recipe["ducking_target"] == "bgm"


# ------------------------------------------------------------ full assembly (tiny, synthetic)

def test_assemble_refused_without_pre_confirmation_writes_no_film(tmp_path):
    voice = _sine_wav(tmp_path / "voice.wav", 4.0)
    out = sfp.assemble_film(
        title="t", segments=_segments(), voice_path=voice, out_dir=tmp_path / "out",
        pre_confirmation={"confirmed": False, "stage": "pre_synthesis"},
        fps=5, width=270, height=480, base_name="film")
    assert out["status"] == "refused"
    assert out["mp4"] is None
    assert not list((tmp_path / "out").glob("*.mp4"))


def test_assemble_voice_only_finishes_when_all_gates_pass(tmp_path):
    from hevi.capabilities import asset_registry as ar
    voice = _sine_wav(tmp_path / "voice.wav", 4.0)
    reg = ar.new_registry()
    ar.register_asset(reg, "star", "prop", "星星")
    ar.reference_asset(reg, "episode1", "star")
    out = sfp.assemble_film(
        title="t", segments=_segments(), voice_path=voice, out_dir=tmp_path / "out",
        pre_confirmation=PRE, registry=reg, episode_id="episode1", transcript_source="",
        fps=5, width=270, height=480, base_name="film",
        critic_review=_ship_review())
    assert out["status"] == "finished", out["failures"]
    assert out["mp4"].endswith("_成片.mp4")
    assert out["loudness"]["verdict"] == "pass"
    assert out["motion_beat_ratio"] is not None and out["motion_beat_ratio"] >= 0.80
    assert out["picture_change_rate"] is not None and out["picture_change_rate"] >= 0.30
    assert out["safe_zone"]["measured"] is True
    assert (tmp_path / "out" / "manifest.json").is_file()
    assert (tmp_path / "out" / "delivery_note.txt").is_file()


def test_assemble_with_bgm_and_pending_is_partial_not_finished(tmp_path):
    from hevi.capabilities import asset_registry as ar
    voice = _sine_wav(tmp_path / "voice.wav", 4.0)
    bgm = _sine_wav(tmp_path / "bgm.wav", 4.0, freq=220.0, amp=0.2)
    reg = ar.new_registry()
    ar.register_asset(reg, "sky", "scene", "蓝天",
                      scene_skeleton={"horizon": "地平线", "foreground": "地面",
                                      "background": "天空"},
                      light="白天太阳直射")
    ar.mark_pending_material(reg, "episode1", "s02-1", "sky",
                             "scene image not generated in free route")
    out = sfp.assemble_film(
        title="t", segments=_segments(), voice_path=voice, out_dir=tmp_path / "out",
        pre_confirmation=PRE, registry=reg, episode_id="episode1",
        bgm_path=bgm, transcript_source="",
        fps=5, width=270, height=480, base_name="film")
    assert out["status"] == "partial", out["failures"]
    assert out["mp4"].endswith("_部分完成.mp4")
    assert not list((tmp_path / "out").glob("*_成片.mp4"))
    assert out["pending_shot_ids"] == ["s02-1"]
    assert out["generation_shot_ids"] == ["s01-1"]
    assert out["ducking"] == {"threshold": 0.03, "ratio": 8, "attack": 20, "release": 300}
    assert out["bgm"] is True
    manifest = (tmp_path / "out" / "manifest.json").read_text(encoding="utf-8")
    assert "s02-1" in manifest


def test_assemble_missing_segment_is_partial_and_never_padded(tmp_path):
    voice = _sine_wav(tmp_path / "voice.wav", 4.0)
    out = sfp.assemble_film(
        title="t", segments=_segments(), voice_path=voice, out_dir=tmp_path / "out",
        pre_confirmation=PRE, transcript_source="", missing_segments=["s03"],
        fps=5, width=270, height=480, base_name="film")
    assert out["status"] == "partial"
    assert out["missing_segments"] == ["s03"]
    assert "缺段" in out["delivery_note"]


# ------------------------------------------------- post-edit ASR review path
# Locks the D-group wiring: post-edit retranscription evidence flows
# through assemble_film into the subtitle gate and final QC on the
# main path. The ASR strings here are fixtures that name the wiring,
# not a real transcription: the real full-film ASR review lives
# outside the repo (see the D-group report).

def test_assemble_with_post_edit_asr_evidence_clears_stale_timeline(tmp_path):
    from hevi.capabilities import asset_registry as ar
    voice = _sine_wav(tmp_path / "voice.wav", 4.0)
    reg = ar.new_registry()
    ar.register_asset(reg, "star", "prop", "星星")
    ar.reference_asset(reg, "episode1", "star")
    asr_text = "".join(s["text"] for s in _segments())
    out = sfp.assemble_film(
        title="t", segments=_segments(), voice_path=voice, out_dir=tmp_path / "out",
        pre_confirmation=PRE, registry=reg, episode_id="episode1",
        transcript_source="post_edit_retranscription", edited=True,
        asr_text=asr_text,
        fps=5, width=270, height=480, base_name="film",
        critic_review=_ship_review())
    assert out["status"] == "finished", out["failures"]
    assert out["edited"] is True
    assert out["asr_evidence_supplied"] is True
    assert not any("stale_timeline" in f for f in out["failures"])
    assert not any("vo_asr" in f for f in out["failures"])


def test_assemble_default_transcript_source_clears_stale_timeline(tmp_path):
    # Default path: no transcript_source supplied, no edit declared.
    # Captions are built in-run from the segments, so the assembly
    # must not claim a transcript provenance the subtitle gate
    # reads as a stale timeline. The gate itself is unchanged: an
    # explicitly supplied non-fresh source still fails (see the
    # edited-without-fresh-source test below).
    from hevi.capabilities import asset_registry as ar
    voice = _sine_wav(tmp_path / "voice.wav", 4.0)
    reg = ar.new_registry()
    ar.register_asset(reg, "star", "prop", "星星")
    ar.reference_asset(reg, "episode1", "star")
    out = sfp.assemble_film(
        title="t", segments=_segments(), voice_path=voice, out_dir=tmp_path / "out",
        pre_confirmation=PRE, registry=reg, episode_id="episode1",
        fps=5, width=270, height=480, base_name="film",
        critic_review=_ship_review())
    assert out["status"] == "finished", out["failures"]
    assert out["transcript_source"] == ""
    assert out["edited"] is False
    assert not any("stale_timeline" in f for f in out["failures"])


def test_assemble_mismatched_asr_fails_vo_asr_but_not_stale_timeline(tmp_path):
    voice = _sine_wav(tmp_path / "voice.wav", 4.0)
    out = sfp.assemble_film(
        title="t", segments=_segments(), voice_path=voice, out_dir=tmp_path / "out",
        pre_confirmation=PRE, transcript_source="post_edit_retranscription",
        edited=True, asr_text="完全不相关的一段话，和剧本没有任何共同内容。",
        fps=5, width=270, height=480, base_name="film")
    assert out["status"] != "finished"
    assert any("vo_asr" in f for f in out["failures"])
    assert not any("stale_timeline" in f for f in out["failures"])


def test_assemble_edited_without_fresh_source_still_fails_stale_timeline(tmp_path):
    voice = _sine_wav(tmp_path / "voice.wav", 4.0)
    out = sfp.assemble_film(
        title="t", segments=_segments(), voice_path=voice, out_dir=tmp_path / "out",
        pre_confirmation=PRE, transcript_source="script", edited=True,
        fps=5, width=270, height=480, base_name="film")
    assert out["status"] != "finished"
    assert any("stale_timeline" in f for f in out["failures"])
