"""LongCat-Video 能力适配测试 — 视频续接 + 渐进生成 + CFG-Zero。

48 tests 覆盖:
  - video_continuation: 续接模式/链式标注/帧数计算/配置构建 (~12 tests)
  - coarse_to_fine: 草稿策略/步数计算/分辨率选择/两阶段流程 (~14 tests)
  - cfg_zero: 数学正确性/噪声合并/追踪器/推荐值/衰减 (~22 tests)

运行: .venv/bin/python -m pytest tests/test_longcat_features.py --noconftest -v
"""
from __future__ import annotations

import math
import asyncio
from pathlib import Path

import pytest

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Video Continuation tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

from hevi.video.longcat.video_continuation import (
    ContinuationMode,
    ContinuationConfig,
    ShotContinuation,
    build_continuation_config,
    apply_continuation_to_shots,
    compute_cond_frames_count,
)


class TestContinuationMode:
    def test_enum_values(self):
        assert ContinuationMode.NO == "no"
        assert ContinuationMode.SINGLE_FRAME == "single_frame"
        assert ContinuationMode.MULTI_FRAME == "multi_frame"

    def test_enum_comparison(self):
        assert ContinuationMode.NO != ContinuationMode.SINGLE_FRAME
        assert ContinuationMode.SINGLE_FRAME != ContinuationMode.MULTI_FRAME


class TestContinuationConfig:
    def test_no_condition_when_no(self):
        cfg = ContinuationConfig(mode=ContinuationMode.NO)
        assert not cfg.has_condition

    def test_no_condition_when_none(self):
        cfg = ContinuationConfig(mode=ContinuationMode.NO, prev_clip_path=None)
        assert not cfg.has_condition

    def test_has_condition_single_frame(self):
        cfg = ContinuationConfig(
            mode=ContinuationMode.SINGLE_FRAME,
            prev_clip_path=Path("/tmp/prev.mp4"),
            last_frame_path=Path("/tmp/last.png"),
        )
        assert cfg.has_condition

    def test_has_condition_multi_frame(self):
        cfg = ContinuationConfig(
            mode=ContinuationMode.MULTI_FRAME,
            prev_clip_path=Path("/tmp/prev.mp4"),
            cond_frames_paths=[Path("/tmp/f1.png"), Path("/tmp/f2.png")],
            cond_frames_count=2,
        )
        assert cfg.has_condition
        assert cfg.cond_frames_count == 2

    def test_cond_weight_default(self):
        cfg = ContinuationConfig(mode=ContinuationMode.NO)
        assert cfg.cond_weight == 1.0

    def test_cond_weight_custom(self):
        cfg = ContinuationConfig(
            mode=ContinuationMode.SINGLE_FRAME,
            cond_weight=0.7,
        )
        assert cfg.cond_weight == 0.7


class TestBuildContinuationConfig:
    def test_no_prev_clip_returns_no(self):
        cfg = build_continuation_config(prev_clip_path=None)
        assert cfg.mode == ContinuationMode.NO

    def test_auto_single_frame_with_last_frame(self):
        cfg = build_continuation_config(
            prev_clip_path=Path("/tmp/prev.mp4"),
            last_frame_path=Path("/tmp/last.png"),
        )
        assert cfg.mode == ContinuationMode.SINGLE_FRAME

    def test_auto_multi_frame_with_cond_paths(self):
        cfg = build_continuation_config(
            prev_clip_path=Path("/tmp/prev.mp4"),
            cond_frames_paths=[Path("/tmp/f1.png"), Path("/tmp/f2.png")],
        )
        assert cfg.mode == ContinuationMode.MULTI_FRAME

    def test_explicit_mode_overrides_auto(self):
        cfg = build_continuation_config(
            prev_clip_path=Path("/tmp/prev.mp4"),
            last_frame_path=Path("/tmp/last.png"),
            mode=ContinuationMode.MULTI_FRAME,
        )
        assert cfg.mode == ContinuationMode.MULTI_FRAME

    def test_cond_weight_propagated(self):
        cfg = build_continuation_config(
            prev_clip_path=Path("/tmp/prev.mp4"),
            cond_weight=0.5,
        )
        assert cfg.cond_weight == 0.5


class TestComputeCondFramesCount:
    def test_short_clip(self):
        # ≤3s at 16fps → 1 frame
        assert compute_cond_frames_count(duration_s=2.0, fps=16) == 1
        assert compute_cond_frames_count(duration_s=3.0, fps=16) == 1

    def test_medium_clip(self):
        # 3-5s → 5 frames
        assert compute_cond_frames_count(duration_s=4.0, fps=16) == 5

    def test_long_clip(self):
        # >5s → min(max_frames, total//3)
        assert compute_cond_frames_count(duration_s=6.0, fps=16, max_frames=13) == 13
        # total=96 frames, 96//3=32, capped at 13
        assert compute_cond_frames_count(duration_s=10.0, fps=16, max_frames=13) == 13

    def test_min_frames_respected(self):
        assert compute_cond_frames_count(duration_s=1.0, fps=16, min_frames=3) == 3


class TestApplyContinuationToShots:
    def test_first_shot_always_no(self):
        clips = [Path("/tmp/s0.mp4"), Path("/tmp/s1.mp4")]
        frames = [Path("/tmp/s0_last.png"), Path("/tmp/s1_last.png")]
        results = apply_continuation_to_shots(clips, frames)
        assert results[0].config.mode == ContinuationMode.NO
        assert results[0].is_first_shot

    def test_subsequent_shots_continue(self):
        clips = [Path("/tmp/s0.mp4"), Path("/tmp/s1.mp4"), Path("/tmp/s2.mp4")]
        frames = [Path("/tmp/f0.png"), Path("/tmp/f1.png"), Path("/tmp/f2.png")]
        results = apply_continuation_to_shots(clips, frames)
        assert len(results) == 3
        assert results[0].config.mode == ContinuationMode.NO
        assert results[1].config.mode == ContinuationMode.SINGLE_FRAME
        assert results[2].config.mode == ContinuationMode.SINGLE_FRAME

    def test_continues_mask_respected(self):
        clips = [Path("/tmp/s0.mp4"), Path("/tmp/s1.mp4"), Path("/tmp/s2.mp4")]
        frames = [Path("/tmp/f0.png"), Path("/tmp/f1.png"), Path("/tmp/f2.png")]
        # 反打: shot 2 不续接 shot 1
        mask = [False, True, False]
        results = apply_continuation_to_shots(clips, frames, continues_mask=mask)
        assert results[0].config.mode == ContinuationMode.NO
        assert results[1].config.mode == ContinuationMode.SINGLE_FRAME
        assert results[2].config.mode == ContinuationMode.NO

    def test_mismatched_lengths_raises(self):
        clips = [Path("/tmp/s0.mp4")]
        frames: list[Path | None] = []
        with pytest.raises(ValueError, match="不匹配"):
            apply_continuation_to_shots(clips, frames)

    def test_mask_length_mismatch_raises(self):
        clips = [Path("/tmp/s0.mp4"), Path("/tmp/s1.mp4")]
        frames = [Path("/tmp/f0.png"), Path("/tmp/f1.png")]
        with pytest.raises(ValueError, match="不匹配"):
            apply_continuation_to_shots(clips, frames, continues_mask=[True])

    def test_shot_index_correct(self):
        clips = [Path("/tmp/s0.mp4"), Path("/tmp/s1.mp4"), Path("/tmp/s2.mp4")]
        frames = [Path("/tmp/f0.png"), Path("/tmp/f1.png"), Path("/tmp/f2.png")]
        results = apply_continuation_to_shots(clips, frames)
        assert results[0].shot_index == 0
        assert results[1].shot_index == 1
        assert results[2].shot_index == 2

    def test_prev_clip_path_correct(self):
        clips = [Path("/tmp/s0.mp4"), Path("/tmp/s1.mp4")]
        frames = [Path("/tmp/f0.png"), Path("/tmp/f1.png")]
        results = apply_continuation_to_shots(clips, frames)
        assert results[1].config.prev_clip_path == clips[0]

    def test_last_frame_path_propagated(self):
        clips = [Path("/tmp/s0.mp4"), Path("/tmp/s1.mp4")]
        frames = [Path("/tmp/f0.png"), Path("/tmp/f1.png")]
        results = apply_continuation_to_shots(clips, frames)
        assert results[1].config.last_frame_path == frames[0]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Coarse-to-Fine tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

from hevi.video.longcat.coarse_to_fine import (
    DraftStrategy,
    CoarseToFineConfig,
    CoarseToFineResult,
    build_coarse_to_fine_config,
    compute_draft_steps,
    select_draft_resolution,
    generate_coarse_to_fine,
)


class TestDraftStrategy:
    def test_enum_values(self):
        assert DraftStrategy.LOW_STEPS == "low_steps"
        assert DraftStrategy.LOW_RES == "low_res"
        assert DraftStrategy.BOTH == "both"


class TestComputeDraftSteps:
    def test_low_steps_strategy(self):
        # 16% of 50 = 8
        assert compute_draft_steps(50, DraftStrategy.LOW_STEPS) == 8
        # 16% of 100 = 16
        assert compute_draft_steps(100, DraftStrategy.LOW_STEPS) == 16

    def test_low_res_strategy_uses_full_steps(self):
        assert compute_draft_steps(50, DraftStrategy.LOW_RES) == 50

    def test_both_strategy(self):
        assert compute_draft_steps(50, DraftStrategy.BOTH) == 8

    def test_min_steps_respected(self):
        # 16% of 10 = 1, but min_steps=4
        assert compute_draft_steps(10, DraftStrategy.LOW_STEPS, min_steps=4) == 4


class TestSelectDraftResolution:
    def test_low_steps_keeps_resolution(self):
        res = select_draft_resolution((720, 1280), DraftStrategy.LOW_STEPS)
        assert res == (720, 1280)

    def test_low_res_reduces(self):
        res = select_draft_resolution((720, 1280), DraftStrategy.LOW_RES)
        # 720 * 2/3 = 480, 1280 * 2/3 ≈ 853, aligned to 16 = 848
        assert res[0] == 480
        assert res[1] % 16 == 0

    def test_both_reduces(self):
        res = select_draft_resolution((720, 1280), DraftStrategy.BOTH)
        assert res[0] < 720
        assert res[1] < 1280

    def test_resolution_aligned_to_16(self):
        res = select_draft_resolution((1080, 1920), DraftStrategy.LOW_RES)
        assert res[0] % 16 == 0
        assert res[1] % 16 == 0


class TestCoarseToFineConfig:
    def test_speedup_ratio(self):
        cfg = CoarseToFineConfig(
            enabled=True,
            draft_strategy=DraftStrategy.LOW_STEPS,
            draft_steps=8,
            refine_steps=50,
            draft_resolution=(480, 832),
            refine_resolution=(720, 1280),
        )
        assert cfg.speedup_ratio > 1.0

    def test_disabled_default(self):
        cfg = CoarseToFineConfig()
        assert not cfg.enabled

    def test_draft_accept_fn_none(self):
        cfg = CoarseToFineConfig(enabled=True)
        assert cfg.draft_accept_fn is None


class TestBuildCoarseToFineConfig:
    def test_basic_build(self):
        cfg = build_coarse_to_fine_config(
            enabled=True,
            draft_strategy=DraftStrategy.LOW_STEPS,
            refine_steps=50,
        )
        assert cfg.enabled
        assert cfg.draft_steps == 8
        assert cfg.draft_guidance_scale == 1.0

    def test_low_res_strategy(self):
        cfg = build_coarse_to_fine_config(
            enabled=True,
            draft_strategy=DraftStrategy.LOW_RES,
            refine_steps=50,
            refine_guidance_scale=4.0,
        )
        assert cfg.draft_steps == 50  # 同步数
        assert cfg.draft_guidance_scale == 4.0


class TestGenerateCoarseToFine:
    @pytest.mark.asyncio
    async def test_disabled_skips_draft(self, tmp_path):
        """disabled config: 直接精修,跳过草稿。"""
        calls: list[dict] = []

        async def mock_gen_fn(**kwargs):
            calls.append(kwargs)
            path = Path(kwargs["output_path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("mock_video")
            return path

        cfg = build_coarse_to_fine_config(enabled=False)
        result = await generate_coarse_to_fine(
            prompt="test prompt",
            output_dir=tmp_path,
            gen_fn=mock_gen_fn,
            config=cfg,
            shot_id="s01",
        )
        # 只调一次(精修),不调草稿
        assert len(calls) == 1
        assert result.draft_path is None
        assert result.refine_path is not None
        assert result.skipped_reason == "config.disabled"

    @pytest.mark.asyncio
    async def test_none_config_direct_refine(self, tmp_path):
        """config=None: 直接精修。"""
        calls: list[dict] = []

        async def mock_gen_fn(**kwargs):
            calls.append(kwargs)
            path = Path(kwargs["output_path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("mock_video")
            return path

        result = await generate_coarse_to_fine(
            prompt="test",
            output_dir=tmp_path,
            gen_fn=mock_gen_fn,
            config=None,
        )
        assert len(calls) == 1
        assert result.refine_path is not None

    @pytest.mark.asyncio
    async def test_draft_rejected_skips_refine(self, tmp_path):
        """draft_accept_fn 返回 False: 跳过精修。"""

        async def mock_gen_fn(**kwargs):
            path = Path(kwargs["output_path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("mock_draft")
            return path

        cfg = build_coarse_to_fine_config(
            enabled=True,
            draft_strategy=DraftStrategy.LOW_STEPS,
            draft_accept_fn=lambda _: False,
        )
        result = await generate_coarse_to_fine(
            prompt="test",
            output_dir=tmp_path,
            gen_fn=mock_gen_fn,
            config=cfg,
        )
        assert result.draft_path is not None
        assert result.draft_accepted is False
        assert result.refine_path is None
        assert result.skipped_reason == "draft_rejected"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CFG-Zero tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

from hevi.video.longcat.cfg_zero import (
    cfg_zero_scale,
    apply_cfg_zero,
    cfg_zero_noise_combine,
    GuidanceTracker,
    GuidanceStats,
    GuidanceConfig,
    recommend_guidance_scale,
)


class TestCfgZeroScale:
    def test_identical_vectors(self):
        """cond == uncond → st_star ≈ 1.0"""
        v = [1.0, 2.0, 3.0]
        st = cfg_zero_scale(v, v)
        assert abs(st - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        """正交向量 → st_star ≈ 0.0"""
        cond = [1.0, 0.0]
        uncond = [0.0, 1.0]
        st = cfg_zero_scale(cond, uncond)
        assert abs(st) < 1e-6

    def test_opposite_vectors(self):
        """反向向量 → st_star < 0"""
        cond = [1.0, 2.0, 3.0]
        uncond = [-1.0, -2.0, -3.0]
        st = cfg_zero_scale(cond, uncond)
        assert st < 0

    def test_scaled_uncond(self):
        """uncond = 2*cond → st_star ≈ 0.5"""
        cond = [1.0, 1.0, 1.0]
        uncond = [2.0, 2.0, 2.0]
        st = cfg_zero_scale(cond, uncond)
        # dot = 6, sq_norm = 12, st = 6/12 = 0.5
        assert abs(st - 0.5) < 1e-6

    def test_empty_vectors(self):
        st = cfg_zero_scale([], [])
        assert st == 1.0  # 默认值

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="长度不匹配"):
            cfg_zero_scale([1.0], [1.0, 2.0])

    def test_single_element(self):
        st = cfg_zero_scale([3.0], [2.0])
        # dot=6, sq_norm=4, st=6/4=1.5
        assert abs(st - 1.5) < 1e-6


class TestApplyCfgZero:
    def test_standard_formula(self):
        """验证 CFG-Zero 公式正确性。"""
        cond = [2.0, 4.0]
        uncond = [1.0, 2.0]
        # st_star = (2*1 + 4*2) / (1+4+eps) = 10/5 = 2.0
        result = apply_cfg_zero(cond, uncond, guidance_scale=4.0)
        # result[0] = 1*2.0 + 4*(2 - 1*2.0) = 2 + 0 = 2.0
        # result[1] = 2*2.0 + 4*(4 - 2*2.0) = 4 + 0 = 4.0
        assert abs(result[0] - 2.0) < 1e-6
        assert abs(result[1] - 4.0) < 1e-6

    def test_with_orthogonal(self):
        """正交时:st_star=0, result = scale * cond"""
        cond = [1.0, 0.0]
        uncond = [0.0, 1.0]
        result = apply_cfg_zero(cond, uncond, guidance_scale=4.0)
        # st_star=0, result = 0 + 4*(cond - 0) = 4*cond
        assert abs(result[0] - 4.0) < 1e-6
        assert abs(result[1] - 0.0) < 1e-6


class TestCfgZeroNoiseCombine:
    def test_cfg_zero_mode(self):
        cond = [2.0, 4.0]
        uncond = [1.0, 2.0]
        result = cfg_zero_noise_combine(cond, uncond, 4.0, use_cfg_zero=True)
        assert len(result) == 2

    def test_standard_cfg_mode(self):
        """标准 CFG: uncond + scale * (cond - uncond)"""
        cond = [2.0, 4.0]
        uncond = [1.0, 2.0]
        result = cfg_zero_noise_combine(cond, uncond, 4.0, use_cfg_zero=False)
        # result[0] = 1 + 4*(2-1) = 5
        # result[1] = 2 + 4*(4-2) = 10
        assert abs(result[0] - 5.0) < 1e-6
        assert abs(result[1] - 10.0) < 1e-6


class TestGuidanceTracker:
    def test_record_single_step(self):
        tracker = GuidanceTracker()
        stats = tracker.record(
            step=0,
            cond_noise=[2.0, 4.0],
            uncond_noise=[1.0, 2.0],
            guidance_scale=4.0,
        )
        assert stats.step == 0
        assert stats.guidance_scale == 4.0

    def test_history_accumulation(self):
        tracker = GuidanceTracker()
        tracker.record(0, [1.0, 0.0], [0.0, 1.0])
        tracker.record(1, [2.0, 0.0], [1.0, 0.0])
        assert len(tracker.history) == 2

    def test_mean_st_star(self):
        tracker = GuidanceTracker()
        tracker.record(0, [1.0, 1.0], [1.0, 1.0])  # st_star=1.0
        tracker.record(1, [1.0, 0.0], [0.0, 1.0])  # st_star≈0.0
        mean = tracker.mean_st_star
        assert 0.4 < mean < 0.6  # 平均 ≈ 0.5

    def test_mean_angle(self):
        tracker = GuidanceTracker()
        tracker.record(0, [1.0, 0.0], [1.0, 0.0])  # 0°
        assert abs(tracker.mean_angle) < 1e-6

    def test_summary_empty(self):
        tracker = GuidanceTracker()
        s = tracker.summary()
        assert s["steps"] == 0

    def test_summary_populated(self):
        tracker = GuidanceTracker()
        tracker.record(0, [2.0, 4.0], [1.0, 2.0], 4.0)
        s = tracker.summary()
        assert s["steps"] == 1
        assert "mean_st_star" in s
        assert "min_st_star" in s
        assert "strengths" in s

    def test_guidance_strength_labels(self):
        tracker = GuidanceTracker()
        # 强引导(orthogonal → st_star≈0)
        stats = tracker.record(0, [1.0, 0.0], [0.0, 1.0])
        assert stats.guidance_strength in ("weak", "moderate", "strong", "extreme")


class TestGuidanceConfig:
    def test_effective_scale_no_decay(self):
        cfg = GuidanceConfig(guidance_scale=4.0)
        assert cfg.effective_scale(0) == 4.0
        assert cfg.effective_scale(100) == 4.0

    def test_effective_scale_with_decay(self):
        cfg = GuidanceConfig(
            guidance_scale=4.0,
            scale_decay_start_step=10,
            scale_decay_factor=0.9,
        )
        assert cfg.effective_scale(5) == 4.0   # 未开始衰减
        assert cfg.effective_scale(10) == 4.0   # 起始步
        assert cfg.effective_scale(11) < 4.0    # 开始衰减
        # step 11: 4.0 * 0.9^1 = 3.6
        assert abs(cfg.effective_scale(11) - 3.6) < 1e-6

    def test_st_star_bounds(self):
        cfg = GuidanceConfig(st_star_min=-1.0, st_star_max=1.5)
        assert cfg.st_star_min == -1.0
        assert cfg.st_star_max == 1.5


class TestRecommendGuidanceScale:
    def test_no_history_returns_default(self):
        assert recommend_guidance_scale(None, 4.0, "balanced") == 4.0
        assert recommend_guidance_scale([], 4.0, "balanced") == 4.0

    def test_balanced_default(self):
        assert recommend_guidance_scale(None, 4.0, "balanced") == 4.0

    def test_high_adherence_default(self):
        assert recommend_guidance_scale(None, 4.0, "high_adherence") == 6.0

    def test_creative_default(self):
        assert recommend_guidance_scale(None, 4.0, "creative") == 2.5

    def test_high_st_star_increases_scale(self):
        """高 st_star(同向)→ 需要更强引导"""
        history = [0.8, 0.9, 0.85]
        result = recommend_guidance_scale(history, 4.0, "high_adherence")
        assert result > 4.0

    def test_low_st_star_decreases_scale(self):
        """低 st_star(差异大)→ 可以弱化引导"""
        history = [0.1, 0.05, 0.08]
        result = recommend_guidance_scale(history, 4.0, "creative")
        assert result < 4.0


class TestGuidanceStats:
    def test_strength_weak(self):
        stats = GuidanceStats(
            step=0, st_star=0.9, guidance_scale=4.0,
            cond_norm=1.0, uncond_norm=1.0, angle_degrees=10.0,
        )
        assert stats.guidance_strength == "weak"

    def test_strength_strong(self):
        stats = GuidanceStats(
            step=0, st_star=0.15, guidance_scale=4.0,
            cond_norm=1.0, uncond_norm=1.0, angle_degrees=80.0,
        )
        assert stats.guidance_strength == "strong"

    def test_strength_extreme(self):
        stats = GuidanceStats(
            step=0, st_star=-0.5, guidance_scale=4.0,
            cond_norm=1.0, uncond_norm=1.0, angle_degrees=170.0,
        )
        assert stats.guidance_strength == "extreme"
