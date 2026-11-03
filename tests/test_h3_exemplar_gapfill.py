"""H3 exemplar gapfill (hevi-vs-h3-exemplar-prompts.md section 4, gaps 1/2/4).

Gap 1: numbering convention + role gate (qa.reference_numbering_gate).
Gap 2: segment match schema + cross-segment gate (qa.segment_match_gate).
Gap 4: millisecond timecodes + per-beat physical cameras
(qa.three_layer_clip, story.prompt_compiler beat cameras).

No dance motion chain is asserted anywhere here: the Rev.1.4
document was never supplied, so no C-chain vocabulary exists to
test. No generation runs, no keys, no budget is touched.
"""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

from hevi.capabilities.prompt_compiler import (
    PromptCompilerError,
    compile_episode,
    frames_for_provider,
)
from hevi.capabilities.reference_numbering_gate import (
    authorize_reference_numbering,
    check_reference_numbering,
)
from hevi.capabilities.scene_reference import canonical_frame_count
from hevi.capabilities.segment_match_gate import (
    authorize_segment_match,
    check_segment_match,
)
from hevi.capabilities.three_layer_clip import (
    build_three_layer_fixtures,
    check_three_layer_clip,
)
from hevi.capabilities.errors import CapabilityError


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- gap 1

def _identity_first_plan(**overrides):
    plan = {
        "route": "h3_scene_assembly",
        "numbering_convention": "identity-first",
        "pictures": [
            {"number": 1, "role": "identity", "file": "pic1.jpg",
             "sha256": _sha("pic1"), "duty": "face, age, hairstyle only"},
            {"number": 2, "role": "camera_composition", "file": "pic2.jpg",
             "sha256": _sha("pic2"),
             "duty": "overhead composition geometry only",
             "composition_only": True},
            {"number": 3, "role": "scene", "file": "pic3.jpg",
             "sha256": _sha("pic3"), "duty": "room, light, space only"},
        ],
        "audio_references": [
            {"file": "seg01_00m00p00s-00m13p27s.mp3",
             "sha256": _sha("seg01 audio"), "local_start_s": 0.0},
        ],
        "audio_mentions": ["seg01_00m00p00s-00m13p27s.mp3"],
    }
    plan.update(overrides)
    return plan


def test_numbering_identity_first_exemplar_passes():
    report = check_reference_numbering(_identity_first_plan())
    assert report["verdict"] == "pass", report["issues"]
    assert report["ok"] is True
    assert report["convention"] == "identity-first"
    assert report["route_judged"] is True


def test_numbering_h3_route_never_not_checked():
    plan = _identity_first_plan(numbering_convention=None)
    del plan["numbering_convention"]
    report = check_reference_numbering(plan)
    assert report["verdict"] == "fail"
    assert report["verdict"] != "not_checked"
    assert any(i["code"] == "missing_numbering_convention"
               for i in report["issues"])
    with pytest.raises(CapabilityError):
        authorize_reference_numbering(plan)


def test_numbering_scene_first_files_under_identity_first_fail():
    plan = _identity_first_plan()
    plan["pictures"][0]["role"] = "scene"
    plan["pictures"][2]["role"] = "identity"
    report = check_reference_numbering(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "identity_first_role_mismatch"
               for i in report["issues"])


def test_numbering_pose_stretched_for_composition_fails():
    plan = _identity_first_plan()
    plan["pictures"][1]["role"] = "pose"
    del plan["pictures"][1]["composition_only"]
    report = check_reference_numbering(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "pose_stretched_for_composition"
               for i in report["issues"])


def test_numbering_composition_without_declaration_fails():
    plan = _identity_first_plan()
    plan["pictures"][1]["composition_only"] = False
    report = check_reference_numbering(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "composition_only_undeclared"
               for i in report["issues"])


def test_numbering_unregistered_audio_fails():
    plan = _identity_first_plan(
        audio_mentions=["seg02_some_other_take.mp3"])
    report = check_reference_numbering(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "unregistered_audio_reference"
               for i in report["issues"])


def test_numbering_audio_without_local_start_fails():
    plan = _identity_first_plan()
    del plan["audio_references"][0]["local_start_s"]
    report = check_reference_numbering(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "audio_reference_missing_local_start"
               for i in report["issues"])


def test_numbering_attachment_order_mismatch_fails():
    plan = _identity_first_plan(
        attachment_order=["pic3.jpg", "pic2.jpg", "pic1.jpg"])
    report = check_reference_numbering(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "attachment_order_mismatch"
               for i in report["issues"])


def test_numbering_scene_first_passes_and_cast_is_last():
    plan = _identity_first_plan(
        numbering_convention="scene-first",
        pictures=[
            {"number": 1, "role": "scene", "file": "pic3.jpg",
             "sha256": _sha("pic3"), "duty": "room, light, space only"},
            {"number": 2, "role": "camera_composition", "file": "pic2.jpg",
             "sha256": _sha("pic2"),
             "duty": "overhead composition geometry only",
             "composition_only": True},
            {"number": 3, "role": "identity", "file": "pic1.jpg",
             "sha256": _sha("pic1"), "duty": "face, age, hairstyle only"},
        ])
    report = check_reference_numbering(plan)
    assert report["verdict"] == "pass", report["issues"]


def test_numbering_scene_first_picture1_not_scene_fails():
    plan = _identity_first_plan(numbering_convention="scene-first")
    report = check_reference_numbering(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "scene_first_picture1_not_scene"
               for i in report["issues"])


# ---------------------------------------------------------------- gap 2

def _two_segment_plan(**overrides):
    plan = {
        "segments": [
            {"segment_id": "seg01",
             "outgoing": {
                 "gesture": "hand sweeps across lens",
                 "direction": "lower-left to upper-right",
                 "speed": "fast",
                 "end_state": "hand across lens",
                 "occlusion_direction": "lower-left to upper-right",
                 "rotation_phase": 0,
             }},
            {"segment_id": "seg02",
             "incoming": {
                 "gesture": "hand sweeps across lens",
                 "direction": "lower-left to upper-right",
                 "speed": "fast",
                 "start_state": "hand across lens",
                 "occlusion_direction": "lower-left to upper-right",
                 "rotation_phase": 0,
             }},
        ],
    }
    for key, value in overrides.items():
        plan[key] = value
    return plan


def test_match_two_segment_chain_passes():
    report = check_segment_match(_two_segment_plan())
    assert report["verdict"] == "pass", report["issues"]
    assert report["boundaries"][0]["checks"]["direction"] is True
    assert report["boundaries"][0]["checks"]["speed"] is True


def test_match_reversed_direction_fails():
    plan = _two_segment_plan()
    plan["segments"][1]["incoming"]["direction"] = "upper-right to lower-left"
    report = check_segment_match(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "direction_mismatch" for i in report["issues"])


def test_match_speed_mismatch_fails():
    plan = _two_segment_plan()
    plan["segments"][1]["incoming"]["speed"] = "slow"
    report = check_segment_match(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "speed_mismatch" for i in report["issues"])


def test_match_rotation_phase_mismatch_fails():
    plan = _two_segment_plan()
    plan["segments"][1]["incoming"]["rotation_phase"] = 180
    report = check_segment_match(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "rotation_phase_mismatch"
               for i in report["issues"])


def test_match_occlusion_direction_mismatch_fails():
    plan = _two_segment_plan()
    plan["segments"][1]["incoming"]["occlusion_direction"] = "upper-right to lower-left"
    report = check_segment_match(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "occlusion_direction_mismatch"
               for i in report["issues"])


def test_match_missing_incoming_in_multi_segment_fails():
    plan = _two_segment_plan()
    del plan["segments"][1]["incoming"]
    report = check_segment_match(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "missing_incoming" for i in report["issues"])
    with pytest.raises(CapabilityError):
        authorize_segment_match(plan)


def test_match_single_segment_missing_is_not_checked_not_pass():
    report = check_segment_match({"segments": [{"segment_id": "seg01"}]})
    assert report["verdict"] == "not_checked"
    assert report["ok"] is False
    assert any(i["code"] == "single_segment_match_not_recorded"
               for i in report["issues"])
    with pytest.raises(CapabilityError):
        authorize_segment_match({"segments": [{"segment_id": "seg01"}]})


def test_match_single_segment_with_sides_still_not_checked():
    plan = _two_segment_plan()
    report = check_segment_match({"segments": [plan["segments"][0]]})
    assert report["verdict"] == "not_checked"
    assert report["ok"] is False


# ---------------------------------------------------------------- gap 4

def _ms_clip(**overrides):
    clip = {
        "style": "紫色仙侠独舞，亲密诗意克制",
        "characters": ["舞者"],
        "still_instant": "舞者坐于花亭中，俯拍开场",
        "duration_s": 13.268,
        "aspect": "9:16",
        "beats": [
            {"t_start_s": 0.0, "t_end_s": 1.083, "action": "云手起势",
             "camera_move": "static", "landing": "手停半空"},
            {"t_start_s": 1.083, "t_end_s": 2.958, "action": "穿掌转身",
             "camera_move": "static", "landing": "侧身站定"},
            {"t_start_s": 2.958, "t_end_s": 9.125, "action": "甩袖落位",
             "camera_move": "static", "landing": "袖落身侧"},
            {"t_start_s": 9.125, "t_end_s": 13.268,
             "action": "手由左下向右上掠过镜头",
             "camera_move": "static", "landing": "手遮镜头"},
        ],
    }
    clip.update(overrides)
    return clip


def test_three_layer_millisecond_timecodes_survive():
    report = check_three_layer_clip(_ms_clip())
    assert report["verdict"] == "pass", report["issues"]
    rendered = report["rendered"]
    assert "13.268" in rendered
    assert "1.083" in rendered
    assert "[0.000–1.083秒]" in rendered
    assert "2.958" in rendered and "9.125" in rendered
    assert "13.3秒" not in rendered
    assert "1.1秒" not in rendered


def _beat_camera(height: str, path: str) -> dict[str, str]:
    return {"height": height, "distance": "2米",
            "optical_axis": "水平", "path": path}


def test_three_layer_distinct_beat_cameras_pass_and_render():
    clip = _ms_clip()
    for index, beat in enumerate(clip["beats"]):
        beat["camera"] = _beat_camera(f"眼高+{index}档", f"弧线{index + 1}")
    report = check_three_layer_clip(clip)
    assert report["verdict"] == "pass", report["issues"]
    assert "高度眼高+0档" in report["rendered"]
    assert "路径弧线4" in report["rendered"]


def test_three_layer_repeated_beat_camera_fails():
    clip = _ms_clip()
    for beat in clip["beats"]:
        beat["camera"] = _beat_camera("眼高", "固定")
    report = check_three_layer_clip(clip)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "repeated_beat_camera" for i in report["issues"])


def test_three_layer_static_camera_declaration_passes():
    clip = _ms_clip(static_camera=True)
    for beat in clip["beats"]:
        beat["camera"] = _beat_camera("眼高", "固定")
    report = check_three_layer_clip(clip)
    assert report["verdict"] == "pass", report["issues"]
    assert "静态机位" in report["rendered"]


def test_three_layer_incomplete_beat_camera_fails():
    clip = _ms_clip()
    clip["beats"][0]["camera"] = {"height": "眼高", "distance": "2米"}
    report = check_three_layer_clip(clip)
    assert report["verdict"] == "fail"
    assert any(i["code"] in ("incomplete_beat_camera", "missing_beat_camera")
               for i in report["issues"])


def test_three_layer_gapfill_fixtures_all_match_expectations():
    for fixture in build_three_layer_fixtures():
        report = check_three_layer_clip(fixture["clip"])
        assert report["verdict"] == fixture["expect"], fixture["name"]


def test_prompt_compiler_beat_camera_must_be_complete():
    episode = _seg01_episode()
    episode["shots"][0]["beats"][0]["camera"] = {"height": "眼高"}
    with pytest.raises(PromptCompilerError):
        compile_episode(episode)


# ------------------------------------------------------- section 01 re-run

def _pic(tmp_path: Path, name: str) -> dict[str, str]:
    path = tmp_path / name
    data = f"gapfill fixture {name}\n".encode("utf-8")
    path.write_bytes(data)
    return {"file": str(path), "sha256": hashlib.sha256(data).hexdigest()}


def _seg01_episode() -> dict:
    cameras = [
        ("俯拍高位", "3米", "垂直向下", "固定俯拍"),
        ("眼高", "2米", "水平", "跟拍弧线"),
        ("腰高", "2.5米", "水平微仰", "弧线推进"),
        ("眼高", "1.2米", "水平", "特写跟拍"),
        ("眼高", "1米", "水平", "固定特写"),
    ]
    bounds = [(0.0, 1.083), (1.083, 2.958), (2.958, 5.5),
              (5.5, 9.125), (9.125, 13.268)]
    actions = ["云手起势坐姿开场", "穿掌转身起身", "盖步甩袖腰螺旋",
               "转身指尖近颊", "手由左下向右上掠过镜头"]
    beats = []
    for index, ((start, end), action) in enumerate(zip(bounds, actions)):
        height, distance, axis, path = cameras[index]
        beats.append({
            "beat_no": index + 1, "t_start_s": start, "t_end_s": end,
            "action": action, "sound": "原曲伴奏",
            "camera": {"height": height, "distance": distance,
                       "optical_axis": axis, "path": path},
        })
    state = {"人物": {"舞者": "紫衣独舞一人"},
             "环境": {"房间": "同一花亭内室"}}
    return {
        "episode_no": "H3SEG01",
        "title": "紫色仙侠独舞段 01 重跑",
        "target_duration_s": 13.268,
        "aspect": "9:16",
        "style": "紫色仙侠独舞，亲密诗意克制",
        "reference": "Picture 1 人物，Picture 2 俯拍构图，Picture 3 环境",
        "shots": [{
            "shot_no": "SEG01",
            "scene": "紫色仙侠私人花亭内室",
            "duration_s": 13.268,
            "camera": {
                "shot_size": "中景", "angle": "俯视", "movement": "dolly_in",
                "start_frame": {
                    "state_kind": "trigger_in_progress",
                    "description": "舞者坐于花亭中等待起势",
                },
                "end_frame": {"description": "手遮镜头收尾"},
            },
            "characters": ["舞者"],
            "continuity": {"entry_state": copy.deepcopy(state),
                           "exit_state": copy.deepcopy(state)},
            "beats": beats,
            "clips": [{"clip_id": "SEG01c1", "beats": [1, 2, 3, 4, 5]}],
        }],
    }


def test_section01_rerun_13268s_ms_numbering_match(tmp_path: Path):
    pic1, pic2, pic3 = (_pic(tmp_path, "pic1.jpg"),
                        _pic(tmp_path, "pic2.jpg"),
                        _pic(tmp_path, "pic3.jpg"))
    anchors = {"舞者": {"look": "紫衣女子，云鬓花簪",
                        "file": pic1["file"], "sha256": pic1["sha256"],
                        "confirmed": True, "wardrobe": "紫色长裙"}}
    bindings = {1: pic1, 2: pic2, 3: pic3}
    episode = _seg01_episode()
    entry_before = copy.deepcopy(episode["shots"][0]["continuity"]["entry_state"])
    exit_before = copy.deepcopy(episode["shots"][0]["continuity"]["exit_state"])
    result = compile_episode(
        episode, provider="fasth3_local", anchors=anchors,
        reference_bindings=bindings, strict=True)
    prompt = result["prompts"][0]["prompt"]
    assert "13.268" in prompt
    assert "1.083" in prompt
    assert "318帧" in prompt and "fasth3_local" in prompt
    assert "高度俯拍高位" in prompt
    assert "路径固定特写" in prompt
    # Continuity entry/exit state dictionaries survive untouched.
    assert episode["shots"][0]["continuity"]["entry_state"] == entry_before
    assert episode["shots"][0]["continuity"]["exit_state"] == exit_before
    # Frame-count routes stay forked, each on its own route.
    assert frames_for_provider(13.268, "fasth3_local") == 318
    assert canonical_frame_count(13.268, 24.0, route="h3") == 328
    # Numbering: identity-first mounting for the same three pictures.
    numbering = check_reference_numbering({
        "route": "h3_scene_assembly",
        "numbering_convention": "identity-first",
        "pictures": [
            {"number": 1, "role": "identity", "file": pic1["file"],
             "sha256": pic1["sha256"], "duty": "face, age, hairstyle only"},
            {"number": 2, "role": "camera_composition", "file": pic2["file"],
             "sha256": pic2["sha256"],
             "duty": "overhead composition geometry only",
             "composition_only": True},
            {"number": 3, "role": "scene", "file": pic3["file"],
             "sha256": pic3["sha256"], "duty": "room, light, space only"},
        ],
        "audio_references": [
            {"file": "seg01_00m00p00s-00m13p27s.mp3",
             "sha256": _sha("seg01 audio"), "local_start_s": 0.0},
        ],
        "audio_mentions": ["seg01_00m00p00s-00m13p27s.mp3"],
    })
    assert numbering["verdict"] == "pass", numbering["issues"]
    # Two-segment match chain: seg01 hands off, seg02 takes up.
    match = check_segment_match(_two_segment_plan())
    assert match["verdict"] == "pass", match["issues"]
    # Three-layer rendering of the same beats keeps milliseconds
    # and distinct per-beat cameras.
    clip = _ms_clip()
    for index, beat in enumerate(clip["beats"]):
        source = episode["shots"][0]["beats"][index]
        beat["camera"] = dict(source["camera"])
    rendered = check_three_layer_clip(clip)
    assert rendered["verdict"] == "pass", rendered["issues"]
    assert "13.268" in rendered["rendered"]
