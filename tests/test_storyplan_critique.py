"""Unit tests for storyplan.critique capability (剧本自审轮：挑剔观众 + 动画导演)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from hevi.capabilities import get, resolve, names
from hevi.capabilities.errors import CapabilityError
from hevi.storyplan.autofill import autofill_story_plan
from hevi.storyplan.check import run_story_check
from hevi.storyplan.critique import (
    CritiqueIssue,
    CritiqueReport,
    critique_story_plan,
    revise_story_plan,
    render_storyplan_critique,
)
from hevi.storyplan.model import StoryPlan


def test_storyplan_critique_capability_registered():
    assert "storyplan.critique" in names()
    cap = get("storyplan.critique")
    assert cap.name == "storyplan.critique"
    assert cap.line == "storyplan"
    assert "16:9" in cap.aspects


def test_critique_detects_audience_and_director_issues():
    plan = autofill_story_plan("小松鼠找坚果", aspect="16:9")
    # 模拟未打磨的平淡开场与单一景别
    plan.narrative.hook.text = "小松鼠在树下走。"
    for seq in plan.shots.sequences:
        for sc in seq.scenes:
            for sh in sc.shots:
                sh.shot_type = "character"
                sh.action = "走动"
                sh.end_state = "停下"

    report = critique_story_plan(plan)
    assert isinstance(report, CritiqueReport)
    assert len(report.issues) > 0
    categories = {i.category for i in report.issues}
    personas = {i.persona for i in report.issues}

    assert "挑剔观众" in personas
    assert "动画导演" in personas
    assert "HOOK_ENGAGEMENT" in categories or "SHOT_SCALE_VARIETY" in categories
    assert report.overall_score < 90.0


def test_revise_story_plan_resolves_issues_and_diversifies_shots():
    plan = autofill_story_plan("小松鼠找坚果", aspect="16:9")
    plan.narrative.hook.text = "小松鼠在树下走。"
    for seq in plan.shots.sequences:
        for sc in seq.scenes:
            for sh in sc.shots:
                sh.shot_type = "character"
                sh.action = "走动"
                sh.end_state = "停下"

    report = critique_story_plan(plan)
    revised = revise_story_plan(plan, report)

    # 验证修订后效果
    assert revised.title == plan.title
    all_shots = [sh for seq in revised.shots.sequences for sc in seq.scenes for sh in sc.shots]
    shot_types = {sh.shot_type for sh in all_shots}
    assert len(shot_types) >= 2  # 包含远景/特写/中景等尺度交替
    assert "establishing" in shot_types or "insert" in shot_types

    # 验证开场问句疑问感增强
    assert "？" in revised.narrative.hook.text or "?" in revised.narrative.hook.text

    # 验证自检门 100% 通过
    check_rep = run_story_check(revised)
    assert check_rep.passed is True


def test_storyplan_critique_render_creates_artifacts(tmp_path: Path):
    cap = resolve("storyplan.critique")
    out_dir = tmp_path / "critique_out"

    result = cap.render(
        {"topic": "神奇魔法画笔", "auto_revise": True},
        out_dir,
        duration=0.0,
        aspect="16:9",
        seed=123,
    )

    assert result is not None
    assert (out_dir / "critique_report.json").is_file()
    assert (out_dir / "revised_story_plan.json").is_file()
    assert (out_dir / "critique_summary.txt").is_file()
    assert (out_dir / "critique_preview.png").is_file()
    assert result.png == out_dir / "critique_preview.png"
    assert result.duration_s > 0
    assert result.sha256 != ""
    assert "audience_score" in result.qa
    assert "director_score" in result.qa
    assert result.qa["issues_count"] >= 0


def test_storyplan_critique_custom_plan_payload(tmp_path: Path):
    custom_plan = autofill_story_plan("森林微光花", aspect="16:9")
    cap = get("storyplan.critique")
    out_dir = tmp_path / "custom_critique"

    res = cap.render(
        {"plan": custom_plan.model_dump(), "auto_revise": True},
        out_dir,
        duration=0.0,
        aspect="16:9",
        seed=42,
    )
    assert res.qa["revised"] is True
    data = json.loads((out_dir / "revised_story_plan.json").read_text(encoding="utf-8"))
    assert data["title"] == "森林微光花"


def test_storyplan_critique_invalid_params():
    cap = get("storyplan.critique")
    with pytest.raises(CapabilityError):
        cap.validate_params({"unknown_field": "error_payload"})
