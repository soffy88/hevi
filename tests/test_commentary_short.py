"""Tests for the commentary-short line: five-segment template,
audio-first board, and Jianying draft plan (plan only).

Run: .venv/bin/python -m pytest tests/test_commentary_short.py -q

The template fixture is the Wang Yangming "少年立志" episode
(the decided first episode); Shangyang appears only as a
replaceable-topic slot in the skeleton document, not here.
"""

import copy
import importlib.util

import pytest

from hevi.capabilities import get as get_capability
from hevi.capabilities.audio_first_board import build_board
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.five_segment_short import build_template, tts_slot
from hevi.capabilities.jianying_draft_plan import (
    build_draft_plan,
    probe_jianying_library,
)

N1 = ("京师入冬的清晨，天还没亮透，胡同里已经有了动静。担水的、卖早点的，"
      "都出来了。王守仁抱着书卷，走进塾馆。案前坐着十几个孩子，窗纸透进灰白的"
      "天光，只有书页翻动，和压低了的诵读声。先生进来，没有立刻讲书，只问了一句："
      "读书，是为了什么？")
N2 = ("前排的孩子先答：登第。又有孩子跟着答，意思都差不多，登第，做官，家里人"
      "盼着的那条路。轮到守仁了。他本来可以像别人一样，顺口答登第，那句话就在嘴边。"
      "可他看着案上摊开的书，忽然觉得，那句话不对。那不是他心里的话。")
N3 = ("守仁站了起来，站得很直，手垂在身侧。他说：做圣贤。声音不高，堂上却更静了。"
      "先生没有点头，也没有摇头，只问：你知道圣贤是什么吗？守仁说：不知道。只记得"
      "书上有一句，人人都可以为尧舜。先生看了他一会儿，说：记住一句，不等于明白一句。"
      "先把书读熟，读熟了，再想这句话是什么意思。")
N4 = ("散塾后，守仁抱着书卷往家走，先生的话和他自己的话，在他心里碰在了一起。"
      "回家后，他温书，抄了一句学而时习之，一笔一画都很用力。记住一句，不等于明白一句。"
      "明白不是说出来的，是读出来的，也是以后走出来的。")
N5 = ("次日塾里照常，背诵抽到他，他背得很顺，先生点了点头。今天也一样，很多话早就记住了，"
      "真正明白却是后来的事，那个问题留下来，等着往后的日子去验证。")


def _spec(**overrides):
    segments = [
        {"index": 1, "name": "现场还原", "duration_sec": 28, "narration": N1, "image_count": 4},
        {"index": 2, "name": "困局代入", "duration_sec": 27, "narration": N2, "image_count": 4,
         "decision_pause_sec": 3.0, "question_subtitle": "如果是你，你会怎么答？"},
        {"index": 3, "name": "古人怎么做", "duration_sec": 30, "narration": N3, "image_count": 4,
         "delivery": "commentary"},
        {"index": 4, "name": "对照抽理", "duration_sec": 20, "narration": N4, "image_count": 3},
        {"index": 5, "name": "鉴今升华", "duration_sec": 15, "narration": N5, "image_count": 2,
         "modern_terms": ["今天"]},
    ]
    spec = {"title": "少年立志", "topic": "王阳明少年立志", "segments": segments,
            "total_duration_sec": 120}
    for key, value in overrides.items():
        if key.startswith("seg"):
            idx = int(key[3])
            segments[idx].update(value)
        else:
            spec[key] = value
    return spec


def _cues():
    # Shots 0-8 and 8-16 in range, final tail 16-19 flagged; research on first cue only.
    return [
        {"start_sec": 0.0, "end_sec": 4.0, "text": "秦国在西边，日子不好过。",
         "dynasty": "战国秦", "costume": "秦人深衣"},
        {"start_sec": 4.0, "end_sec": 8.0, "text": "周围的强国一个比一个硬。"},
        {"start_sec": 8.0, "end_sec": 12.0, "text": "秦孝公刚接手这个国家。"},
        {"start_sec": 12.0, "end_sec": 16.0, "text": "他面前的问题很实在。"},
        {"start_sec": 16.0, "end_sec": 19.0, "text": "再这样下去，秦国要怎么活下去。"},
    ]


# --- template: normal + boundary -------------------------------------------

def test_template_valid_reports_quota_table_and_disclaimer():
    result = build_template(_spec())
    assert result["format_label"] == "解说短片"
    assert "不是演绎真片" in result["disclaimer"]
    assert result["total_duration_sec"] == 120
    assert len(result["quota_table"]) == 5
    assert result["segments"][1]["decision_pause_sec"] == 3.0
    assert result["segments"][1]["question_subtitle"] == "如果是你，你会怎么答？"
    assert result["segments"][2]["delivery"] == "commentary"
    assert result["segments"][2]["is_live_action"] is False


def test_template_accepts_zenmezuo_question_form_too():
    spec = _spec(seg1={"question_subtitle": "如果是你，你会怎么做？"})
    assert build_template(spec)["segments"][1]["question_subtitle"] == "如果是你，你会怎么做？"


def test_template_total_at_lower_boundary_passes():
    spec = _spec()
    spec["segments"][0]["duration_sec"] = 20
    spec["segments"][2]["duration_sec"] = 20
    spec["segments"][3]["duration_sec"] = 14
    spec["segments"][4]["duration_sec"] = 10
    spec["segments"][1]["duration_sec"] = 26  # 20+26+20+14+10 = 90
    spec["total_duration_sec"] = 90
    assert build_template(spec)["total_duration_sec"] == 90


def test_template_modern_terms_allowed_only_in_segment5():
    result = build_template(_spec())
    assert result["segments"][4]["modern_terms"] == ["今天"]


def test_template_tts_slot_local_reports_pending_without_synthesis():
    slot = tts_slot("local")
    assert slot["provider"] == "local"
    assert slot["status"] in ("ready", "pending")


# --- template: illegal ------------------------------------------------------

def test_template_rejects_total_outside_90_150():
    spec = _spec()
    spec["segments"][0]["duration_sec"] = 36
    spec["segments"][1]["duration_sec"] = 32
    spec["segments"][2]["duration_sec"] = 36
    spec["segments"][3]["duration_sec"] = 26
    spec["segments"][4]["duration_sec"] = 22  # total 152
    spec["total_duration_sec"] = 152
    with pytest.raises(CapabilityError):
        build_template(spec)


def test_template_rejects_missing_decision_pause():
    spec = _spec()
    del spec["segments"][1]["decision_pause_sec"]
    with pytest.raises(CapabilityError, match="decision_pause_sec"):
        build_template(spec)


def test_template_rejects_missing_question_subtitle():
    spec = _spec()
    del spec["segments"][1]["question_subtitle"]
    with pytest.raises(CapabilityError, match="question_subtitle"):
        build_template(spec)


def test_template_rejects_question_without_required_phrasing():
    spec = _spec(seg1={"question_subtitle": "你怎么看？"})
    with pytest.raises(CapabilityError, match="如果是你"):
        build_template(spec)


def test_template_rejects_modern_terms_in_segment1():
    spec = _spec(seg0={"modern_terms": ["公司"]})
    with pytest.raises(CapabilityError, match="modern"):
        build_template(spec)


def test_template_rejects_modern_word_in_segment1_narration():
    spec = _spec(seg0={"narration": N1 + "这就像一家公司。"})
    with pytest.raises(CapabilityError, match="modern"):
        build_template(spec)


def test_template_rejects_live_action_claim_in_segment3():
    spec = _spec(seg2={"delivery": "live_action", "is_live_action": True})
    with pytest.raises(CapabilityError, match="commentary"):
        build_template(spec)


def test_template_rejects_wrong_segment_order():
    spec = _spec()
    spec["segments"][1]["name"] = "对照抽理"
    with pytest.raises(CapabilityError):
        build_template(spec)


def test_template_rejects_narration_below_quota():
    spec = _spec(seg3={"narration": "太短了。"})
    with pytest.raises(CapabilityError, match="quota"):
        build_template(spec)


def test_template_rejects_image_count_outside_quota():
    spec = _spec(seg4={"image_count": 9})
    with pytest.raises(CapabilityError, match="image_count"):
        build_template(spec)


def test_template_rejects_declared_total_mismatch():
    spec = _spec(total_duration_sec=100)
    with pytest.raises(CapabilityError, match="total_duration_sec"):
        build_template(spec)


def test_template_rejects_doubao_tts():
    with pytest.raises(CapabilityError, match="doubao"):
        tts_slot("doubao")


def test_template_rejects_key_like_fields():
    spec = _spec(api_key="x")
    with pytest.raises(CapabilityError, match="key-like"):
        build_template(spec)


# --- audio-first board ------------------------------------------------------

def test_board_cuts_at_about_8s_and_first_shot_starts_at_zero():
    result = build_board({"cues": _cues()})
    assert result["first_shot_start_sec"] == 0.0
    assert result["shot_count"] == 3
    assert result["shots"][0]["duration_sec"] == 8.0
    assert result["shots"][1]["duration_sec"] == 8.0
    assert result["shots"][2]["duration_flag"] == "final_tail_short"
    assert result["shots"][0]["sentence_text"] == (
        "秦国在西边，日子不好过。周围的强国一个比一个硬。")


def test_board_research_pending_not_invented():
    result = build_board({"cues": _cues()})
    first = result["shots"][0]
    assert first["research"]["dynasty"] == "战国秦"
    assert first["research"]["costume"] == "秦人深衣"
    assert first["research"]["person_age"] == "pending"
    assert first["research"]["architecture"] == "pending"
    assert set(first["pending_fields"]) == {"person_age", "architecture"}


def test_board_single_long_cue_kept_whole_and_flagged():
    cues = [
        {"start_sec": 0.0, "end_sec": 12.0, "text": "一句很长的话。"},
        {"start_sec": 12.0, "end_sec": 15.0, "text": "尾巴。"},
    ]
    result = build_board({"cues": cues})
    assert result["shots"][0]["duration_flag"] == "overlong"
    assert result["shots"][0]["sentence_text"] == "一句很长的话。"


def test_board_rejects_first_cue_not_at_zero():
    cues = copy.deepcopy(_cues())
    cues[0]["start_sec"] = 0.5
    cues[0]["end_sec"] = 4.0
    with pytest.raises(CapabilityError, match="start at 0"):
        build_board({"cues": cues})


def test_board_rejects_overlapping_cues():
    cues = copy.deepcopy(_cues())
    cues[1]["start_sec"] = 3.0
    with pytest.raises(CapabilityError, match="overlaps"):
        build_board({"cues": cues})


def test_board_rejects_unsorted_cues():
    cues = copy.deepcopy(_cues())
    cues[1], cues[2] = cues[2], cues[1]
    with pytest.raises(CapabilityError, match="out of order"):
        build_board({"cues": cues})


def test_board_rejects_empty_cues():
    with pytest.raises(CapabilityError):
        build_board({"cues": []})


# --- jianying draft plan -----------------------------------------------------

def test_draft_plan_keyframe_math_for_8s_push():
    shots = [
        {"shot_id": "S01", "start_sec": 0.0, "end_sec": 8.0,
         "camera_move": "push", "sentence_text": "第一句。"},
        {"shot_id": "S02", "start_sec": 8.0, "end_sec": 16.0,
         "camera_move": "pull", "sentence_text": "第二句。"},
    ]
    result = build_draft_plan({"shots": shots, "title": "少年立志"})
    video = result["tracks"]["video"]["clips"]
    assert video[0]["push_amplitude"] == 0.08
    assert video[0]["scale_start"] == 1.0 and video[0]["scale_end"] == 1.08
    assert video[0]["cut_out"]["scale"] == 1.10
    assert video[0]["cut_out"]["window_sec"] == 0.3
    assert video[1]["cut_in"]["scale"] == 1.12  # pull starts 1.08 + 0.04
    assert video[1]["cut_in"]["settle_sec"] == 0.5
    assert video[1]["cut_out"] is None
    assert result["tracks"]["subtitle"]["entries"][0]["text"] == "第一句。"
    assert result["tracks"]["audio"]["source_status"] == "pending"


def test_draft_plan_never_writes_a_draft_file():
    result = build_draft_plan({"shots": [
        {"shot_id": "S01", "start_sec": 0.0, "end_sec": 8.0, "camera_move": "hold"},
    ]})
    assert result["draft_file"] is None
    probe = probe_jianying_library()
    assert probe["installed"] == (importlib.util.find_spec("pyJianYingDraft") is not None)
    assert result["library_availability"]["installed"] == probe["installed"]


def test_draft_plan_rejects_gap_between_shots():
    shots = [
        {"shot_id": "S01", "start_sec": 0.0, "end_sec": 8.0, "camera_move": "push"},
        {"shot_id": "S02", "start_sec": 9.0, "end_sec": 16.0, "camera_move": "push"},
    ]
    with pytest.raises(CapabilityError, match="gap"):
        build_draft_plan({"shots": shots})


def test_draft_plan_rejects_overlap_and_duplicate_ids():
    with pytest.raises(CapabilityError, match="overlap"):
        build_draft_plan({"shots": [
            {"shot_id": "S01", "start_sec": 0.0, "end_sec": 8.0},
            {"shot_id": "S02", "start_sec": 7.0, "end_sec": 16.0},
        ]})
    with pytest.raises(CapabilityError, match="duplicate"):
        build_draft_plan({"shots": [
            {"shot_id": "S01", "start_sec": 0.0, "end_sec": 8.0},
            {"shot_id": "S01", "start_sec": 8.0, "end_sec": 16.0},
        ]})


def test_draft_plan_rejects_first_shot_not_at_zero():
    with pytest.raises(CapabilityError, match="start at 0"):
        build_draft_plan({"shots": [
            {"shot_id": "S01", "start_sec": 1.0, "end_sec": 9.0},
        ]})


def test_draft_plan_hold_has_zero_amplitude():
    result = build_draft_plan({"shots": [
        {"shot_id": "S01", "start_sec": 0.0, "end_sec": 8.0, "camera_move": "hold"},
    ]})
    clip = result["tracks"]["video"]["clips"][0]
    assert clip["push_amplitude"] == 0.0
    assert clip["scale_start"] == clip["scale_end"] == 1.0


# --- registry -----------------------------------------------------------------

def test_all_three_capabilities_registered():
    for name in ("story.five_segment_short", "story.audio_first_board",
                 "edit.jianying_draft_plan"):
        cap = get_capability(name)
        assert cap.name == name
        assert cap.has_media_output is False
