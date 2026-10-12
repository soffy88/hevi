"""DRAMAPLAN bug1:镜头预算随 target_duration_s 变化且落在预算内。

上游 `oskill.script_writer`/`storyboard_planner` 不受时长约束(见 STATUS 247-260),
hevi 侧用 `shot_budget` 纯算法兜住。本测试不调网络、不加载模型。
"""

from __future__ import annotations

import pytest
from oskill._schemas import ShotPlan

from hevi.layer4_legacy.script2video.oskill_impl.shot_budget import (
    adjust_shot_plans_to_budget,
    expected_chapters_for_duration,
    expand_shot_plans_to_budget,
    fit_shot_plans_to_budget,
    merge_shot_plans,
    shot_budget_for_duration,
    shot_budget_per_chapter,
    split_single_shot_plan,
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


def test_expand_shot_plans_splits_under_budget():
    # 5 镜输入，预算 6 镜与 12 镜（测试补足与扩展）
    plans = [_plan(i) for i in range(5)]
    expanded_6 = expand_shot_plans_to_budget(plans, 6)
    assert len(expanded_6) == 6
    assert sum(p.duration_s for p in expanded_6) == pytest.approx(25.0)

    expanded_12 = expand_shot_plans_to_budget(plans, 12)
    assert len(expanded_12) == 12
    assert sum(p.duration_s for p in expanded_12) == pytest.approx(25.0)


def test_adjust_shot_plans_to_budget():
    plans = [_plan(i) for i in range(5)]
    # 超预算 -> 压缩到 3 镜
    assert len(adjust_shot_plans_to_budget(plans, 3)) == 3
    # 恰好等于预算 -> 原样 5 镜
    assert len(adjust_shot_plans_to_budget(plans, 5)) == 5
    # 低于预算 -> 补足扩展到 12 镜
    assert len(adjust_shot_plans_to_budget(plans, 12)) == 12


def test_shot_count_monotonic_across_durations_after_fit():
    """模拟 orchestrator 的每章裁剪:同一份 20 镜 storyboard,时长越大保留越多镜。"""
    plans = [_plan(i) for i in range(20)]
    counts = [len(fit_shot_plans_to_budget(plans, shot_budget_per_chapter(d))) for d in (30, 60, 120)]
    assert counts == [3, 6, 12]
    assert counts == sorted(counts)
    for d, count in zip((30, 60, 120), counts, strict=True):
        assert count <= shot_budget_per_chapter(d)


@pytest.mark.asyncio
async def test_orchestrator_counting_shot_gen_chain_with_fixed_5_shots(
    monkeypatch, tmp_path
):
    """P1.2 / R3：monkeypatch `default_longvideo_shot_generator` 与
    `agentic_longvideo_pipeline`，调用**真正的** `orchestrate_longvideo`
    （真实 script_fn→storyboard_fn→shot_gen_fn 链，fake pipeline 内调用
    providers["shot_gen_fn"]）。断言 target_duration_s=30/60/120 时最终
    镜头数严格单调递增且每个都落在 shot_budget_for_duration 预算内。
    """
    from pathlib import Path
    from unittest.mock import patch

    from omodul.longvideo_produce import LongVideoResult

    from hevi.pipeline import longvideo_orchestrator as lvo
    from hevi.pipeline.longvideo_orchestrator import orchestrate_longvideo
    from hevi.providers.registry import register_all_providers

    register_all_providers()

    per_duration_calls: dict[float, list[int]] = {}

    async def fake_shot_gen(*, storyboard, llm):
        # 固定上游 storyboard 每章 5 镜（与审核方实测同口径）
        return [_plan(i) for i in range(5)]

    async def fake_pipeline(*, config, _providers):
        target = float(getattr(config, "target_duration_s", 0.0) or 0.0)
        # 真实链：orchestrator 会先注入真实 storyboard_fn（依赖上游 LLM），本测只需
        # 验证 shot_gen_fn 上的时长预算适配——用 pass-through 占位 storyboard_fn 避开 LLM。
        async def _noop_storyboard_fn(**kw):
            return kw.get("script")

        _providers["storyboard_fn"] = _noop_storyboard_fn
        plans: list = []
        for _chapter in range(expected_chapters_for_duration(target)):
            storyboard = await _providers["storyboard_fn"](script=None, llm=None)
            chapter_plans = await _providers["shot_gen_fn"](storyboard=storyboard, llm=None)
            plans.extend(chapter_plans)
            per_duration_calls.setdefault(target, []).append(len(chapter_plans))
        config.output_dir.mkdir(parents=True, exist_ok=True)
        vp = Path(config.output_dir) / "final.mp4"
        vp.write_bytes(b"\x00" * 2048)
        return LongVideoResult(
            video_path=vp,
            duration_s=10.0,
            chapters=1,
            shots_generated=len(plans),
            provider_used={"video": "ltx2_cloud", "audio": "edge_tts"},
        )

    total_shots_per_duration: list[int] = []
    budgets = {}
    for d in (30, 60, 120):
        budgets[float(d)] = shot_budget_for_duration(float(d))

    with patch.object(lvo, "default_longvideo_shot_generator", fake_shot_gen), patch.object(
        lvo, "agentic_longvideo_pipeline", fake_pipeline
    ):
        for d in (30, 60, 120):
            target = float(d)
            per_duration_calls.setdefault(target, [])
            await orchestrate_longvideo(
                topic="预算链测试",
                duration_archetype="1-5min",
                video_provider="ltx2_cloud",
                audio_provider="edge_tts",
                output_dir=tmp_path / f"task_{d}",
                target_duration_s=target,
            )
            # fake_pipeline 每 target 只调一次：其内每章都过 shot_gen_fn
            chapter_calls = per_duration_calls[target]
            # 每章都被 shot_gen_fn 适配到 <= 每章预算（上游固定 5 镜被压回预算）
            chapter_budget = shot_budget_per_chapter(target)
            assert all(c == chapter_budget for c in chapter_calls), (
                f"target={target}s 章镜头数 {chapter_calls} != 预算 {chapter_budget}"
            )
            total_shots_per_duration.append(sum(chapter_calls))

    # 严格单调：30s(6) < 60s(12) < 120s(24)，且落在总预算内（±章数取整误差）
    assert total_shots_per_duration == [6, 12, 24]
    assert total_shots_per_duration[0] < total_shots_per_duration[1] < total_shots_per_duration[2]
    for d, total in zip((30, 60, 120), total_shots_per_duration, strict=True):
        assert total <= budgets[float(d)] + expected_chapters_for_duration(float(d))


def test_split_single_shot_preserves_all_content():
    from oskill._schemas import ShotPlan

    p = ShotPlan(shot_id='sh', image_prompt='画面', tts_text='第0句，前半，后半，尾巴。', duration_s=10.0)
    sub2 = split_single_shot_plan(p, 2)
    assert len(sub2) == 2
    joined = ''.join(s.tts_text for s in sub2)
    assert joined == '第0句，前半，后半，尾巴。', f'R3 丢分句: {joined}'

    sub3 = split_single_shot_plan(p, 3)
    joined3 = ''.join(s.tts_text for s in sub3)
    assert joined3 == '第0句，前半，后半，尾巴。', f'R3 丢分句: {joined3}'

    # 子镜画面描述应有区分（景别递进）
    prompts = [s.image_prompt for s in sub3]
    assert len(set(prompts)) == 3, '子镜画面应不同'


def test_split_single_shot_no_empty_tts_when_content_exists():
    """R3: 分句数不足拆分数时按字符细分，原文充足时每个子镜都不应为空 tts。

    注：字符数 < 拆分数时（如 4 字拆 6 镜）数学上无法做到既逐字保留又全非空，
    此时保证逐字保留优先（本测试用充足文本覆盖“不足分句但字符充足”的真实场景）。
    """
    from oskill._schemas import ShotPlan

    # 4 个分句 < 6 镜，但 16 个字符足够均分（FIX 简报中的原文示例）
    p = ShotPlan(
        shot_id='sh', image_prompt='画面',
        tts_text='第0句，前半，后半，尾巴。', duration_s=10.0,
    )
    sub6 = split_single_shot_plan(p, 6)
    assert len(sub6) == 6
    for s in sub6:
        assert s.tts_text, f'子镜 {s.shot_id} 不应为空 tts'
    assert ''.join(s.tts_text for s in sub6) == '第0句，前半，后半，尾巴。'

    # 极端退化：字符数 < 拆分数 → 逐字保留优先（非空镜数 = 字符数）
    p2 = ShotPlan(
        shot_id='sh2', image_prompt='画面', tts_text='一句话。', duration_s=10.0,
    )
    sub6b = split_single_shot_plan(p2, 6)
    assert len(sub6b) == 6
    assert ''.join(s.tts_text for s in sub6b) == '一句话。'

