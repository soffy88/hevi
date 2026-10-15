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
from hevi.quality.kids_gate import FORBIDDEN_WORDS, check_content_safety_text, load_safety_rules
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


# ── R5 (KIDSMANIFEST_FIX_R5) patrol4 独立核验 P0/P1 ──
# P0: GOLIVE-1016 A.2 点名的 6 类暴力行为及其同义/改写必须全部拦截。
R5_MANDATED_GROUPS: list[str] = [
    "勒脖子", "踹飞", "针扎", "绑树堵嘴", "鞭打", "狗咬",
]

R5_P0_ADVERSARIAL: list[str] = [
    # 勒脖子
    "大灰狼勒住了小兔的脖子。",
    "坏人用手臂紧紧箍住小熊的喉咙，让他喘不过气。",
    "小狐狸被掐住了脖子，脸都红了。",
    # 踹飞
    "大熊一脚把小兔踹飞到墙上。",
    "他用力踢过去，小朋友整个人飞了出去。",
    "大灰狼猛踢一脚，小羊被踢得远远飞走。",
    # 针扎
    "坏巫婆拿针扎小兔的手指。",
    "她用尖尖的注射器刺进小熊的手臂。",
    "小狐狸被缝衣针刺了很多下，疼得大哭。",
    # 绑树堵嘴
    "坏人把小兔绑在树上，还用布堵住他的嘴。",
    "他们把小朋友捆在树干上，用毛巾塞住嘴巴不让他叫。",
    "小狐狸被绳索绑住手脚，封住了嘴，说不出话。",
    # 鞭打
    "大灰狼用鞭子抽打小马。",
    "他举起皮带使劲抽小朋友的背。",
    "坏国王用棍子反复抽打小仆人。",
    # 狗咬
    "大狗咬住了小兔的腿。",
    "恶犬张开嘴撕咬小朋友的手臂。",
    "那只狗用牙齿死死咬住小熊不放。",
    # 额外扩展同义（R5 词表覆盖，不能回退）
    "他死死捂住小熊的嘴，小熊快喘不过气来了。",
    "坏人把小朋友绑在椅子上，用胶带封住他的嘴。",
    "小狗咬住绳子不放。",
    "他用藤条一下下抽打小狗。",
]

# R5/P1: 幼儿高频正常词不得误报（over-blocking 会让产线不可用）。
R5_P1_BENIGN: list[str] = [
    "小刺猬背上有苹果，真可爱。",
    "妈妈在厨房用刀切菜，一刀切菜真整齐。",
    "小兔咬了一口胡萝卜，真好吃。",
    "小狐狸给妈妈扎头发。",
    "小朋友自己绑鞋带。",
    "他们把绳子捆好，装进书包里。",
    "小汽车堵住了路口，大家都排队等着。",
    "小兔把玩具塞进箱子。",
    "妈妈把饼干封进罐子里。",
    "小刺猬的苹果滚到了桌子底下。",
]

R5_HARD_REDLINE: list[str] = [
    "小兔被划伤了，到处都是血。",
    "小狐狸拿起刀和枪。",
    "小狐狸用刀砍伤了小兔。",
    "小狐狸不吃药，把毒药给了小熊。",
    "房间里有一颗炸弹。",
    "小熊死了，大家都哭了。",
]


@pytest.mark.parametrize("text", R5_P0_ADVERSARIAL)
def test_r5_p0_mandated_violent_words_blocked(text: str) -> None:
    """R5/P0: 6 类点名暴力行为 + 同义/改写全部命中违规词表。"""
    hits = check_content_safety_text(text)
    assert hits, f"Expected violation for '{text}', got {hits}"


def test_r5_p0_all_six_groups_covered_by_rules() -> None:
    """R5/P0: 6 个点名词组的字面词与核心同义词必须真实存在于规则表 category。"""
    rules = load_safety_rules()
    categories = rules.get("categories", {})
    flat = {w for words in categories.values() for w in words}
    for word in [
        "勒", "勒住", "箍住", "喉咙", "喘不过气",        # 勒脖子
        "踹", "踹飞", "踢飞", "踢倒",                      # 踹飞
        "针", "针扎", "刺进", "注射器" if "注射器" in flat else "刺穿",  # 针扎
        "绑", "绑住", "捆", "捆绑", "堵", "堵嘴", "塞", "封住嘴",           # 绑树堵嘴
        "鞭子", "鞭打", "抽打", "皮带", "棍子",            # 鞭打
        "咬", "咬住", "撕咬", "恶犬",                      # 狗咬
    ]:
        assert word in flat, f"'{word}' missing from kids_safety_rules categories"
    # 新增的 6 个 category（或并入 violence）中至少有 strangulation 级覆盖
    assert "strangulation" in categories, "expected new 'strangulation' category"


@pytest.mark.parametrize("text", R5_P1_BENIGN)
def test_r5_p1_benign_preschool_words_not_blocked(text: str) -> None:
    """R5/P1: 幼儿正常用词不得误报。"""
    hits = check_content_safety_text(text)
    assert not hits, f"Unexpected false positive for '{text}': {hits}"


def test_r5_p1_apple_no_longer_a_brand_violation() -> None:
    """R5/P1: 「苹果」在幼儿内容里首先是水果，不得再当作品牌名误报。"""
    rules = load_safety_rules()
    assert "苹果" not in rules.get("categories", {}).get("brand", [])
    assert not check_content_safety_text("小猴咬了一口苹果。")


def test_r5_p1_knife_cutting_context_exempt_but_attack_still_blocked() -> None:
    """R5/P1: 「刀 + 厨事语境」豁免，但「刀 + 攻击语境」仍拦截。"""
    assert not check_content_safety_text("妈妈在厨房用刀切菜。")
    assert not check_content_safety_text("爷爷用刀削苹果皮。")
    assert check_content_safety_text("坏人用刀刺伤了小熊。")
    assert check_content_safety_text("他拿起刀捅了过去，血流了出来。")
    assert check_content_safety_text("小狐狸拿起刀和枪。")


def test_r5_p1_negation_still_not_over_blocked() -> None:
    """R5/P1: 直接否定教育语境不得误报（R4/H3 不回退）。"""
    for text in ["小朋友不可以打人，我们要友好相处。",
                 "小狐狸不会下毒，他是好孩子。",
                 "小狐狸没有带刀，他带的是小铲子。"]:
        assert not check_content_safety_text(text), text


@pytest.mark.parametrize("text", R5_HARD_REDLINE)
def test_r5_hard_redlines_still_blocked(text: str) -> None:
    """R5: 血/武器/毒/炸/死 硬红线必须保持拦截（不得回退）。"""
    assert check_content_safety_text(text), text


def test_r5_cross_clause_evasion_still_blocked() -> None:
    """R5: 跨句规避仍被拦截（R4/H3 窄否定窗口不回退）。"""
    hits = check_content_safety_text("小狐狸不吃药，把毒药给了小熊。")
    assert "毒药" in hits


def test_r5_story_gate_blocks_mandated_violence() -> None:
    """R5: story gate 端到端对点名暴力行为必须 FAIL。"""
    story = _load("story_fox_star.json")
    story["beats"][3]["text"] = "坏人把小兔绑在树上，还用布堵住他的嘴。"
    report = kids_story_gate(story)
    r8_fails = [f for f in report.findings if f.rule == "R8_CONTENT_SAFETY" and f.severity == "FAIL"]
    assert len(r8_fails) > 0, report.findings


def test_r5_story_gate_allows_benign_preschool_text() -> None:
    """R5: story gate 端到端对幼儿正常内容不得 FAIL。"""
    story = _load("story_fox_star.json")
    story["beats"][3]["text"] = "妈妈在厨房用刀切菜，一刀切菜真整齐，小刺猬背上有苹果。"
    report = kids_story_gate(story)
    r8_fails = [f for f in report.findings if f.rule == "R8_CONTENT_SAFETY" and f.severity == "FAIL"]
    assert len(r8_fails) == 0, report.findings


def test_r5_determinism_of_content_safety_verdict() -> None:
    """R5: 判定确定性——两次调用结果一致（sha256 相同）。"""
    payload = R5_P0_ADVERSARIAL + R5_P1_BENIGN + R5_HARD_REDLINE
    h1 = hashlib.sha256(json.dumps([check_content_safety_text(t) for t in payload],
                                   ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    h2 = hashlib.sha256(json.dumps([check_content_safety_text(t) for t in payload],
                                   ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    assert h1 == h2 and len(h1) == 64
