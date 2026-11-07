"""Contract tests for story.season_arc (offline, zero LLM cost)."""

import json
from pathlib import Path

import pytest

from hevi.capabilities import registry
from hevi.capabilities.errors import CapabilityError
import hevi.capabilities.season_arc as arc_cap

_BEATS_A = "主角清晨推开店门清点货架并写下今日待办清单然后开始营业迎接客人"
_BEATS_B = "主角清晨推开店门清点货架并写下今日待办清单然后开始营业接待顾客"


def _episode(no, **overrides):
    ep = {
        "episode_no": no,
        "promise": "本集承诺一个变化",
        "goal": "主角想达成一件事",
        "obstacle": "一件阻碍他的事",
        "payoff": "本集兑现一个小结果",
        "exit_state": "主角状态向前一步",
        "hook": {"type": "悬念", "intensity": 4, "visual": True, "text": "门外留下一把钥匙"},
        "beats": [f"第 {no} 集独有的节拍：主角处理一件只在本集出现的事情"],
        "foreshadows_planted": [],
        "foreshadows_paid": [],
    }
    ep.update(overrides)
    return ep


def _clean_params():
    episodes = [
        _episode(
            1,
            beats=["主角清晨开店时在门口发现一把陌生钥匙，犹豫再三还是收进了抽屉"],
            foreshadows_planted=["F1", "F2"],
        ),
        _episode(
            2,
            beats=["常客深夜来店里点了一碗面，席间第一次提起自己多年未归的家乡"],
            foreshadows_paid=["F1"],
        ),
        _episode(
            3,
            beats=["主角把旧货架全部清空，决定把小店二楼改成可以坐下来慢慢聊天的角落"],
        ),
    ]
    ledger = [
        {
            "fact_id": "F1",
            "first_seen_ep": 1,
            "audience_knows": "观众看到一把钥匙",
            "full_truth": "钥匙属于多年未见的人",
            "planned_reveal_ep": 2,
            "status": "paid",
        },
        {
            "fact_id": "F2",
            "first_seen_ep": 1,
            "audience_knows": "观众听到一个未接来电",
            "full_truth": "来电来自下一季的关键人物",
            "planned_reveal_ep": 9,
            "status": "carried",
        },
    ]
    return {"season_title": "干净季", "episodes": episodes, "foreshadow_ledger": ledger}


def _broken_params():
    episodes = [
        _episode(1, beats=[_BEATS_A], foreshadows_planted=["F_DUE", "F_OVER"]),
        _episode(
            2,
            beats=[_BEATS_B],
            foreshadows_paid=["F_GHOST"],
            hook={"type": "内心独白", "intensity": 3, "visual": False, "text": "他心里想"},
        ),
        _episode(4, beats=["第四集独有的节拍：主角第一次走出小店去往远方办事"]),
    ]
    del episodes[1]["payoff"]
    del episodes[2]["hook"]
    ledger = [
        {
            "fact_id": "F_DUE",
            "first_seen_ep": 1,
            "audience_knows": "观众看到一个包裹",
            "full_truth": "包裹里是旧信",
            "planned_reveal_ep": 2,
            "status": "planted",
        },
        {
            "fact_id": "F_OVER",
            "first_seen_ep": 1,
            "audience_knows": "观众看到一张旧照片",
            "full_truth": "照片里的人下一季才出现",
            "planned_reveal_ep": 9,
            "status": "planted",
        },
    ]
    return {"season_title": "问题季", "episodes": episodes, "foreshadow_ledger": ledger}


def _run(params, tmp_path):
    cap = registry.get("story.season_arc")
    result = cap.render_safe(params, tmp_path, duration=0.0, aspect="16:9", seed=42)
    report = json.loads(Path(result.qa["report_json"]).read_text(encoding="utf-8"))
    return result, report


def test_registration_idempotent():
    assert registry.get("story.season_arc").name == "story.season_arc"
    assert arc_cap.register_season_arc_capabilities_once() == []


def test_clean_arc_passes(tmp_path):
    result, report = _run(_clean_params(), tmp_path)
    assert report["passed"] is True
    assert report["counts"] == {"blocker": 0, "major": 0, "minor": 0}
    assert report["findings"] == []
    assert report["episode_count"] == 3
    assert report["ledger_count"] == 2
    assert result.qa["report_sha256"] == result.sha256


def test_broken_arc_severities(tmp_path):
    _, report = _run(_broken_params(), tmp_path)
    assert report["passed"] is False
    assert report["counts"] == {"blocker": 4, "major": 2, "minor": 2}
    issues = [f["issue"] for f in report["findings"]]
    assert any("集号不连续" in i for i in issues)  # 2 -> 4
    assert any("第 2 集缺 payoff" in i for i in issues)
    assert any("第 4 集无 hook" in i for i in issues)
    assert any("非视觉型" in i for i in issues)  # ep2 hook
    assert any("F_DUE" in i and "仍未 paid" in i for i in issues)
    assert any("F_GHOST" in i and "没有任何一集埋过" in i for i in issues)
    assert any("F_OVER" in i and "超出季末" in i for i in issues)
    assert any("routine 重复未升级" in i for i in issues)
    for f in report["findings"]:
        assert set(f.keys()) == {"check", "severity", "issue", "suggestion"}


def test_non_visual_hook_only_is_minor_and_passes(tmp_path):
    params = _clean_params()
    params["episodes"][0]["hook"] = {
        "type": "内心独白", "intensity": 2, "visual": False, "text": "他心里想",
    }
    _, report = _run(params, tmp_path)
    assert report["passed"] is True
    assert report["counts"] == {"blocker": 0, "major": 0, "minor": 1}


def test_escalation_suppresses_routine_minor(tmp_path):
    params = _clean_params()
    params["episodes"][0]["beats"] = [_BEATS_A]
    params["episodes"][1]["beats"] = [_BEATS_B]
    params["episodes"][1]["escalation"] = True
    _, report = _run(params, tmp_path)
    assert report["findings"] == []


def test_missing_input_raises(tmp_path):
    with pytest.raises(CapabilityError):
        _run({}, tmp_path)
    with pytest.raises(CapabilityError):
        _run({"season_title": "空季"}, tmp_path)


def test_illegal_input_raises(tmp_path):
    params = _clean_params()
    params["episodes"] = "not a list"
    with pytest.raises(CapabilityError):
        _run(params, tmp_path)
    params = _clean_params()
    params["episodes"] = [{"promise": "缺集号"}]
    with pytest.raises(CapabilityError):
        _run(params, tmp_path)
    params = _clean_params()
    params["foreshadow_ledger"] = [{"fact_id": "F1", "status": "bogus"}]
    with pytest.raises(CapabilityError):
        _run(params, tmp_path)


def test_report_file_sha(tmp_path):
    result, report = _run(_clean_params(), tmp_path)
    report_path = Path(result.qa["report_json"])
    assert report_path.is_file()
    assert report_path.name == "arc_report.json"
    assert result.sha256 == registry.compute_sha256(report_path)
    assert report["season_title"] == "干净季"
