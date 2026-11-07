"""Contract tests for the long-form method intake (offline, zero cost).

Clean-room method additions, 2026-10-25, from principle descriptions only:
- story.context_store / story.foreshadow_ledger / story.chapter_workspace
  (new module hevi.capabilities.longform_context);
- story.shot_chain discipline + selection gate (extension, chain semantics
  untouched -- see test_shot_chain.py for the chain contract);
- story.script_polish ai_flavor check (extension);
- story.season_arc episode word budget (extension);
- story.branch_forecast / story.branch_adopt comparison (item 1-iv):
  already sufficient, covered here by an isolation test, not a new system;
- harness comparison (item 4): completion is judged by the landed report
  file's ``passed`` field, recomputed here from the file itself, not from
  the returned object alone.

Fixtures are invented for these tests only: a small-town photo studio
(老街照相馆) keeper and apprentice. No novel text, no series bible, no
real plot or person is reused. No media is generated, no LLM is called.
"""

import json
from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities import registry
from hevi.capabilities.errors import CapabilityError
import hevi.capabilities.longform_context as lc_cap
import hevi.capabilities.shot_chain as shot_chain
import hevi.capabilities.storybranch as sb_cap


# ---------------------------------------------------------------------------
# Shared invented fixtures: 老街照相馆
# ---------------------------------------------------------------------------


def _context():
    return {
        "protected": {
            "characters": [
                {"id": "G01", "name": "顾山"},
                {"id": "D01", "name": "阿豆"},
            ],
            "world": {"place": "老街", "shop": "照相馆"},
            "mainline": ["顾山守着老街照相馆，阿豆来学手艺"],
        },
        "summaries": {
            "1": "顾山在老街照相馆开门，阿豆第一天来学手艺，店里冷清。",
            "2": "阿豆打翻了显影液，顾山没有责骂，只让他重新洗一张。",
        },
    }


def _ledger():
    return [
        {
            "foreshadow_id": "F_OLD",
            "status": "planted",
            "planted_chapter": 1,
            "paid_chapter": None,
            "due_chapter": 9,
            "description": "抽屉里的旧底片",
        },
        {
            "foreshadow_id": "F_NEW",
            "status": "registered",
            "planted_chapter": None,
            "paid_chapter": None,
            "due_chapter": 9,
            "description": "门口的陌生来客",
        },
    ]


def _run_cap(name, params, tmp_path, sub="out"):
    cap = registry.get(name)
    result = cap.render_safe(params, tmp_path / sub, duration=0.0, aspect="16:9", seed=42)
    report = json.loads(Path(result.qa["report_json"]).read_text(encoding="utf-8"))
    return result, report


def _issues_with(report, code_substr=None, check=None):
    out = report["findings"]
    if check is not None:
        out = [f for f in out if f.get("check") == check]
    if code_substr is not None:
        out = [f for f in out if code_substr in str(f.get("code", "")) or code_substr in f.get("issue", "")]
    return out


# ---------------------------------------------------------------------------
# 1-i. Context store: protected vs compressible summaries
# ---------------------------------------------------------------------------


def test_context_store_clean_passes_and_lands_context_json(tmp_path):
    _, report = _run_cap("story.context_store", {"context": _context()}, tmp_path)
    assert report["passed"] is True
    assert report["findings"] == []
    landed = json.loads(Path(tmp_path / "out" / "context.json").read_text(encoding="utf-8"))
    assert landed == _context()


def test_context_store_unconfirmed_protected_change_blocked_and_unchanged(tmp_path):
    proposed = {
        "characters": [
            {"id": "G01", "name": "顾山"},
            {"id": "D01", "name": "阿豆改名"},
        ],
        "world": {"place": "老街", "shop": "照相馆"},
        "mainline": ["顾山守着老街照相馆，阿豆来学手艺"],
    }
    _, report = _run_cap(
        "story.context_store",
        {"context": _context(), "proposed_protected": proposed},
        tmp_path,
    )
    assert report["passed"] is False
    blockers = [f for f in report["findings"] if f["severity"] == "blocker"]
    assert any("未确认" in f["issue"] for f in blockers)
    landed = json.loads(Path(tmp_path / "out" / "context.json").read_text(encoding="utf-8"))
    assert landed == _context()  # unconfirmed change must not take effect


def test_context_store_confirmed_protected_change_applies(tmp_path):
    proposed = {
        "characters": [
            {"id": "G01", "name": "顾山"},
            {"id": "D01", "name": "阿豆改名"},
        ],
        "world": {"place": "老街", "shop": "照相馆"},
        "mainline": ["顾山守着老街照相馆，阿豆来学手艺"],
    }
    _, report = _run_cap(
        "story.context_store",
        {
            "context": _context(),
            "proposed_protected": proposed,
            "confirm_protected_change": True,
        },
        tmp_path,
    )
    assert report["passed"] is True
    landed = json.loads(Path(tmp_path / "out" / "context.json").read_text(encoding="utf-8"))
    assert landed["protected"]["characters"][1]["name"] == "阿豆改名"


def test_context_store_compression_keeps_key_settings(tmp_path):
    ctx = _context()
    ctx["summaries"]["3"] = (
        "天很阴，街上没什么人，顾山坐在柜台后擦镜头。"
        "阿豆问起抽屉里的旧底片，顾山没有回答。"
        "傍晚雨停了，店里又安静下来。"
    )
    _, report = _run_cap(
        "story.context_store", {"context": ctx, "compress_summaries": True}, tmp_path
    )
    assert report["passed"] is True
    landed = json.loads(Path(tmp_path / "out" / "context.json").read_text(encoding="utf-8"))
    compressed = landed["summaries"]["3"]
    assert "顾山" in compressed and "阿豆" in compressed
    assert "傍晚雨停了" not in compressed  # filler sentence dropped


def test_context_store_mixed_top_level_key_is_major_not_blocker(tmp_path):
    ctx = _context()
    ctx["characters"] = [{"id": "X01", "name": "混层人物"}]
    _, report = _run_cap("story.context_store", {"context": ctx}, tmp_path)
    assert report["passed"] is True  # major warns, does not block
    assert any(f["severity"] == "major" for f in report["findings"])


def test_context_store_bad_shape_raises(tmp_path):
    with pytest.raises(CapabilityError):
        _run_cap("story.context_store", {"context": {"protected": {}}}, tmp_path)


# ---------------------------------------------------------------------------
# 1-ii. Foreshadow ledger: registered -> planted -> paid
# ---------------------------------------------------------------------------


def test_foreshadow_ledger_clean_passes(tmp_path):
    _, report = _run_cap(
        "story.foreshadow_ledger", {"ledger": _ledger(), "current_chapter": 2}, tmp_path
    )
    assert report["passed"] is True
    assert report["findings"] == []


def test_foreshadow_ledger_paid_without_source_chapter_fails(tmp_path):
    ledger = [
        {
            "foreshadow_id": "F1",
            "status": "paid",
            "planted_chapter": 1,
            "paid_chapter": None,
            "due_chapter": 5,
        }
    ]
    _, report = _run_cap(
        "story.foreshadow_ledger", {"ledger": ledger, "current_chapter": 2}, tmp_path
    )
    assert report["passed"] is False
    assert any("无 paid_chapter" in f["issue"] or "出处" in f["issue"] for f in report["findings"])


def test_foreshadow_ledger_paid_before_planted_fails(tmp_path):
    ledger = [
        {
            "foreshadow_id": "F1",
            "status": "paid",
            "planted_chapter": 3,
            "paid_chapter": 2,
            "due_chapter": 5,
        }
    ]
    _, report = _run_cap(
        "story.foreshadow_ledger", {"ledger": ledger, "current_chapter": 3}, tmp_path
    )
    assert report["passed"] is False
    assert any("不晚于埋设" in f["issue"] for f in report["findings"])


def test_foreshadow_ledger_overdue_unresolved_fails(tmp_path):
    ledger = [
        {
            "foreshadow_id": "F1",
            "status": "planted",
            "planted_chapter": 1,
            "paid_chapter": None,
            "due_chapter": 2,
        }
    ]
    _, report = _run_cap(
        "story.foreshadow_ledger", {"ledger": ledger, "current_chapter": 2}, tmp_path
    )
    assert report["passed"] is False
    assert any("悬而未决" in f["issue"] for f in report["findings"])


def test_foreshadow_ledger_duplicate_id_fails(tmp_path):
    ledger = _ledger() + [_ledger()[0]]
    _, report = _run_cap(
        "story.foreshadow_ledger", {"ledger": ledger, "current_chapter": 2}, tmp_path
    )
    assert report["passed"] is False
    assert any("重复" in f["issue"] for f in report["findings"])


# ---------------------------------------------------------------------------
# 1-iii. Safe chapter workspace: validate first, atomic write only on pass
# ---------------------------------------------------------------------------


def _chapter(**overrides):
    chap = {
        "chapter_no": 3,
        "title": "第三章：旧底片",
        "characters": ["顾山", "阿豆"],
        "foreshadows_planted": ["F_NEW"],
        "foreshadows_paid": ["F_OLD"],
        "text": "顾山从抽屉里取出旧底片，阿豆第一次看见底片上的人。",
    }
    chap.update(overrides)
    return chap


def test_chapter_workspace_clean_writes_chapter_and_updated_ledger(tmp_path):
    _, report = _run_cap(
        "story.chapter_workspace",
        {
            "new_chapter": _chapter(),
            "last_chapter_no": 2,
            "context": _context(),
            "ledger": _ledger(),
        },
        tmp_path,
    )
    assert report["passed"] is True
    chapter_path = Path(report["chapter_file"])
    assert chapter_path.is_file()
    assert "旧底片" in chapter_path.read_text(encoding="utf-8")
    ledger_path = Path(report["ledger_file"])
    assert ledger_path.is_file()
    updated = {e["foreshadow_id"]: e for e in json.loads(ledger_path.read_text(encoding="utf-8"))["ledger"]}
    assert updated["F_NEW"]["status"] == "planted"
    assert updated["F_NEW"]["planted_chapter"] == 3
    assert updated["F_OLD"]["status"] == "paid"
    assert updated["F_OLD"]["paid_chapter"] == 3
    # atomic write leaves no temp file behind
    assert not list(Path(tmp_path / "out").glob("*.tmp"))


def test_chapter_workspace_unknown_character_writes_nothing(tmp_path):
    _, report = _run_cap(
        "story.chapter_workspace",
        {
            "new_chapter": _chapter(characters=["顾山", "陌生人"]),
            "last_chapter_no": 2,
            "context": _context(),
            "ledger": _ledger(),
        },
        tmp_path,
    )
    assert report["passed"] is False
    assert report["chapter_file"] is None
    assert report["ledger_file"] is None
    out_files = {p.name for p in Path(tmp_path / "out").iterdir()}
    assert out_files == {"workspace_report.json"}


def test_chapter_workspace_skipped_chapter_number_writes_nothing(tmp_path):
    _, report = _run_cap(
        "story.chapter_workspace",
        {
            "new_chapter": _chapter(chapter_no=5),
            "last_chapter_no": 2,
            "context": _context(),
            "ledger": _ledger(),
        },
        tmp_path,
    )
    assert report["passed"] is False
    assert any("不连续" in f["issue"] for f in report["findings"])
    assert not (tmp_path / "out" / "chapter_05.txt").exists()
    assert not (tmp_path / "out" / "ledger.json").exists()


def test_chapter_workspace_paying_unplanted_writes_nothing(tmp_path):
    _, report = _run_cap(
        "story.chapter_workspace",
        {
            "new_chapter": _chapter(foreshadows_paid=["F_NEW"]),
            "last_chapter_no": 2,
            "context": _context(),
            "ledger": _ledger(),
        },
        tmp_path,
    )
    assert report["passed"] is False
    assert not (tmp_path / "out" / "chapter_03.txt").exists()
    assert not (tmp_path / "out" / "ledger.json").exists()


def test_chapter_workspace_empty_text_writes_nothing(tmp_path):
    _, report = _run_cap(
        "story.chapter_workspace",
        {
            "new_chapter": _chapter(text="  "),
            "last_chapter_no": 2,
            "context": _context(),
            "ledger": _ledger(),
        },
        tmp_path,
    )
    assert report["passed"] is False
    assert not (tmp_path / "out" / "chapter_03.txt").exists()


# ---------------------------------------------------------------------------
# 2. Shot discipline + selection gate
# ---------------------------------------------------------------------------


def _shot(shot_id, **overrides):
    shot = {
        "shot_id": shot_id,
        "dramatic_purpose": "让阿豆第一次看见旧底片，关系推进",
        "spatial_relation": "顾山在柜台后，阿豆站在柜台前，底片在两人之间",
        "continuity_note": "承接上一镜顾山拉开抽屉的手，底片位置不变",
        "camera": "固定机位，中景",
        "dialogue": [{"speaker": "阿豆", "text": "这上面是谁？"}],
        "sound_effects": ["抽屉轻响"],
        "production_notes": "暖调灯光",
        "image_prompt": "柜台后顾山把旧底片递给阿豆",
    }
    shot.update(overrides)
    return shot


def test_shot_discipline_clean_passes(tmp_path):
    shots = [_shot("S01"), _shot("S02"), _shot("S03", selection_reason="合并开场两句为一镜")]
    _, report = _run_cap(
        "story.shot_chain",
        {"shots": shots, "source_sentences": ["句一。", "句二。", "句三。"]},
        tmp_path,
    )
    assert report["passed"] is True
    assert report["discipline_issues"] == []


def test_shot_discipline_missing_purpose_fails(tmp_path):
    shots = [_shot("S01", dramatic_purpose="")]
    _, report = _run_cap("story.shot_chain", {"shots": shots}, tmp_path)
    assert report["passed"] is False
    assert any(i["code"] == "missing_dramatic_purpose" for i in report["discipline_issues"])


def test_shot_discipline_missing_spatial_and_continuity_fail(tmp_path):
    shots = [_shot("S01", spatial_relation="", continuity_note="")]
    _, report = _run_cap("story.shot_chain", {"shots": shots}, tmp_path)
    codes = {i["code"] for i in report["discipline_issues"]}
    assert "missing_spatial_relation" in codes
    assert "missing_continuity_note" in codes


def test_shot_discipline_merged_prompt_field_fails(tmp_path):
    shots = [_shot("S01", prompt="机位+对白+音效全写在一起")]
    _, report = _run_cap("story.shot_chain", {"shots": shots}, tmp_path)
    assert any(i["code"] == "merged_shot_fields" for i in report["discipline_issues"])


def test_shot_discipline_camera_holding_dialogue_fails(tmp_path):
    shots = [_shot("S01", camera={"angle": "中景", "dialogue": "这上面是谁？"})]
    _, report = _run_cap("story.shot_chain", {"shots": shots}, tmp_path)
    assert any(i["code"] == "merged_camera_field" for i in report["discipline_issues"])


def test_shot_discipline_multi_moment_image_prompt_fails(tmp_path):
    shots = [
        _shot("S01", image_prompt="顾山递出底片，然后阿豆接过，接着两人一起看向窗外")
    ]
    _, report = _run_cap("story.shot_chain", {"shots": shots}, tmp_path)
    assert any(i["code"] == "multi_moment_image_prompt" for i in report["discipline_issues"])
    shots2 = [_shot("S01", moments=["递底片", "看向窗外"])]
    _, report2 = _run_cap("story.shot_chain", {"shots": shots2}, tmp_path)
    assert any(i["code"] == "multi_moment_image_prompt" for i in report2["discipline_issues"])


def test_shot_selection_mechanical_sentence_split_fails(tmp_path):
    shots = [_shot("S01"), _shot("S02"), _shot("S03")]
    _, report = _run_cap(
        "story.shot_chain",
        {"shots": shots, "source_sentences": ["句一。", "句二。", "句三。"]},
        tmp_path,
    )
    assert report["passed"] is False
    assert any(
        i["code"] == "mechanical_sentence_split" for i in report["discipline_issues"]
    )


def test_shot_selection_merge_reason_passes(tmp_path):
    shots = [
        _shot("S01", covers_sentences=[1, 2]),
        _shot("S02"),
        _shot("S03"),
    ]
    _, report = _run_cap(
        "story.shot_chain",
        {"shots": shots, "source_sentences": ["句一。", "句二。", "句三。"]},
        tmp_path,
    )
    assert report["passed"] is True


def test_shot_discipline_function_direct():
    assert shot_chain.validate_shot_discipline([_shot("S01")]) == []
    issues = shot_chain.validate_shot_discipline([_shot("S01", dramatic_purpose=None)])
    assert issues and issues[0]["code"] == "missing_dramatic_purpose"


# ---------------------------------------------------------------------------
# 3. AI-flavor check + episode word budget
# ---------------------------------------------------------------------------


def _polish_params(scenes):
    return {"title": "照相馆一夜", "scenes": scenes}


def test_ai_flavor_clean_script_no_hits(tmp_path):
    scenes = [
        {
            "scene_id": "S01",
            "characters": ["顾山", "阿豆"],
            "action": "顾山把底片递给阿豆，阿豆低头仔细看。",
            "dialogue": [{"speaker": "阿豆", "text": "这上面是谁？"}],
        }
    ]
    _, report = _run_cap("story.script_polish", _polish_params(scenes), tmp_path)
    ai = [f for f in report["findings"] if f["check"] == "ai_flavor"]
    assert ai == []


def test_ai_flavor_parallel_triplet_hit_has_snippet_and_rule(tmp_path):
    scenes = [
        {
            "scene_id": "S01",
            "characters": ["顾山"],
            "action": "他笑了，他哭了，他走了。",
            "dialogue": [],
        }
    ]
    _, report = _run_cap("story.script_polish", _polish_params(scenes), tmp_path)
    ai = [f for f in report["findings"] if f["check"] == "ai_flavor"]
    assert any("ai_parallel" in f["issue"] and "他笑了" in f["issue"] for f in ai)


def test_ai_flavor_sublimation_and_stock_opening_hits(tmp_path):
    scenes = [
        {
            "scene_id": "S01",
            "characters": ["顾山", "阿豆"],
            "action": "顾山把底片收进抽屉，阿豆站在原地没有说话。",
            "dialogue": [{"speaker": "顾山", "text": "这就是坚持的真谛，让我们一起砥砺前行。"}],
        },
        {
            "scene_id": "S02",
            "characters": ["顾山"],
            "action": "众所周知，老街的冬天总是来得很早，顾山关上了店门。",
            "dialogue": [],
        },
    ]
    _, report = _run_cap("story.script_polish", _polish_params(scenes), tmp_path)
    ai = [f for f in report["findings"] if f["check"] == "ai_flavor"]
    assert any("ai_sublimation" in f["issue"] for f in ai)
    assert any("ai_stock_opening" in f["issue"] for f in ai)
    assert all(f["severity"] == "major" for f in ai)


def test_ai_flavor_subjectless_exclamation_hit(tmp_path):
    scenes = [
        {
            "scene_id": "S01",
            "characters": ["顾山"],
            "action": "多么美好的夜晚啊！顾山站在店门口没有动。",
            "dialogue": [],
        }
    ]
    _, report = _run_cap("story.script_polish", _polish_params(scenes), tmp_path)
    ai = [f for f in report["findings"] if f["check"] == "ai_flavor"]
    assert any("ai_exclamation" in f["issue"] for f in ai)


def _arc_episode(no, **overrides):
    ep = {
        "episode_no": no,
        "promise": "本集承诺一个变化",
        "goal": "主角想达成一件事",
        "obstacle": "一件阻碍他的事",
        "payoff": "本集兑现一个小结果",
        "exit_state": "主角状态向前一步",
        "hook": {"type": "悬念", "intensity": 4, "visual": True, "text": "门外留下一张底片"},
        "beats": [f"第 {no} 集独有的节拍"],
        "foreshadows_planted": [],
        "foreshadows_paid": [],
    }
    ep.update(overrides)
    return ep


def test_word_budget_in_range_passes(tmp_path):
    params = {
        "season_title": "照相馆季",
        "episodes": [_arc_episode(1, script_text="顾山开门。" * 100)],
        "foreshadow_ledger": [],
        "word_budget": {"min_chars": 100, "max_chars": 1000},
    }
    _, report = _run_cap("story.season_arc", params, tmp_path)
    assert report["passed"] is True
    assert not [f for f in report["findings"] if f["check"] == "episode_word_budget"]


def test_word_budget_under_and_over_are_major_warnings(tmp_path):
    params = {
        "season_title": "照相馆季",
        "episodes": [
            _arc_episode(1, script_text="短。"),
            _arc_episode(2, script_text="长句。" * 500),
        ],
        "foreshadow_ledger": [],
        "word_budget": {"min_chars": 100, "max_chars": 1000},
    }
    _, report = _run_cap("story.season_arc", params, tmp_path)
    budget = [f for f in report["findings"] if f["check"] == "episode_word_budget"]
    assert any("欠幅" in f["issue"] for f in budget)
    assert any("超幅" in f["issue"] for f in budget)
    assert all(f["severity"] == "major" for f in budget)
    assert report["passed"] is True  # warnings do not block


def test_word_budget_skips_episodes_without_text(tmp_path):
    params = {
        "season_title": "照相馆季",
        "episodes": [_arc_episode(1)],
        "foreshadow_ledger": [],
        "word_budget": {"min_chars": 100, "max_chars": 1000},
    }
    _, report = _run_cap("story.season_arc", params, tmp_path)
    assert not [f for f in report["findings"] if f["check"] == "episode_word_budget"]


def test_word_budget_invalid_range_raises(tmp_path):
    params = {
        "season_title": "照相馆季",
        "episodes": [_arc_episode(1)],
        "foreshadow_ledger": [],
        "word_budget": {"min_chars": 1000, "max_chars": 100},
    }
    with pytest.raises(CapabilityError):
        _run_cap("story.season_arc", params, tmp_path)


# ---------------------------------------------------------------------------
# 1-iv. Branch forecasting: already sufficient -- isolation test, no new system
# ---------------------------------------------------------------------------


def _fake_branches(state_dict, branch_count, seed):
    return [
        {
            "branch_id": f"branch-{i + 1}",
            "title": f"候选{i + 1}",
            "beats": [f"节拍{i + 1}"],
            "key_decisions": [{"character": "顾山", "decision": f"决定{i + 1}"}],
            "state_changes": [f"变化{i + 1}"],
            "risks": [f"风险{i + 1}"],
            "intent_match": round(0.9 - i * 0.1, 2),
        }
        for i in range(branch_count)
    ]


def test_branch_forecast_is_isolated_plan_and_adopt_leaves_canon_untouched(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(sb_cap, "_generator_fn", _fake_branches)
    monkeypatch.delenv("MONID_API_KEY", raising=False)
    canon_path = tmp_path / "canon.json"
    canon_path.write_text(json.dumps(_context(), ensure_ascii=False), encoding="utf-8")
    before = canon_path.read_bytes()
    state = {
        "canon_facts": ["顾山守着老街照相馆"],
        "characters": [{"name": "顾山"}],
        "recent_summaries": ["第一章：阿豆来学手艺。"],
        "author_intent": "下一章让旧底片第一次被看见",
    }
    forecast_dir = tmp_path / "forecast"
    result = registry.get("story.branch_forecast").render_safe(
        {**state, "branch_count": 3}, forecast_dir, duration=0.0, aspect="16:9", seed=7
    )
    # forecast writes only branches.json: a lateral comparison of 3 isolated
    # candidates, no chapter, no canon edit.
    assert {p.name for p in forecast_dir.iterdir()} == {"branches.json"}
    assert result.qa["branch_count"] == 3
    assert len(result.qa["comparison"]["rows"]) == 3
    plan_dir = tmp_path / "plan"
    adopted = registry.get("story.branch_adopt").render_safe(
        {
            "branches_path": str(forecast_dir / "branches.json"),
            "branch_id": "branch-2",
            "canon_path": str(canon_path),
        },
        plan_dir,
        duration=0.0,
        aspect="16:9",
        seed=7,
    )
    assert Path(adopted.qa["branch_plan_json"]).is_file()
    assert adopted.qa["adopted_branch_id"] == "branch-2"
    assert canon_path.read_bytes() == before  # canon never modified


# ---------------------------------------------------------------------------
# 4. Harness comparison: completion is judged by the landed report file
# ---------------------------------------------------------------------------


def _drama_package():
    import hevi.capabilities.episode_prompts as ep_cap

    bible = {
        "characters": [{"id": "C01", "name": "顾山"}],
        "scenes": [{"id": "SC01", "name": "照相馆", "block": "老街照相馆：柜台、底片柜"}],
        "visual_locks": {"C01": "顾山：深色布衣"},
    }
    shot = {
        "shot_id": "SH01",
        "scene_id": "SC01",
        "character_ids": ["C01"],
        "action": "顾山把底片递给阿豆，阿豆低头仔细看。",
        "dialogue": [{"speaker": "顾山", "text": "这张底片先留着。", "language": "中文"}],
        "camera": "固定机位，中景",
        "duration_sec": 60,
        "style": "写实、暖调",
        "first_frame": "照相馆柜台，顾山把底片递出。",
    }
    return ep_cap.compile_episode_prompts(
        {
            "bible": bible,
            "episode": {"episode_no": 1, "title": "底片", "shots": [shot]},
            "must_know": [{"fact": "底片先留着", "keywords": ["底片"]}],
        }
    )


def test_harness_drama_gates_passed_comes_from_report_file(tmp_path):
    scenes = [
        {
            "scene_id": "S01",
            "characters": ["顾山"],
            "action": "顾山把底片递给阿豆，阿豆低头仔细看。",
            "dialogue": [{"speaker": "顾山", "text": "这张底片先留着。"}],
        }
    ]
    _, report = _run_cap(
        "story.drama_gates",
        {
            "prompt_package": _drama_package(),
            "episode_scenes": scenes,
            "budget": {"max_credits": 1000, "credits_per_8s": 20},
        },
        tmp_path,
    )
    report_path = tmp_path / "out" / "drama_gates_report.json"
    assert report_path.is_file()
    from_file = json.loads(report_path.read_text(encoding="utf-8"))
    assert from_file["passed"] == report["passed"]
    assert from_file["passed"] == (
        sum(1 for f in from_file["findings"] if f["severity"] == "blocker") == 0
    )


def test_harness_script_polish_passed_comes_from_report_file(tmp_path):
    scenes = [
        {
            "scene_id": "S01",
            "characters": ["顾山", "阿豆"],
            "action": "顾山把底片递给阿豆，阿豆低头仔细看。",
            "dialogue": [{"speaker": "阿豆", "text": "这上面是谁？"}],
        }
    ]
    _, report = _run_cap("story.script_polish", _polish_params(scenes), tmp_path)
    report_path = tmp_path / "out" / "polish_report.json"
    assert report_path.is_file()
    from_file = json.loads(report_path.read_text(encoding="utf-8"))
    assert from_file["passed"] == report["passed"]
    assert from_file["passed"] == (
        sum(1 for f in from_file["findings"] if f["severity"] == "blocker") == 0
    )


# ---------------------------------------------------------------------------
# 5. Skill granularity: no registry-structure change -- each item stays a
#    separate, separately addressable capability with its own schema.
# ---------------------------------------------------------------------------


def test_new_capabilities_are_separately_registered_with_own_schemas():
    names = caps.names()
    for name in (
        "story.context_store",
        "story.foreshadow_ledger",
        "story.chapter_workspace",
    ):
        assert name in names
    assert lc_cap.register_longform_context_capabilities_once() == []
    from hevi.capabilities.registry import describe

    by_name = {item["name"]: item for item in describe()}
    for name in (
        "story.context_store",
        "story.foreshadow_ledger",
        "story.chapter_workspace",
    ):
        assert by_name[name].get("params_schema"), name
        assert by_name[name].get("description"), name
