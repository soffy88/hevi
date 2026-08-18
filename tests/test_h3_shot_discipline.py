"""烁皓 1–6: H3 切长门 / 运镜卡 / 门日志 / 写作规则(不调模型)。"""

from __future__ import annotations

from pathlib import Path

from hevi.director.gate_log import (
    append_gate_log,
    gate_log_entries,
    summarize_gate_log,
)
from hevi.director.h3_shot_gates import lint_h3_cut_budget, lint_h3_vocab
from hevi.director.pipeline_schemas import ShotList, ShotListItem
from hevi.director.scene_stage_lint import LintFinding
from hevi.director.screenplay import _REVIEW_PROMPT, _SCREENPLAY_PROMPT
from hevi.director.shot_list import _SHOT_LIST_PROMPT
from hevi.prompt.h3_recipes import H3_CAMERA_MOVES, RecipeCard


def _shot(**kw) -> ShotListItem:
    data = {"shot_id": "SH1", "scene_no": 1, "duration_s": 4.0}
    data.update(kw)
    return ShotListItem(**data)


def test_h1_flags_cut_outside_2_to_5() -> None:
    sl = ShotList(shots=[_shot(duration_s=8.0), _shot(shot_id="SH2", duration_s=3.0)])
    rules = {f.rule for f in lint_h3_cut_budget(sl)}
    assert rules == {"H1"}
    assert lint_h3_cut_budget(sl)[0].shot_ids == ["SH1"]


def test_h1_accepts_boundary_2_and_5() -> None:
    sl = ShotList(
        shots=[
            _shot(duration_s=2.0),
            _shot(shot_id="SH2", duration_s=5.0),
        ]
    )
    assert lint_h3_cut_budget(sl) == []


def test_h2_flags_single_cut_over_15() -> None:
    sl = ShotList(shots=[_shot(duration_s=16.0)])
    rules = {f.rule for f in lint_h3_cut_budget(sl)}
    assert "H1" in rules
    assert "H2" in rules


def test_camera_official_and_alias_pass() -> None:
    sl = ShotList(
        shots=[
            _shot(camera="Follow"),
            _shot(shot_id="SH2", camera="跟拍"),
            _shot(shot_id="SH3", camera="平视"),
            _shot(shot_id="SH4", camera=""),
        ]
    )
    assert lint_h3_vocab(sl) == []


def test_camera_unknown_move_flagged() -> None:
    sl = ShotList(shots=[_shot(camera="随意飘移")])
    findings = lint_h3_vocab(sl)
    assert findings[0].rule == "C1"


def test_recipe_lint_skipped_without_card_library() -> None:
    sl = ShotList(shots=[_shot(recipe="ots-shot-reverse")])
    assert lint_h3_vocab(sl, cards=None) == []


def test_recipe_must_phrases_and_unknown_id() -> None:
    cards = {
        "hand-insert": RecipeCard(
            recipe_id="hand-insert",
            must_phrases=("foreground hand",),
        )
    }
    missing = lint_h3_vocab(
        ShotList(shots=[_shot(recipe="hand-insert", visual_prompt="一只手伸进画面")]),
        cards=cards,
    )
    assert missing[0].rule == "R2"
    unknown = lint_h3_vocab(ShotList(shots=[_shot(recipe="nope")]), cards=cards)
    assert unknown[0].rule == "R1"
    ok = lint_h3_vocab(
        ShotList(
            shots=[_shot(recipe="hand-insert", visual_prompt="a foreground hand on the table")]
        ),
        cards=cards,
    )
    assert ok == []


def test_h3_camera_domain_has_20_moves() -> None:
    assert len(H3_CAMERA_MOVES) == 20
    assert len(set(H3_CAMERA_MOVES)) == 20


def test_gate_log_entries_and_stats_are_pure() -> None:
    findings = [
        LintFinding(rule="H1", scene_no=1, shot_ids=["SH1"], message="太长"),
        LintFinding(rule="H1", scene_no=1, shot_ids=["SH2"], message="还长"),
        LintFinding(rule="L1", scene_no=1, shot_ids=["SH3"], message="越轴"),
    ]
    rows = gate_log_entries(source="director", findings=findings)
    assert rows[0]["kind"] == "run"
    assert rows[0]["failed"] == 3
    stats = summarize_gate_log(rows)
    assert stats["failures"] == 3
    assert stats["loudest"][0]["rule"] == "H1"
    assert "H2" in stats["silent"]
    assert "太长" in stats["details"]


def test_append_gate_log_writes_and_survives_bad_path(tmp_path: Path) -> None:
    dest = tmp_path / "sub" / ".gates.jsonl"
    append_gate_log(
        dest,
        gate_log_entries(
            source="t",
            findings=[LintFinding(rule="C1", scene_no=0, shot_ids=["A"], message="x")],
        ),
    )
    text = dest.read_text(encoding="utf-8")
    assert "C1" in text
    append_gate_log(tmp_path / "nope" / ("x" * 8), [])  # empty → no IO


def test_screenplay_and_shot_prompts_carry_shuohao_rules() -> None:
    assert "常见动作" in _SCREENPLAY_PROMPT
    assert "冷开场" in _SCREENPLAY_PROMPT
    assert "常见动作" in _REVIEW_PROMPT
    assert "冷开场" in _REVIEW_PROMPT
    assert "2–5 秒" in _SHOT_LIST_PROMPT
    assert "运动主体" in _SHOT_LIST_PROMPT
    assert "Static" in _SHOT_LIST_PROMPT
