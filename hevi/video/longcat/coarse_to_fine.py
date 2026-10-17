"""渐进生成 (Coarse-to-Fine) — LongCat-Video 两阶段策略适配。

LongCat-Video 的生成策略:
  Stage 1 (coarse): 低分辨率(480p) + 少步数(8 steps) → 快速草稿
  Stage 2 (fine):   高分辨率(720p) + 全步数(50 steps) + refinement LoRA → 精修

核心机制:先花少量算力验证构图/动作,确认后再花大算力渲染。
Hevi 侧适配:wan_local 两档分辨率 + 步数差异化,云端用不同 quality_profile。

LongCat 原始代码路径(参考):
  run_demo_long_video.py:
    stage1: generate_vc(resolution='480p', num_inference_steps=50, guidance_scale=4.0)
    distill: generate_vc(num_inference_steps=16, use_distill=True, guidance_scale=1.0)
    refine: generate_refine(stage1_video=stage1, spatial_refine_only=False)
      → refinement_lora + enable_bsa() + 720p
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)

__all__ = [
    "DraftStrategy",
    "CoarseToFineConfig",
    "CoarseToFineResult",
    "build_coarse_to_fine_config",
    "generate_coarse_to_fine",
    "compute_draft_steps",
    "select_draft_resolution",
]

# 类型:异步生成函数签名 (与 wan_local_generate / gen_fn 一致)
GenFn = Callable[..., Awaitable[Path]]


class DraftStrategy(StrEnum):
    """草稿策略。

    low_steps  — 同分辨率少步数(LongCat distill 模式:8-16 steps)
    low_res    — 同步数低分辨率(LongCat coarse 模式:480p → 720p)
    both       — 少步数 + 低分辨率(最快草稿,质量损失最大)
    """

    LOW_STEPS = "low_steps"
    LOW_RES = "low_res"
    BOTH = "both"


@dataclass(frozen=True)
class CoarseToFineConfig:
    """渐进生成配置。"""

    enabled: bool = False
    draft_strategy: DraftStrategy = DraftStrategy.LOW_STEPS

    # 草稿参数
    draft_steps: int = 8
    draft_resolution: tuple[int, int] = (480, 832)  # (H, W) 480p
    draft_guidance_scale: float = 1.0  # LongCat distill 模式用 1.0

    # 精修参数
    refine_steps: int = 50
    refine_resolution: tuple[int, int] = (720, 1280)  # (H, W) 720p
    refine_guidance_scale: float = 4.0

    # 草稿确认回调:None=自动继续(两阶段都跑);
    # callable(draft_path) -> bool = 人审/自动QC后决定是否继续精修
    draft_accept_fn: Callable[[Path], bool] | None = None

    @property
    def speedup_ratio(self) -> float:
        """草稿相对于精修的理论加速比(步数比 × 分辨率面积比)。"""
        step_ratio = self.draft_steps / max(self.refine_steps, 1)
        area_ratio = (self.draft_resolution[0] * self.draft_resolution[1]) / max(
            self.refine_resolution[0] * self.refine_resolution[1], 1
        )
        return 1.0 / max(step_ratio * area_ratio, 0.01)


@dataclass
class CoarseToFineResult:
    """渐进生成结果。"""

    draft_path: Path | None = None
    refine_path: Path | None = None
    draft_accepted: bool = True
    skipped_reason: str | None = None
    config: CoarseToFineConfig | None = None


def compute_draft_steps(
    refine_steps: int,
    strategy: DraftStrategy = DraftStrategy.LOW_STEPS,
    min_steps: int = 4,
) -> int:
    """根据精修步数计算草稿步数。

    LongCat distill: refine_steps=50 → draft=8/16;
    LongCat 标准: refine_steps=50 → draft=50(同步,仅低分辨率)。
    """
    if strategy == DraftStrategy.LOW_RES:
        return refine_steps  # 同步数,仅降分辨率
    # low_steps / both: 取 refine_steps 的 16%
    draft = max(min_steps, int(refine_steps * 0.16))
    return draft


def select_draft_resolution(
    refine_resolution: tuple[int, int],
    strategy: DraftStrategy = DraftStrategy.LOW_STEPS,
) -> tuple[int, int]:
    """根据策略选择草稿分辨率。

    低分辨率档:refine 的 2/3(720p→480p)。
    """
    if strategy == DraftStrategy.LOW_STEPS:
        return refine_resolution  # 同分辨率
    # low_res / both: 降到 2/3
    h = int(refine_resolution[0] * 2 / 3)
    w = int(refine_resolution[1] * 2 / 3)
    # 对齐到 16 的倍数
    h = (h // 16) * 16
    w = (w // 16) * 16
    return (h, w)


def build_coarse_to_fine_config(
    enabled: bool = True,
    draft_strategy: DraftStrategy = DraftStrategy.LOW_STEPS,
    refine_steps: int = 50,
    refine_resolution: tuple[int, int] = (720, 1280),
    refine_guidance_scale: float = 4.0,
    draft_accept_fn: Callable[[Path], bool] | None = None,
) -> CoarseToFineConfig:
    """构造渐进生成配置。"""
    draft_steps = compute_draft_steps(refine_steps, draft_strategy)
    draft_res = select_draft_resolution(refine_resolution, draft_strategy)

    # LongCat distill 模式 guidance_scale=1.0; 标准 coarse 模式用 4.0
    draft_gs = 1.0 if draft_strategy in (DraftStrategy.LOW_STEPS, DraftStrategy.BOTH) else refine_guidance_scale

    return CoarseToFineConfig(
        enabled=enabled,
        draft_strategy=draft_strategy,
        draft_steps=draft_steps,
        draft_resolution=draft_res,
        draft_guidance_scale=draft_gs,
        refine_steps=refine_steps,
        refine_resolution=refine_resolution,
        refine_guidance_scale=refine_guidance_scale,
        draft_accept_fn=draft_accept_fn,
    )


async def generate_coarse_to_fine(
    *,
    prompt: str,
    output_dir: Path,
    gen_fn: GenFn,
    config: CoarseToFineConfig | None = None,
    negative_prompt: str = "",
    reference_image: Path | None = None,
    shot_id: str = "shot",
    extra_kwargs: dict[str, Any] | None = None,
) -> CoarseToFineResult:
    """执行两阶段渐进生成。

    Stage 1(draft):低参数快速生成草稿
      ↓ (draft_accept_fn 确认)
    Stage 2(refine):高参数精修(以 draft 末帧为条件,如有)

    Args:
        prompt: 文本提示
        output_dir: 输出目录
        gen_fn: 异步生成函数 (signature: *, prompt, output_path, size, frame_num, ...)
        config: 渐进配置(None=disabled,直接精修)
        negative_prompt: 负向提示
        reference_image: 参考图(两阶段共用)
        shot_id: 镜头标识(用于文件名)
        extra_kwargs: 传给 gen_fn 的额外参数

    Returns:
        CoarseToFineResult
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    extra = extra_kwargs or {}

    if config is None or not config.enabled:
        # 直接精修,跳过草稿
        refine_path = output_dir / f"{shot_id}_refine.mp4"
        await gen_fn(
            prompt=prompt,
            output_path=refine_path,
            size=config.refine_resolution if config else (720, 1280),
            frame_num=extra.get("frame_num", 81),
            negative_prompt=negative_prompt,
            reference_image=reference_image,
            **extra,
        )
        return CoarseToFineResult(
            refine_path=refine_path,
            draft_accepted=True,
            skipped_reason="config.disabled",
            config=config,
        )

    # ── Stage 1: Draft ──────────────────────────────────────────────────────
    draft_path = output_dir / f"{shot_id}_draft.mp4"
    logger.info(
        "coarse_to_fine: stage1 draft [%s steps=%d res=%s]",
        shot_id, config.draft_steps, config.draft_resolution,
    )
    try:
        await gen_fn(
            prompt=prompt,
            output_path=draft_path,
            size=config.draft_resolution,
            frame_num=extra.get("frame_num", 81),
            negative_prompt=negative_prompt,
            reference_image=reference_image,
            num_inference_steps=config.draft_steps,
            guidance_scale=config.draft_guidance_scale,
            **extra,
        )
    except Exception as e:
        logger.warning("coarse_to_fine: draft failed (%s), falling back to refine", e)
        draft_path = None

    # ── Draft 确认门 ─────────────────────────────────────────────────────────
    if draft_path is not None and config.draft_accept_fn is not None:
        accepted = config.draft_accept_fn(draft_path)
        if not accepted:
            logger.info("coarse_to_fine: draft rejected by accept_fn, skipping refine")
            return CoarseToFineResult(
                draft_path=draft_path,
                draft_accepted=False,
                skipped_reason="draft_rejected",
                config=config,
            )

    # ── Stage 2: Refine ──────────────────────────────────────────────────────
    refine_path = output_dir / f"{shot_id}_refine.mp4"

    # 如果 draft 成功,提取末帧作为 refine 的 reference_image(LongCat 模式)
    refine_ref_image = reference_image
    if draft_path is not None and draft_path.exists():
        from hevi.video.longcat.video_continuation import extract_video_last_frames

        draft_frames = await extract_video_last_frames(
            draft_path, output_dir / f"{shot_id}_draft_frames", num_frames=1
        )
        if draft_frames:
            refine_ref_image = draft_frames[0]
            logger.info(
                "coarse_to_fine: stage2 refine with draft last-frame as condition"
            )

    logger.info(
        "coarse_to_fine: stage2 refine [%s steps=%d res=%s]",
        shot_id, config.refine_steps, config.refine_resolution,
    )
    await gen_fn(
        prompt=prompt,
        output_path=refine_path,
        size=config.refine_resolution,
        frame_num=extra.get("frame_num", 81),
        negative_prompt=negative_prompt,
        reference_image=refine_ref_image,
        num_inference_steps=config.refine_steps,
        guidance_scale=config.refine_guidance_scale,
        **extra,
    )

    return CoarseToFineResult(
        draft_path=draft_path,
        refine_path=refine_path,
        draft_accepted=True,
        config=config,
    )
