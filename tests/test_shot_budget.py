"""DRAMAPLAN bug1:镜头预算随 target_duration_s 变化且落在预算内。

上游 `oskill.script_writer`/`storyboard_planner` 不受时长约束(见 STATUS 247-260),
hevi 侧用 `shot_budget` 纯算法兜住。本测试不调网络、不加载模型。
"""

from __future__ import annotations

import pytest
from oskill._schemas import ShotPlan

from hevi.layer4_legacy.script2video.oskill_impl.shot_budget import (
    expected_chapters_for_duration,
    fit_shot_plans_to_budget,
    merge_shot_plans,
    shot_budget_for_duration,
    shot_budget_per_chapter,
)


def test_budget_monotonic_with_duration():
    budgets = [shot_budget_for_duration(d) for d in (30, 60, 120)]
    assert budgets == [6, 12, 24]
    assert budgets[0] < budgets[1] < budgets[2]


def test_budget_respects_bounds():
    assert shot_budget_for_duration(0) == 1
    assert shot_budget_for_duration(1) == 1
    assert shot_budget_for_duration(10_000) == 120  # max cap
    assert shot_budget_for_duration(30, seconds_per_shot=10) == 3


def test_expected_chapters_mirrors_upstream_tiers():
    assert expected_chapters_for_duration(30) == 2
    assert expected_chapters_for_duration(600) == 4
    assert expected_chapters_for_duration(1800) == 8
    assert expected_chapters_for_duration(3600) == 16


def test_per_chapter_budget_divides_total():
    # 30s → 总预算 6,2 章 → 每章 3;60s → 12/2=6;120s → 24/2=12
    assert shot_budget_per_chapter(30) == 3
    assert shot_budget_per_chapter(60) == 6
    assert shot_budget_per_chapter(120) == 12
    # 均摊后总上限不超过总预算(向上取整最多超 1 镜)
    for d in (30, 60, 120):
        chapters = expected_chapters_for_duration(d)
        assert shot_budget_per_chapter(d) * chapters <= shot_budget_for_duration(d) + chapters


def _plan(i: int) -> ShotPlan:
    return ShotPlan(
        shot_id=f"shot_{i}",
        image_prompt=f"prompt{i}",
        tts_text=f"line{i}",
        duration_s=5.0,
    )


def test_fit_merges_to_budget_and_preserves_content():
    plans = [_plan(i) for i in range(10)]
    fitted = fit_shot_plans_to_budget(plans, 4)
    assert len(fitted) == 4
    # 内容不丢:所有 prompt/台词 token 都还在合并后的镜头里
    joined = " ".join(p.image_prompt for p in fitted)
    for i in range(10):
        assert f"prompt{i}" in joined
    assert sum(p.duration_s for p in fitted) == pytest.approx(50.0)
    # 首镜 id 保留(合并进组内首镜)
    assert fitted[0].shot_id == "shot_0"


def test_fit_noop_when_within_budget():
    plans = [_plan(i) for i in range(3)]
    assert fit_shot_plans_to_budget(plans, 5) == plans
    assert fit_shot_plans_to_budget(plans, 3) == plans


def test_fit_empty_and_zero_budget():
    assert fit_shot_plans_to_budget([], 5) == []
    assert fit_shot_plans_to_budget([_plan(0)], 0) == []


def test_merge_single_is_identity():
    p = _plan(0)
    assert merge_shot_plans([p]) is p


def test_shot_count_monotonic_across_durations_after_fit():
    """模拟 orchestrator 的每章裁剪:同一份 20 镜 storyboard,时长越大保留越多镜。"""
    plans = [_plan(i) for i in range(20)]
    counts = [len(fit_shot_plans_to_budget(plans, shot_budget_per_chapter(d))) for d in (30, 60, 120)]
    assert counts == [3, 6, 12]
    assert counts == sorted(counts)
    for d, count in zip((30, 60, 120), counts, strict=True):
        assert count <= shot_budget_per_chapter(d)
