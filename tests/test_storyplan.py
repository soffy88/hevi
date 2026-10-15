"""Hevi StoryPlan 单元测试 (pytest)。"""

from __future__ import annotations

from pathlib import Path
import pytest

from hevi.storyplan.autofill import autofill_story_plan
from hevi.storyplan.check import run_story_check
from hevi.storyplan.take_select import select_best_take, TakeCandidate
from hevi.storyplan.export import export_storyboard_markdown, export_storyboard_html
from hevi.storyplan.model import story_plan_schema


def test_story_plan_autofill_raindrop():
    plan = autofill_story_plan("小水滴去哪儿了", aspect="16:9")
    assert plan.title == "小水滴去哪儿了"
    assert plan.aspect == "16:9"
    assert len(plan.narrative.beats) >= 3
    assert len(plan.shots.sequences[0].scenes[0].shots) >= 3


def test_story_plan_autofill_bear():
    plan = autofill_story_plan("小熊为什么洗手", aspect="9:16")
    assert plan.title == "小熊为什么洗手"
    assert plan.aspect == "9:16"
    assert plan.narrative.hook.hook_type == "question"


def test_story_check_pass_on_planned_plan():
    plan = autofill_story_plan("小水滴去哪儿了", aspect="16:9")
    report = run_story_check(plan)
    assert report.passed is True
    assert all(c.status == "PASS" for c in report.checks)


def test_story_check_fail_on_bad_plan():
    plan = autofill_story_plan("小水滴去哪儿了", aspect="16:9")
    # 注入违规项以测出门禁拒绝
    plan.narration_text = "这里有暴力血腥武器杀戮。"
    report = run_story_check(plan)
    assert report.passed is False
    c7 = next(c for c in report.checks if c.check_id == "C7_CONTENT_SAFETY")
    assert c7.status == "FAIL"


def test_take_select_best():
    cands = [
        TakeCandidate(take_id="t1", video_path="clip1.mp4", duration_sec=4.8),
        TakeCandidate(take_id="t2", video_path="clip2.mp4", duration_sec=9.5),
    ]
    best, all_res = select_best_take(cands, "水滴落入水中", target_duration_sec=5.0)
    assert best.take_id == "t1"
    assert best.score > 90.0
    assert len(all_res) == 2


def test_storyboard_exports():
    plan = autofill_story_plan("小水滴去哪儿了", aspect="16:9")
    report = run_story_check(plan)
    md = export_storyboard_markdown(plan)
    assert "# 分镜表与镜头清单" in md
    html = export_storyboard_html(plan, report)
    assert "<html" in html
    assert "结构自检门" in html


def test_json_schema_export():
    schema = story_plan_schema()
    assert isinstance(schema, dict)
    assert "properties" in schema
