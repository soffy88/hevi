"""Tests for kids story gate + consistency manifest (单元 K1/R2, RENOISE_EVAL §3.3 / §4).

全代码路径、无网络、无 mock、确定性可复现。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from hevi.kids.story_gate import kids_story_gate, gate_json, StoryInput, StoryBeat, cross_check_story_manifest, generate_logline
from hevi.kids.consistency_manifest import (
    KidsConsistencyManifest,
    validate_manifest,
    canonical_json,
    to_task_specs,
    attach_to_task_shot_rows,
    read_specs_from_task_shot_rows,
    manifest_from_task_specs,
    ShotIndexMismatchError,
)
from hevi.capabilities import get

FIX = Path(__file__).parent / "fixtures" / "kids"


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


GOOD_STORIES = [
    "story_fox_star.json",
    "story_slide.json",
    "story_brush_monster.json",
    "story_seed_sprout.json",
]


@pytest.mark.parametrize("name", GOOD_STORIES)
def test_pilot_story_gate_pass(name: str) -> None:
    story = _load(name)
    report = kids_story_gate(story)
    assert report.status == "PASS", report.to_dict()
    assert len(report.findings) >= 7


def test_content_safety_violations_fail() -> None:
    story = _load("story_fox_star.json")
    story["logline"] = "小狐狸夜里遇到会吃小孩的怪兽，血流满地，非常恐怖。"
    story["theme"] = "恐怖与死亡"
    story["beats"][1]["text"] = "黑暗里怪兽张开血盆大口要吃掉小狐狸！"
    story["beats"][2]["text"] = "小狐狸拿起刀和枪去砍怪兽，到处是血。"
    story["beats"][3]["text"] = "怪兽被杀死了，尸体倒在地上。"
    report = kids_story_gate(story)
    assert report.status == "FAIL"
    assert any(f.rule == "R8_CONTENT_SAFETY" and f.severity == "FAIL" for f in report.findings)


def test_adult_content_violations_fail() -> None:
    story = _load("story_fox_star.json")
    story["logline"] = "小狐狸和朋友一起喝酒抽烟，学会了谈恋爱。"
    story["theme"] = "喝酒和恋爱"
    story["beats"][3]["text"] = "大家一起喝啤酒、抽烟，然后亲嘴谈恋爱。"
    report = kids_story_gate(story)
    assert report.status == "FAIL"
    assert any(f.rule == "R8_CONTENT_SAFETY" for f in report.findings)


def test_farewell_question_required() -> None:
    story = _load("story_fox_star.json")
    story["beats"][5]["text"] = "再见啦。"
    report = kids_story_gate(story)
    assert report.status == "FAIL"
    assert any(f.rule == "R9_FAREWELL_QUESTION" for f in report.findings)


def test_spoken_language_lock_strict() -> None:
    story = _load("story_fox_star.json")
    story["spoken_language"] = "zh-CN"
    for b in story["beats"]:
        b["text"] = "Hello kids, this is an English sentence about the fox."
    report = kids_story_gate(story)
    assert report.status == "FAIL"
    assert any(f.rule == "R7_SPOKEN_LANGUAGE" for f in report.findings)


def test_emotion_missing_fails() -> None:
    story = _load("story_fox_star.json")
    for b in story["beats"]:
        b["emotion"] = ""
    report = kids_story_gate(story)
    assert report.status == "FAIL"
    assert any(f.rule == "R4_BEAT_EMOTION" for f in report.findings)


def test_multi_theme_fails() -> None:
    story = _load("story_fox_star.json")
    story["theme"] = "分享、刷牙、勇敢、轮流和种子发芽"
    report = kids_story_gate(story)
    assert report.status == "FAIL"
    assert any(f.rule == "R5_SINGLE_THEME" for f in report.findings)


def test_recap_missing_theme_or_action_fails() -> None:
    story = _load("story_fox_star.json")
    story["beats"][4]["text"] = "然后大家去睡觉了。"
    report = kids_story_gate(story)
    assert report.status == "FAIL"
    assert any(f.rule == "R5_RECAP_THEME" for f in report.findings)


def test_logline_generation_and_formula() -> None:
    story = _load("story_fox_star.json")
    gen = generate_logline(story)
    assert len(gen) >= 8
    story["logline"] = gen
    report = kids_story_gate(story)
    assert report.status == "PASS"

    # 缺主角或缺问题的 logline 校验失败
    story["logline"] = "天上的星星真好看。"
    report_bad = kids_story_gate(story)
    assert report_bad.status == "FAIL"


# ── Manifest 校验与绑定测试 ──
def test_manifest_unknown_template_fails() -> None:
    manifest = dict(_load("manifest_fox_star.json"))
    manifest["shots"][0]["shot_spec"]["template"] = "no_such_template"
    report = validate_manifest(manifest)
    assert report.status == "FAIL"
    assert any(f.rule == "M0_SHOTSPEC_DELEGATION" for f in report.findings)


def test_manifest_unknown_sfx_fails() -> None:
    manifest = dict(_load("manifest_fox_star.json"))
    manifest["shots"][0]["shot_spec"]["sfx"] = [{"id": "no_such_sfx", "offset": 0.0}]
    report = validate_manifest(manifest)
    assert report.status == "FAIL"
    assert any(f.rule == "M0_SHOTSPEC_DELEGATION" for f in report.findings)


def test_manifest_unknown_transition_fails() -> None:
    manifest = dict(_load("manifest_fox_star.json"))
    manifest["shots"][0]["shot_spec"]["transition_in"] = "no_such_transition"
    report = validate_manifest(manifest)
    assert report.status == "FAIL"
    assert any(f.rule == "M0_SHOTSPEC_DELEGATION" for f in report.findings)


def test_manifest_unknown_shot_spec_key_fails() -> None:
    manifest = dict(_load("manifest_fox_star.json"))
    manifest["shots"][0]["shot_spec"]["tempalte"] = None  # 拼写错误键
    report = validate_manifest(manifest)
    assert report.status == "FAIL"


def test_manifest_duration_binding_mismatch_fails() -> None:
    manifest = dict(_load("manifest_fox_star.json"))
    manifest["shots"][0]["duration"] = 4.0
    manifest["shots"][0]["shot_spec"]["duration"] = 1.0  # 绑定不一致
    report = validate_manifest(manifest)
    assert report.status == "FAIL"
    assert any(f.rule == "M5_DURATION_BINDING" for f in report.findings)


def test_manifest_duplicate_shot_index_fails() -> None:
    manifest = dict(_load("manifest_fox_star.json"))
    manifest["shots"][1]["shot_index"] = 1  # 重复 S1
    report = validate_manifest(manifest)
    assert report.status == "FAIL"
    assert any(f.rule == "M7_SHOT_INDEX" for f in report.findings)


def test_manifest_missing_anchor_fails() -> None:
    manifest = dict(_load("manifest_fox_star.json"))
    manifest["characters"][0]["anchor_ref"] = None
    manifest["characters"][0]["seed"] = None
    manifest["characters"][0]["voice_ref"] = None
    report = validate_manifest(manifest)
    assert report.status == "FAIL"
    assert any(f.rule == "M6_FIXED_CHARACTER" for f in report.findings)


def test_manifest_spoken_language_mismatch_fails() -> None:
    manifest = dict(_load("manifest_fox_star.json"))
    manifest["spoken_language"][2]["language"] = "en-US"
    report = validate_manifest(manifest)
    assert report.status == "FAIL"
    assert any(f.rule == "M3_SPOKEN_LANGUAGE" for f in report.findings)


def test_manifest_unknown_ref_recursive_scan() -> None:
    manifest = dict(_load("manifest_fox_star.json"))
    manifest["shots"][2]["camera"] = "跟拍 @char_unknown"
    report = validate_manifest(manifest)
    assert report.status == "FAIL"
    assert any(f.rule == "M4_REF_RESOLUTION" for f in report.findings)


def test_attach_to_task_shot_rows_strict_error() -> None:
    manifest = KidsConsistencyManifest.model_validate(_load("manifest_fox_star.json"))
    with pytest.raises(ShotIndexMismatchError):
        attach_to_task_shot_rows(manifest, [{"task_id": "t1", "shot_index": 99, "selection_json": {}}], strict=True)


@pytest.mark.parametrize(
    "text,expected_action",
    [
        ("小狐狸打开了门，向大家打招呼。", "PASS"),
        ("大家一起打扫房间，把玩具放回篮子里。", "PASS"),
        ("小狐狸打着小雨伞，走过彩色的小路。", "PASS"),
        ("太阳公公出来啦，小狐狸热得出汗，喝了一大口水。", "PASS"),
        ("小狐狸狠狠地揍了小兔子一顿，小兔子疼得大哭。", "FAIL"),
        ("大家一起踢小松鼠，推他摔进泥坑里嘲弄他。", "FAIL"),
        ("夜里怪兽把小朋友一口吞进肚子里，再也没有出来。", "FAIL"),
        ("小熊偷偷在水里放了毒药，想让朋友们肚子疼。", "FAIL"),
        ("小狐狸点燃炸弹，轰的一声把房子炸飞了。", "FAIL"),
        ("陌生叔叔说跟我走吧，小狐狸没告诉爸爸妈妈就自己跟着他走了。", "FAIL"),
        ("大家都骂小刺猬是傻瓜、胖子，没人愿意理他。", "FAIL"),
        ("小狐狸不打人，也不骂人", "NON_FAIL"),
        ("妈妈说不能跟陌生人走", "NON_FAIL"),
    ],
)
def test_content_safety_parameterized(text: str, expected_action: str) -> None:
    story = _load("story_fox_star.json")
    story["beats"][3]["text"] = text
    report = kids_story_gate(story)
    if expected_action == "PASS":
        r8_fails = [f for f in report.findings if f.rule == "R8_CONTENT_SAFETY" and f.severity == "FAIL"]
        assert len(r8_fails) == 0, f"Expected PASS for '{text}', got findings: {report.findings}"
    elif expected_action == "FAIL":
        r8_fails = [f for f in report.findings if f.rule == "R8_CONTENT_SAFETY" and f.severity == "FAIL"]
        assert len(r8_fails) > 0, f"Expected FAIL for '{text}', status was {report.status}"
    else:  # NON_FAIL
        r8_fails = [f for f in report.findings if f.rule == "R8_CONTENT_SAFETY" and f.severity == "FAIL"]
        assert len(r8_fails) == 0, f"Expected NON_FAIL for negative context '{text}', got FAIL"


def test_attach_to_task_shot_rows_strict_modes() -> None:
    manifest = KidsConsistencyManifest.model_validate(_load("manifest_fox_star.json"))
    with pytest.raises(ShotIndexMismatchError):
        attach_to_task_shot_rows(manifest, [{"task_id": "t1", "shot_index": 99, "selection_json": {}}], strict=True)

    res = attach_to_task_shot_rows(manifest, [{"task_id": "t1", "shot_index": 99, "selection_json": {}}], strict=False)
    assert len(res) == 1


def test_manifest_from_task_specs_missing_duration_raises() -> None:
    spec = to_task_specs(KidsConsistencyManifest.model_validate(_load("manifest_fox_star.json")))[1]
    spec.duration = None
    with pytest.raises(ValueError):
        manifest_from_task_specs(
            project_id="test", episode=1, audience=KidsConsistencyManifest.model_validate(_load("manifest_fox_star.json")).audience,
            theme=KidsConsistencyManifest.model_validate(_load("manifest_fox_star.json")).theme,
            style_bible=KidsConsistencyManifest.model_validate(_load("manifest_fox_star.json")).style_bible,
            characters=KidsConsistencyManifest.model_validate(_load("manifest_fox_star.json")).characters,
            props=[], scenes=[], transition_table=[], spoken_language=[],
            specs_by_index={1: spec}, durations={}, lines={}
        )


def test_story_manifest_cross_check() -> None:
    story = StoryInput.model_validate(_load("story_fox_star.json"))
    manifest = KidsConsistencyManifest.model_validate(_load("manifest_fox_star.json"))
    res = cross_check_story_manifest(story, manifest)
    assert res.status == "OK"

    # 改坏 voice_ref
    manifest.characters[0].voice_ref = "wrong.onnx"
    res_bad = cross_check_story_manifest(story, manifest)
    assert res_bad.status == "FAIL"


# ── 确定性测试：两个独立子进程比较 SHA-256 ──
def test_determinism_via_subprocesses() -> None:
    code = (
        "import json,hashlib;"
        "from hevi.kids.story_gate import gate_json;"
        "from hevi.kids.consistency_manifest import KidsConsistencyManifest, canonical_json;"
        "s = json.load(open('tests/fixtures/kids/story_fox_star.json'));"
        "m = KidsConsistencyManifest.model_validate(json.load(open('tests/fixtures/kids/manifest_fox_star.json')));"
        "print(hashlib.sha256(gate_json(s).encode()).hexdigest(), hashlib.sha256(canonical_json(m).encode()).hexdigest())"
    )
    cmd = [sys.executable, "-c", code]
    r1 = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
    r2 = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
    assert r1 == r2
    assert len(r1) > 20


# ── R4 (KIDSMANIFEST_FIX_R4) 回归/漏杀/否定窗口 ──
@pytest.mark.parametrize(
    "text",
    [
        "小狐狸被划伤了，到处都是血。",
        "小狐狸拿起刀和枪。",
        "小狐狸用刀砍伤了小兔。",
    ],
)
def test_r4_h1_blood_weapon_hard_redline_fails(text: str) -> None:
    """H1: 血 / 武器类硬红线必须拦截（R3 回归）。"""
    story = _load("story_fox_star.json")
    story["beats"][3]["text"] = text
    report = kids_story_gate(story)
    r8_fails = [f for f in report.findings if f.rule == "R8_CONTENT_SAFETY" and f.severity == "FAIL"]
    assert len(r8_fails) > 0, f"Expected FAIL for '{text}', got {report.findings}"


@pytest.mark.parametrize(
    "text",
    [
        "坏孩子把小熊掐得哇哇叫，还把他推下楼梯。",
        "他们用石头砸小兔，把小兔的头划破了直流血。",
        "大家把小刺猬关进小黑屋，一整天都不给他饭吃。",
        "小狐狸把一壶开水浇在小猫身上，小猫疼得直哭。",
    ],
)
def test_r4_h2_common_harm_words_fail(text: str) -> None:
    """H2: 常见伤害词漏杀（掐/推下楼梯/砸/划破/关小黑屋/烫/浇）必须拦截。"""
    story = _load("story_fox_star.json")
    story["beats"][3]["text"] = text
    report = kids_story_gate(story)
    r8_fails = [f for f in report.findings if f.rule == "R8_CONTENT_SAFETY" and f.severity == "FAIL"]
    assert len(r8_fails) > 0, f"Expected FAIL for '{text}', got {report.findings}"


def test_r4_h3_negation_window_is_narrow() -> None:
    """H3: 否定只对紧随其后的词生效，不能整条豁免。"""
    story = _load("story_fox_star.json")
    story["beats"][3]["text"] = "小狐狸不吃药，把毒药给了小熊。"
    report = kids_story_gate(story)
    r8_fails = [f for f in report.findings if f.rule == "R8_CONTENT_SAFETY" and f.severity == "FAIL"]
    assert len(r8_fails) > 0, f"Expected FAIL for negation-window bypass, got {report.findings}"


@pytest.mark.parametrize("text", ["不可以下毒", "小狐狸不打人"])
def test_r4_h3_negated_forms_not_fail(text: str) -> None:
    """H3: 直接否定的教育语境不得误杀。"""
    story = _load("story_fox_star.json")
    story["beats"][3]["text"] = text
    report = kids_story_gate(story)
    r8_fails = [f for f in report.findings if f.rule == "R8_CONTENT_SAFETY" and f.severity == "FAIL"]
    assert len(r8_fails) == 0, f"Expected non-FAIL for negated '{text}', got {report.findings}"
