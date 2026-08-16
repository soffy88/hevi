"""产品宣传片八阶段工作流 —— 产品简报→styleframe→镜头映射→分镜→采集→实现→声音→终检
(3O 内化 Phase C,来源 video-shotcraft pipeline.md)。

八个阶段,方向性问题不进昂贵的逐镜头阶段。本 workflow 是 skeleton:真实渲染
走 remotion_render_workflow;这里负责**制作计划**的确定性部分 —— 产品简报校验、
镜头卡映射(用 hevi/motion 配方卡)、节拍分析(BGM 给定)、声音设计构建、
判例库终检报告 —— 全链路可离线跑,渲染/采集是可选步骤。

3O 归属(待上游): `omodul.promo_video_workflow`(三件套签名)。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.motion.motion_stylepack import MotionPreset, resolve_motion_preset
from hevi.motion.recipe_card import ShotRecipeCard, build_seed_library
from hevi.motion.sound_design import (
    SfxPin,
    SoundDesign,
    pick_sound_vocabulary,
)
from hevi.verdict.aesthetic_canon import (
    build_self_check_report,
    default_canon,
)

logger = logging.getLogger(__name__)

STAGES: tuple[str, ...] = (
    "product_brief",
    "styleframe",
    "shot_mapping",
    "storyboard",
    "capture",
    "shot_impl",
    "sound_design",
    "final_review",
)


@dataclass
class PromoConfig:
    """宣传片配置。"""

    product_name: str
    target_duration_s: float = 30.0
    aspect: str = "16:9"
    fps: int = 30
    energy_axis: float = 0.0  # -1 沉稳 … +1 高能
    tone_axis: float = 0.0  # -1 严肃 … +1 活泼
    motion_preset_name: str | None = None
    bgm_path: Path | None = None
    piece_type: str = "product_promo"
    features: list[str] = field(default_factory=list)


@dataclass
class PromoInput:
    """输入:产品页面/素材(采集阶段)。"""

    page_url: str = ""
    product_shots: list[Path] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class PromoPlan:
    """八阶段计划(制作放行的中间表示)。"""

    stages_passed: list[str] = field(default_factory=list)
    motion_preset: MotionPreset | None = None
    shot_cards: list[ShotRecipeCard] = field(default_factory=list)
    sequence_plan: list[dict[str, object]] = field(default_factory=list)
    sound_design: SoundDesign | None = None
    beat_note: str = ""
    final_review: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "stages_passed": self.stages_passed,
            "motion_preset": self.motion_preset.name if self.motion_preset else None,
            "shot_cards": [c.name for c in self.shot_cards],
            "sequence_plan": self.sequence_plan,
            "sound_design": (
                {
                    "bgm_path": self.sound_design.bgm_path,
                    "sfx_pins": len(self.sound_design.sfx_pins),
                    "dual_delivery": self.sound_design.dual_delivery,
                }
                if self.sound_design
                else None
            ),
            "beat_note": self.beat_note,
            "final_review": self.final_review,
        }


def _estimate_shot_count(target_duration_s: float) -> int:
    """按目标时长估镜头数(每镜 ~3s,含转场)。"""
    return max(int(target_duration_s / 3.0), 1)


async def promo_video_workflow(
    config: PromoConfig,
    input_data: PromoInput,
    output_dir: Path,
    *,
    on_step: Any = None,
) -> dict[str, Any]:
    """八阶段骨架:确定性阶段全跑,采集/渲染按输入可选。

    Returns:
        {"status": "completed"|"failed", "plan": {...}, "report_path": ...}
    """
    _enabled_pillars = {"report", "cost", "decision_trail"}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    plan = PromoPlan()

    def _step(stage: str, pct: float) -> None:
        if callable(on_step):
            on_step({"stage": stage, "pct": pct})

    try:
        if not config.product_name.strip():
            return {"status": "failed", "error": "product_name required"}
        _step("product_brief", 10.0)
        plan.stages_passed.append("product_brief")

        # 阶段 1:视觉方向 —— 品牌→动效参数(来源:品牌→动效参数推导表)
        preset = resolve_motion_preset(
            energy_axis=config.energy_axis,
            tone_axis=config.tone_axis,
            name=config.motion_preset_name,
        )
        plan.motion_preset = preset
        _step("styleframe", 20.0)
        plan.stages_passed.append("styleframe")

        # 阶段 2-3:镜头映射 —— 序列模式(能量弧)分配预算,再逐槽位取卡
        # (Round 3:替换 naive 卡循环;分配纪律来自 shotcraft sequences/promo-energy-arc)。
        from hevi.motion.sequence import PROMO_ENERGY_ARC, plan_sequence

        library = build_seed_library()
        role_card: dict[str, str] = {
            "brand_open": "title-card-hold",
            "hero": "spotlight-hero-card",
            "feature": "deck-deal-flyin",
            "breath": "title-card-hold",
            "launch_peak": "outro-wordmark-settle",
        }
        planned = plan_sequence(
            PROMO_ENERGY_ARC,
            total_duration_s=config.target_duration_s,
            fps=config.fps,
            feature_count=max(len(config.features), 1),
        )
        cards: list[ShotRecipeCard] = []
        for shot in planned:
            card_name = role_card.get(shot.role, "title-card-hold")
            if card_name in library:
                cards.append(library[card_name])
        plan.shot_cards = cards
        plan.sequence_plan = [s.to_dict() for s in planned]
        _step("shot_mapping", 40.0)
        plan.stages_passed.append("shot_mapping")
        plan.stages_passed.append("storyboard")

        # 阶段 4-5:采集(可选)
        if input_data.page_url:
            plan.stages_passed.append("capture")
            plan.stages_passed.append("shot_impl")

        # 阶段 6:声音设计 —— BGM 先行 + 词汇表按片种
        vocab = pick_sound_vocabulary(config.piece_type)
        sfx_pins = [
            SfxPin(
                from_frame=i * int(preset.main_duration_frames * 1.5),
                src=f"{vocab[i % len(vocab)]}.wav",
                note="per-shot beat",
            )
            for i in range(len(cards))
        ]
        design = SoundDesign(
            bgm_path=str(config.bgm_path) if config.bgm_path else "",
            vocabulary=vocab,
            sfx_pins=sfx_pins,
        )
        plan.sound_design = design
        if config.bgm_path is not None:
            plan.beat_note = (
                "BGM 给定:渲染前先做节拍网格分析(见 hevi.motion.beat_sync),"
                "切点钉 beatF(n);配 BGM 终渲交付两版。"
            )
        else:
            plan.beat_note = "无 BGM:时间线按内容节奏排,不强行卡点(来源: music-beat-sync.md §0)。"
        _step("sound_design", 75.0)
        plan.stages_passed.append("sound_design")

        # 阶段 7:终检 —— 判例库自检报告(未执行阶段 = ?)
        canon = default_canon()
        review = build_self_check_report(canon, {})
        plan.final_review = review
        plan.stages_passed.append("final_review")

        report_path = output_dir / "promo_plan.json"
        report = {"status": "completed", "plan": plan.to_dict()}
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {"status": "completed", "plan": plan.to_dict(), "report_path": str(report_path)}
    except Exception as e:
        logger.exception("promo_video_workflow failed")
        return {"status": "failed", "error": str(e)}
