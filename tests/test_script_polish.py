"""Contract tests for story.script_polish (offline, zero LLM cost).

Fake LLM functions stand in for the Monid backend; hermetic tests prove
full mode refuses to run without any LLM instead of faking success.
"""

import json
from pathlib import Path

import pytest

from hevi.capabilities import registry
from hevi.capabilities.errors import CapabilityError
import hevi.capabilities.script_polish as sp_cap


def _clean_params():
    return {
        "title": "干净本",
        "premise": "店员与保安的夜班故事",
        "intent": {
            "must_know": [
                {"fact": "陈默每夜来买咖啡饭团", "keywords": ["咖啡"]},
            ]
        },
        "scenes": [
            {
                "scene_id": "S01",
                "header": "便利店内",
                "characters": ["林晚", "陈默"],
                "action": "便利店内夜里，林晚站在收银台后，陈默推门进来买咖啡。",
                "dialogue": [{"speaker": "陈默", "text": "黑咖啡，一个饭团。"}],
            },
            {
                "scene_id": "S02",
                "header": "便利店内",
                "characters": ["林晚", "陈默"],
                "action": "林晚把饭团递给陈默，陈默点头道谢后离开。",
                "dialogue": [{"speaker": "林晚", "text": "明天见。"}],
            },
        ],
    }


def _broken_params():
    return {
        "title": "问题本",
        "premise": "店员偷看保安纸条的故事",
        "intent": {
            "must_know": [
                {"fact": "纸条是写给去世父亲的道歉", "keywords": ["父亲", "道歉"]},
                {"fact": "每夜三点三十三分", "keywords": ["三点三十三分"]},
            ]
        },
        "scenes": [
            {
                "scene_id": "S01",
                "time_marker": "第二夜",
                "characters": ["林晚", "陈默"],
                "action": "第二夜三点三十三分，陈默推门进来买咖啡和饭团，走向收银台。",
                "dialogue": [{"speaker": "陈默", "text": "黑咖啡，一个饭团。"}],
            },
            {
                "scene_id": "S02",
                "time_marker": "第四夜",
                "characters": ["林晚", "陈默"],
                "action": "第四夜，林晚把饭团递给陈默。",
                "dialogue": [
                    {"speaker": "林晚", "text": "嗯。"},
                ],
            },
            {"scene_id": "S03", "characters": [], "action": "", "dialogue": []},
            {
                "scene_id": "S04",
                "characters": ["林晚", "陈默"],
                "action": "林晚站在柜台后，陈默推门进来买咖啡和饭团，走向收银台。",
                "dialogue": [],
            },
            {
                "scene_id": "S05",
                "characters": ["林晚"],
                "action": "林晚站在意见箱前。",
                "dialogue": [{"speaker": "苏青", "text": "箱子是我放的。"}],
            },
        ],
    }


def _run(params, tmp_path):
    cap = registry.get("story.script_polish")
    result = cap.render_safe(params, tmp_path, duration=0.0, aspect="16:9", seed=42)
    report = json.loads(Path(result.qa["report_json"]).read_text(encoding="utf-8"))
    return result, report


def test_registration_idempotent():
    assert registry.get("story.script_polish").name == "story.script_polish"
    assert sp_cap.register_script_polish_capabilities_once() == []


def test_clean_script_passes(tmp_path):
    _, report = _run(_clean_params(), tmp_path)
    assert report["passed"] is True
    assert report["counts"] == {"blocker": 0, "major": 0, "minor": 0}
    assert report["findings"] == []
    assert "cold_reader" in report["skipped"]  # deterministic mode skips LLM checks


def test_broken_script_deterministic(tmp_path):
    _, report = _run(_broken_params(), tmp_path)
    assert report["passed"] is False
    by_issue = [f["issue"] for f in report["findings"]]

    def _has(substr):
        return any(substr in issue for issue in by_issue)

    assert _has("未向观众交付关键信息")  # 父亲/道歉 全集未出现
    assert _has("夜次跳号")  # 第二夜 → 第四夜
    assert _has("空场")  # S03
    assert _has("routine 重复未升级")  # S01 vs S04
    assert _has("对白人物未列入本场人物表")  # 苏青 not in S05 characters
    assert _has("纯应答词")  # 嗯。
    blockers = [f for f in report["findings"] if f["severity"] == "blocker"]
    assert len(blockers) == 1  # only the missing must_know fact
    assert report["checks"]["info_audit"]["passed"] is False


def test_schema_rejects_bad_mode(tmp_path):
    params = _clean_params()
    params["mode"] = "whatever"
    with pytest.raises(CapabilityError):
        _run(params, tmp_path)


def test_missing_script_input(tmp_path):
    with pytest.raises(CapabilityError):
        _run({"title": "空本"}, tmp_path)


def _fake_llm(prompt, kind):
    if kind == "script_polish_cold_reader":
        return json.dumps(
            {
                "retelling": "店员和保安在便利店相遇。",
                "unanswered": [{"question": "纸条上到底写了什么？", "importance": "high"}],
            },
            ensure_ascii=False,
        )
    if kind == "script_polish_silent":
        return json.dumps(
            {
                "scenes": [
                    {
                        "scene_id": "S02",
                        "understandable_without_dialogue": False,
                        "missing": "看不出这场戏为什么重要",
                    }
                ]
            },
            ensure_ascii=False,
        )
    if kind == "script_polish_dialogue":
        return json.dumps(
            {
                "lines": [
                    {
                        "scene_id": "S01",
                        "speaker": "陈默",
                        "text": "黑咖啡，一个饭团。",
                        "function": "无功能",
                        "speakable": True,
                        "rewrite": "改成带目的的点单。",
                    }
                ]
            },
            ensure_ascii=False,
        )
    raise AssertionError(f"unexpected kind {kind}")


def test_full_mode_fake_llm(tmp_path, monkeypatch):
    monkeypatch.setattr(sp_cap, "_llm_fn", _fake_llm)
    params = _broken_params()
    params["mode"] = "full"
    _, report = _run(params, tmp_path)
    issues = [f["issue"] for f in report["findings"]]
    assert any("冷读复述缺失关键信息" in i for i in issues)
    assert any("冷读未解问题" in i for i in issues)
    assert any("静音下看不懂" in i for i in issues)
    assert any("对白无功能或不口语" in i for i in issues)
    assert report["skipped"] == []


def test_full_mode_malformed_llm_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(sp_cap, "_llm_fn", lambda prompt, kind: "not json at all")
    params = _clean_params()
    params["mode"] = "full"
    with pytest.raises(CapabilityError):
        _run(params, tmp_path)


def test_full_mode_no_llm_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(sp_cap, "_llm_fn", None)
    monkeypatch.delenv("MONID_API_KEY", raising=False)
    params = _clean_params()
    params["mode"] = "full"
    with pytest.raises(CapabilityError):
        _run(params, tmp_path)


def test_silent_verb_words_cover_everyday_actions(tmp_path):
    """整理/来了/完成 必须算动作，不能冤枉正常场面（E1 demo 实测教训）。"""
    params = {
        "scenes": [
            {
                "scene_id": "S01",
                "characters": ["林晚"],
                "action": "林晚整理货架底层，完成了理货，陈默来了。",
                "dialogue": [],
            }
        ]
    }
    _, report = _run(params, tmp_path)
    assert report["findings"] == []


def test_markdown_parser():
    text = """INT·便利店·夜
林晚站在收银台后擦拭台面。
陈默：黑咖啡，一个饭团。
林晚：明天见。
"""
    scenes = sp_cap._parse_markdown_screenplay(text)
    assert len(scenes) == 1
    assert scenes[0]["dialogue"][0] == {"speaker": "陈默", "text": "黑咖啡，一个饭团。"}
    assert "林晚" in scenes[0]["characters"]
    assert "擦拭台面" in scenes[0]["action"]


def test_report_file_sha(tmp_path):
    result, report = _run(_clean_params(), tmp_path)
    report_path = Path(result.qa["report_json"])
    assert report_path.is_file()
    assert result.sha256 == registry.compute_sha256(report_path)
    assert report["scene_count"] == 2
