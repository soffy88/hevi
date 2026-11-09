"""Rules, compiler and schema tests for the ai_drama line."""

from __future__ import annotations

import json
from pathlib import Path

from hevi.ai_drama.compile import compile_storyboard, draft_script_from_theme
from hevi.ai_drama.rules import (
    check_assets,
    check_edit,
    check_game_pov,
    check_script,
    check_storyboard,
    passed,
    summarise,
)
from hevi.ai_drama.schema import normalize_script, normalize_storyboard

DATA = Path(__file__).resolve().parents[2] / "hevi" / "ai_drama" / "data"


def sample() -> dict:
    return normalize_script(json.loads((DATA / "sample_episode.json").read_text(encoding="utf-8")))


def game() -> dict:
    return normalize_script(json.loads((DATA / "sample_game_pov.json").read_text(encoding="utf-8")))


def test_sample_script_and_storyboard_pass_clean() -> None:
    script = sample()
    assert passed(check_script(script))
    sb = normalize_storyboard(compile_storyboard(script))
    assert passed(check_storyboard(sb, script))
    assert len(sb["segments"]) >= 6
    assert all(2 <= len(seg["shots"]) <= 4 for seg in sb["segments"])


def test_dialogue_is_copied_verbatim_and_ordered() -> None:
    script = sample()
    sb = normalize_storyboard(compile_storyboard(script))
    want = [(d["speaker"], d["text"]) for sc in script["scenes"] for b in sc["beats"] for d in b["dialogue"]]
    got = [(d["speaker"], d["text"]) for seg in sb["segments"] for s in seg["shots"] for d in s["dialogue"]]
    assert got == want


def test_big_action_and_three_same_sizes_are_flagged() -> None:
    script = sample()
    sb = normalize_storyboard(compile_storyboard(script))
    sb["segments"][0]["shots"][2]["size"] = sb["segments"][1]["shots"][0]["size"] = sb["segments"][0]["shots"][1]["size"]
    findings = summarise(check_storyboard(sb, script))
    assert any(f["rule"] == "B-SAME-SIZE" for f in findings["findings"])


def test_unfilmable_action_is_flagged() -> None:
    script = sample()
    script["scenes"][0]["beats"][0]["action"] = ["△林晚心里想，这人又来了。"]
    findings = check_script(script)
    assert any(f["rule"] == "S-UNFILMABLE" for f in findings)


def test_speaker_change_inside_one_shot_is_blocked() -> None:
    script = sample()
    sb = normalize_storyboard(compile_storyboard(script))
    first = next(s for s in sb["segments"][1]["shots"] if s["dialogue"])
    first["dialogue"].append({"speaker": "zhou", "text": "抢一句。", "kind": "said"})
    assert not passed(check_storyboard(sb, script))


def test_missing_reference_and_identity_field_are_blocked() -> None:
    from hevi.ai_drama.assets import build_assets

    script = sample()
    assets = build_assets(script)
    assets["images"][0]["prompt"] = "角色，正面，侧面，背面"  # missing 表情/白底/鞋
    findings = summarise(check_assets(assets, script, normalize_storyboard(compile_storyboard(script))))
    assert not findings["passed"]
    assert any(f["rule"].startswith("A-IDENTITY") for f in findings["findings"])


def test_edit_requires_verbatim_subtitles_and_inner_colour() -> None:
    from hevi.ai_drama.assets import assign_shot_refs, build_assets
    from hevi.ai_drama.edit import build_edit
    from hevi.ai_drama.voice import build_voice_plan

    script = sample()
    sb = normalize_storyboard(compile_storyboard(script))
    assets = build_assets(script)
    assign_shot_refs(sb, assets)
    plan = build_voice_plan(script, Path("/tmp/ai_drama_rules_voice"))
    edit = build_edit(sb, script, plan, Path("/tmp/ai_drama_rules_edit"))
    assert passed(check_edit(edit, script, sb))
    edit["subtitles"][0]["text"] = "改过的台词"
    assert not passed(check_edit(edit, script, sb))


def test_game_pov_spine_and_pov_body_are_required() -> None:
    script = game()
    assert passed(check_script(script))
    sb = normalize_storyboard(compile_storyboard(script))
    assert passed(check_storyboard(sb, script))
    pov = next(s for s in sb["segments"][0]["shots"] if s["mode"] == "pov")
    pov["pov"].pop("body")
    pov["pov"]["where"] = "教室"
    pov["pov"]["looking"] = "前方"
    pov["pov"]["next_move"] = "不动"
    findings = check_game_pov(script, sb, {"ui_overlays": [{"text": "x", "png": "x", "start_s": 1}]})
    assert any(f["rule"] == "G-POV-BODY" for f in findings)


def test_theme_scaffold_still_runs_all_checks() -> None:
    script = normalize_script(draft_script_from_theme("雨夜有人敲门", style="live_action"))
    assert isinstance(check_script(script), list)
    sb = normalize_storyboard(compile_storyboard(script))
    assert isinstance(check_storyboard(sb, script), list)
