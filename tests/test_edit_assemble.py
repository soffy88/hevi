"""Contract tests for story.edit_assemble (offline, deterministic).

Fixtures are invented for these tests only: a riverside tea stall
run by two keepers. No external skill text, example plot or person
is reused. The ffmpeg tests only inspect the built command list;
ffmpeg is never executed.
"""

import json
from pathlib import Path

import pytest

from hevi.capabilities import registry
from hevi.capabilities.errors import CapabilityError
import hevi.capabilities.edit_assemble as ea_cap


def _shot_blocks(shot_id, scene_id, scene_name, action, dialogue, duration):
    return {
        "shot_id": shot_id,
        "prompt_text": "",
        "blocks": {
            "character_ids": ["C01"],
            "characters": [{"id": "C01", "name": "阿棠"}],
            "scene_id": scene_id,
            "scene_name": scene_name,
            "scene": scene_name + "：木桌、陶壶、河风",
            "action": action,
            "dialogue": dialogue,
            "camera": "固定机位",
            "style": "写实、暖调",
            "duration_sec": duration,
            "negatives": ["不换脸"],
            "first_frame": action[:12],
        },
    }


def _package(shots=None):
    if shots is None:
        shots = [
            _shot_blocks(
                "S01", "SC01", "河边茶摊",
                "阿棠走进茶摊，把陶壶放在木桌上。",
                [{"speaker": "阿棠", "text": "河风起了，先烧一壶热茶。"}],
                30,
            ),
            _shot_blocks(
                "S02", "SC02", "河边渡口",
                "老周站在渡口望向河面。",
                [{"speaker": "老周", "text": "船快到了，茶先备好。"}],
                20,
            ),
        ]
    return {"episode_no": 1, "title": "茶摊晨光", "shots": shots}


def _clips():
    return [
        {"shot_id": "S01", "file": "s01.mp4", "duration_sec": 30},
        {"shot_id": "S02", "file": "s02.mp4", "duration_sec": 20},
    ]


def _run(params, tmp_path):
    cap = registry.get("story.edit_assemble")
    result = cap.render_safe(params, tmp_path, duration=0.0, aspect="16:9", seed=42)
    report = json.loads(Path(result.qa["report_json"]).read_text(encoding="utf-8"))
    return result, report


def test_registry_and_basic_edl(tmp_path):
    result, report = _run({"prompt_package": _package(), "clips": _clips()}, tmp_path)
    assert result.sha256
    assert report["edit_ready"] is True
    assert report["total_duration_sec"] == 50
    edl = report["edl"]
    assert [e["shot_id"] for e in edl] == ["S01", "S02"]
    assert (edl[0]["timeline_start_sec"], edl[0]["timeline_end_sec"]) == (0, 30)
    assert (edl[1]["timeline_start_sec"], edl[1]["timeline_end_sec"]) == (30, 50)
    assert edl[0]["transition"] == "cut"
    assert edl[0]["in_sec"] == 0 and edl[0]["out_sec"] == 30
    changes = report["spatial_continuity"]["scene_changes"]
    assert len(changes) == 1 and changes[0]["at_sec"] == 30
    assert report["spatial_continuity"]["scene_sequence"] == ["SC01", "SC02"]


def test_clip_in_out_points_shift_timeline(tmp_path):
    clips = [
        {"shot_id": "S01", "file": "s01.mp4", "duration_sec": 40,
         "in_sec": 5, "out_sec": 35},
        {"shot_id": "S02", "file": "s02.mp4", "duration_sec": 20},
    ]
    _, report = _run({"prompt_package": _package(), "clips": clips}, tmp_path)
    assert report["edl"][0]["duration_sec"] == 30
    assert report["edl"][1]["timeline_start_sec"] == 30
    assert report["total_duration_sec"] == 50


def test_missing_clip_raises(tmp_path):
    with pytest.raises(CapabilityError, match="no finished clip for shot S02"):
        _run({"prompt_package": _package(), "clips": _clips()[:1]}, tmp_path)


def test_unknown_and_duplicate_clips_raise(tmp_path):
    clips = _clips() + [{"shot_id": "S99", "file": "x.mp4", "duration_sec": 5}]
    with pytest.raises(CapabilityError, match="unknown shots"):
        _run({"prompt_package": _package(), "clips": clips}, tmp_path)
    clips = _clips() + [{"shot_id": "S01", "file": "dup.mp4", "duration_sec": 5}]
    with pytest.raises(CapabilityError, match="duplicate clip"):
        _run({"prompt_package": _package(), "clips": clips}, tmp_path)


def test_bad_clip_ranges_raise(tmp_path):
    bad = [
        {"shot_id": "S01", "file": "s01.mp4", "duration_sec": 30, "in_sec": 20, "out_sec": 20},
        {"shot_id": "S01", "file": "s01.mp4", "duration_sec": 30, "out_sec": 31},
        {"shot_id": "S01", "file": "s01.mp4", "duration_sec": 30, "in_sec": -1},
        {"shot_id": "S01", "file": "s01.mp4"},
        {"shot_id": "S01", "duration_sec": 30},
    ]
    for clip in bad:
        with pytest.raises(CapabilityError):
            _run({"prompt_package": _package(), "clips": [clip, _clips()[1]]}, tmp_path)


def test_unknown_transition_raises(tmp_path):
    package = _package()
    package["shots"][0]["transition"] = "wipe"
    with pytest.raises(CapabilityError, match="unknown transition"):
        _run({"prompt_package": package, "clips": _clips()}, tmp_path)


def test_music_pending_without_music(tmp_path):
    _, report = _run({"prompt_package": _package(), "clips": _clips()}, tmp_path)
    assert report["music_beat_table"]["status"] == "pending"
    assert report["music_beat_table"]["cuts"] == []
    assert report["ffmpeg"]["status"] == "pending"


def test_music_bpm_grid_on_and_off_beat(tmp_path):
    _, report = _run(
        {"prompt_package": _package(), "clips": _clips(), "music": {"bpm": 120}},
        tmp_path,
    )
    beat = report["music_beat_table"]
    assert beat["status"] == "ready"
    assert beat["cuts"][0]["boundary_sec"] == 30
    assert beat["cuts"][0]["on_beat"] is True  # 120bpm: beat every 0.5s
    # Off-beat case, exercised on the helper: 100bpm beats fall at
    # 24.6/25.2 around a 25s boundary, so the boundary is off beat.
    table, _ = ea_cap._music_beat_table({"bpm": 100}, 50, [25])
    assert table["cuts"][0]["on_beat"] is False
    assert table["cuts"][0]["nearest_beat_sec"] == 25.2
    assert table["cuts"][0]["offset_sec"] == 0.2


def test_music_explicit_beats_and_short_music_partial(tmp_path):
    _, report = _run(
        {"prompt_package": _package(), "clips": _clips(),
         "music": {"beats": [10, 30, 45], "duration_sec": 40}},
        tmp_path,
    )
    beat = report["music_beat_table"]
    assert beat["status"] == "partial"  # 40s music < 50s episode
    assert beat["cuts"][0]["nearest_beat_sec"] == 30
    assert any(f["check"] == "music" for f in report["findings"])


def test_music_without_bpm_or_beats_is_pending(tmp_path):
    _, report = _run(
        {"prompt_package": _package(), "clips": _clips(), "music": {"title": "无名曲"}},
        tmp_path,
    )
    assert report["music_beat_table"]["status"] == "pending"
    assert any(f["check"] == "music" for f in report["findings"])


def test_sound_layers_caller_wins_over_keyword_rule(tmp_path):
    package = _package()
    package["shots"][0]["sound_cues"] = [
        {"layer": "脚步声", "file": "steps.wav", "trigger_action": "阿棠走进茶摊"},
    ]
    _, report = _run({"prompt_package": package, "clips": _clips()}, tmp_path)
    layers = report["edl"][0]["sound_layers"]
    by_layer = {layer["layer"]: layer for layer in layers}
    assert by_layer["脚步声"]["source"] == "caller-cue"
    assert by_layer["脚步声"]["file"] == "steps.wav"
    # "放在" still fires the generic rule layer, marked as a suggestion.
    assert by_layer["器物声"]["source"] == "keyword-rule"
    assert by_layer["器物声"]["file"] is None
    assert by_layer["器物声"]["trigger_action"].startswith("阿棠走进茶摊")
    assert by_layer["器物声"]["start_sec"] == 0
    assert report["sound_layers"] == [layer for e in report["edl"] for layer in e["sound_layers"]]


def test_subtitle_spec_and_lines(tmp_path):
    _, report = _run({"prompt_package": _package(), "clips": _clips()}, tmp_path)
    spec = report["subtitle_spec"]
    assert spec["font_size_rel"] == 0.042
    assert spec["max_chars_per_line"] == 20
    assert spec["safe_area"]["width_pct"] == 90
    lines = report["edl"][0]["subtitle_lines"]
    assert len(lines) == 1
    assert lines[0]["timing"] == "estimated-even-split"
    assert (lines[0]["start_sec"], lines[0]["end_sec"]) == (0, 30)
    # A pure-visual shot (explicit empty dialogue) yields no lines.
    package = _package()
    package["shots"][1]["blocks"]["dialogue"] = []
    _, report2 = _run({"prompt_package": package, "clips": _clips()}, tmp_path)
    assert report2["edl"][1]["subtitle_lines"] == []
    # A long line is chunked at 20 chars.
    package = _package()
    package["shots"][0]["blocks"]["dialogue"] = [
        {"speaker": "阿棠", "text": "这句话很长很长很长很长很长很长很长很长很长很长很长很长很长"}
    ]
    _, report3 = _run({"prompt_package": package, "clips": _clips()}, tmp_path)
    texts = [line["text"] for line in report3["edl"][0]["subtitle_lines"]]
    assert all(len(t) <= 20 for t in texts) and len(texts) > 1


def test_assemble_ffmpeg_command_is_built_not_run(tmp_path):
    _, report = _run(
        {"prompt_package": _package(), "clips": _clips(),
         "subtitle_file": "subs.srt", "music_file": "bgm.mp3",
         "sfx_files": [{"file": "steps.wav", "delay_sec": 2.5}]},
        tmp_path,
    )
    ff = report["ffmpeg"]
    cmd = ff["command"]
    assert cmd[0] == "ffmpeg"
    assert "-filter_complex" in cmd
    joined = " ".join(cmd)
    assert "concat=n=2:v=1:a=1" in joined
    assert "amix" in joined and "adelay=2500" in joined
    assert "subtitles=" in joined and "subs.srt" in joined
    assert cmd[-1] == "episode_assembled.mp4"
    assert not Path(tmp_path / "episode_assembled.mp4").exists()
    assert any(layer["layer"] == "器物声" for layer in ff["unmixed_sound_layers"])


def test_assemble_ffmpeg_rejects_dissolve_and_missing_subtitle():
    edl = [{"shot_id": "S01", "source_file": "s01.mp4", "transition": "dissolve",
            "sound_layers": []}]
    with pytest.raises(CapabilityError, match="cuts only"):
        ea_cap.assemble_ffmpeg(edl, "subs.srt")
    edl_cut = [{"shot_id": "S01", "source_file": "s01.mp4", "transition": "cut",
                "sound_layers": []}]
    with pytest.raises(CapabilityError, match="subtitle_file is required"):
        ea_cap.assemble_ffmpeg(edl_cut, "")
    with pytest.raises(CapabilityError, match="non-empty list"):
        ea_cap.assemble_ffmpeg([], "subs.srt")


def test_edit_ready_false_on_missing_scene_and_dialogue(tmp_path):
    raw_shot = {"shot_id": "S01", "action": "阿棠站在摊前。", "duration_sec": 10}
    package = {"episode_no": 1, "title": "缺字段", "shots": [raw_shot]}
    clips = [{"shot_id": "S01", "file": "s01.mp4", "duration_sec": 10}]
    _, report = _run({"prompt_package": package, "clips": clips}, tmp_path)
    assert report["edit_ready"] is False
    assert report["counts"]["blocker"] == 2  # missing scene + missing dialogue
    assert len(report["edl"]) == 1  # EDL still emitted so the editor can fix it


def test_blueprint_present_with_qa_plan(tmp_path):
    _, report = _run({"prompt_package": _package(), "clips": _clips()}, tmp_path)
    blueprint = report["blueprint"]
    assert blueprint["phase"] == "blueprint"
    assert blueprint["intake_summary"]["shot_count"] == 2
    assert blueprint["intake_summary"]["total_duration_sec"] == 50
    assert blueprint["intake_summary"]["missing_inputs"] == ["音乐信息（bpm 或节拍点）", "字幕文件"]
    assert blueprint["contact_sheet"][0]["shot_id"] == "S01"
    assert blueprint["contact_sheet"][0]["first_frame"]
    assert blueprint["edit_plan"]["sound_layer_count"] == len(report["sound_layers"])
    assert any("面部" in item for item in blueprint["qa_plan"])
    assert blueprint["qa_checks"] == {"duration_mismatches": [], "trimmed_shots": []}
    assert report["blueprint_gate"] == {
        "required": False, "approved": False, "blocked": False,
    }
    assert report["mix_policy"]["dialogue"].startswith("人声优先")


def test_trimmed_clip_flagged_for_voice_cut_check(tmp_path):
    clips = [
        {"shot_id": "S01", "file": "s01.mp4", "duration_sec": 40,
         "in_sec": 5, "out_sec": 35},
        {"shot_id": "S02", "file": "s02.mp4", "duration_sec": 20},
    ]
    _, report = _run({"prompt_package": _package(), "clips": clips}, tmp_path)
    # Used length (30) still matches the prompt shot length: no av finding.
    assert report["blueprint"]["qa_checks"]["duration_mismatches"] == []
    trimmed = report["blueprint"]["qa_checks"]["trimmed_shots"]
    assert len(trimmed) == 1 and trimmed[0]["shot_id"] == "S01"
    assert any(f["check"] == "voice_cut" for f in report["findings"])


def test_av_duration_mismatch_is_major_finding(tmp_path):
    clips = [
        {"shot_id": "S01", "file": "s01.mp4", "duration_sec": 20},
        {"shot_id": "S02", "file": "s02.mp4", "duration_sec": 20},
    ]
    _, report = _run({"prompt_package": _package(), "clips": clips}, tmp_path)
    mismatches = report["blueprint"]["qa_checks"]["duration_mismatches"]
    assert len(mismatches) == 1 and mismatches[0]["shot_id"] == "S01"
    assert mismatches[0]["diff_sec"] == -10
    assert any(
        f["check"] == "av_duration" and f["severity"] == "major"
        for f in report["findings"]
    )


def test_blueprint_gate_blocks_ffmpeg_until_approved(tmp_path):
    base = {"prompt_package": _package(), "clips": _clips(),
            "subtitle_file": "subs.srt", "require_blueprint_approval": True}
    _, report = _run(base, tmp_path)
    assert report["ffmpeg"]["status"] == "blocked"
    assert report["blueprint_gate"]["blocked"] is True
    _, report2 = _run({**base, "blueprint_approved": True}, tmp_path)
    assert report2["ffmpeg"]["command"][0] == "ffmpeg"
    edl = report2["edl"]
    with pytest.raises(CapabilityError, match="blueprint not approved"):
        ea_cap.assemble_ffmpeg(
            edl, "subs.srt", require_blueprint_approval=True,
            blueprint_approved=False,
        )


def test_face_safe_rule_in_subtitle_spec(tmp_path):
    _, report = _run({"prompt_package": _package(), "clips": _clips()}, tmp_path)
    face_safe = report["subtitle_spec"]["face_safe"]
    assert "不压人物面部" in face_safe["rule"]
    assert "核对" in face_safe["check"]
