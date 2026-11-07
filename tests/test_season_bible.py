"""Contract tests for story.season_bible (offline, zero LLM cost)."""

import json
from pathlib import Path

import pytest

from hevi.capabilities import registry
from hevi.capabilities.errors import CapabilityError
import hevi.capabilities.season_bible as bible_cap


def _character(cid, name="主角"):
    return {
        "id": cid,
        "name": name,
        "age": 30,
        "occupation": "店员",
        "appearance": "短发，穿围裙",
        "personality_core": "外冷内热",
        "values": "守信",
        "fears": "失去亲人",
        "flaw": "不肯求助",
        "desire": "开一家自己的店",
        "backstory": "三年前来到这座城市打工",
        "mbti": "ISTJ",
        "contradiction": "对人冷淡却总在深夜多留一盏灯",
        "long_arc": "从独善其身到学会依靠他人",
    }


def _lock():
    return {
        "portrait_block": "短发，圆脸，左眉有痣",
        "outfit": "深灰围裙配白衬衫",
        "signature_props": ["旧钥匙串"],
        "face_anchors": "左眉痣，右耳耳钉",
    }


def _clean_params():
    return {
        "title": "干净季",
        "premise": "小店店员与常客在一年里互相改变的故事",
        "worldview": "现代城市小店，时间按真实四季推进，无超常设定",
        "characters": [_character("c1"), _character("c2", name="常客")],
        "scenes": [
            {"id": "s1", "name": "小店", "description": "街角二十四小时便利店"},
            {"id": "s2", "name": "后巷", "description": "小店后面的窄巷"},
        ],
        "props": [
            {"id": "p1", "name": "旧钥匙串", "description": "主角随身的旧钥匙串"},
        ],
        "visual_locks": {"c1": _lock(), "c2": _lock()},
        "tone_style": {
            "palette": "暖黄为主",
            "lighting": "自然光加暖色灯光",
            "camera_style": "手持中景为主",
            "dialogue_style": "口语短句",
            "era": "当代",
        },
    }


def _broken_params():
    params = _clean_params()
    params["premise"] = ""
    bad_char = _character("c1")
    del bad_char["contradiction"]
    del bad_char["flaw"]
    bad_char["occupation"] = ""
    params["characters"] = [bad_char, _character("c2", name="常客")]
    params["visual_locks"] = {"c1": _lock()}  # c2 has no visual lock
    params["scenes"] = [
        {"id": "s1", "name": "小店", "description": "街角店"},
        {"id": "s1", "name": "小店二", "description": "重复 id 的场景"},
    ]
    params["tone_style"] = dict(params["tone_style"])
    del params["tone_style"]["era"]
    return params


def _run(params, tmp_path):
    cap = registry.get("story.season_bible")
    result = cap.render_safe(params, tmp_path, duration=0.0, aspect="16:9", seed=42)
    report = json.loads(Path(result.qa["report_json"]).read_text(encoding="utf-8"))
    return result, report


def test_registration_idempotent():
    assert registry.get("story.season_bible").name == "story.season_bible"
    assert bible_cap.register_season_bible_capabilities_once() == []


def test_clean_bible_passes(tmp_path):
    result, report = _run(_clean_params(), tmp_path)
    assert report["passed"] is True
    assert report["counts"] == {"blocker": 0, "major": 0, "minor": 0}
    assert report["findings"] == []
    assert report["bible"] == _clean_params()
    assert result.qa["report_sha256"] == result.sha256


def test_broken_bible_severities(tmp_path):
    _, report = _run(_broken_params(), tmp_path)
    assert report["passed"] is False
    assert report["counts"] == {"blocker": 5, "major": 2, "minor": 0}
    issues = [f["issue"] for f in report["findings"]]
    assert any("premise 为空" in i for i in issues)
    assert any("缺 contradiction" in i for i in issues)
    assert any("缺 flaw" in i for i in issues)
    assert any("c2" in i and "无 visual lock" in i for i in issues)
    assert any("scenes id 重复" in i for i in issues)
    assert any("tone_style 缺 era" in i for i in issues)
    assert any("缺 occupation" in i for i in issues)
    for f in report["findings"]:
        assert set(f.keys()) == {"check", "severity", "issue", "suggestion"}


def test_major_only_still_passes(tmp_path):
    params = _clean_params()
    del params["tone_style"]["era"]
    _, report = _run(params, tmp_path)
    assert report["passed"] is True
    assert report["counts"] == {"blocker": 0, "major": 1, "minor": 0}


def test_missing_input_raises(tmp_path):
    with pytest.raises(CapabilityError):
        _run({}, tmp_path)
    with pytest.raises(CapabilityError):
        _run({"title": "空本"}, tmp_path)


def test_illegal_input_raises(tmp_path):
    params = _clean_params()
    params["characters"] = "not a list"
    with pytest.raises(CapabilityError):
        _run(params, tmp_path)
    params = _clean_params()
    params["characters"] = ["not an object"]
    with pytest.raises(CapabilityError):
        _run(params, tmp_path)
    params = _clean_params()
    params["visual_locks"] = {"c1": "not an object"}
    with pytest.raises(CapabilityError):
        _run(params, tmp_path)


def test_report_file_sha(tmp_path):
    result, report = _run(_clean_params(), tmp_path)
    report_path = Path(result.qa["report_json"])
    assert report_path.is_file()
    assert report_path.name == "bible_report.json"
    assert result.sha256 == registry.compute_sha256(report_path)
    assert report["title"] == "干净季"
