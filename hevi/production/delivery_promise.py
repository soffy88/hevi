"""交付承诺分类器 —— 制片启动前锁定「这单承诺交付什么」。

对标 OpenMontage lib/delivery_promise.py(3O 内化, 差距 B 级补面):
最致命的失败模式是**静默降级** —— 承诺运动主导(motion_led), 最后
却用静帧幻灯片交差, 用户不知情。本模块在提案期把承诺类型定死并锁定,
合成阶段若兑现不了必须停下来问, 而不是偷偷换货。

与 hevi/production/delivery_gate.py 关系:
delivery_gate 是**成片侧**合同(ffprobe 探测 + 残镜/抄图/微动降级拦截);
本模块是**提案侧**合同(承诺类型 → 切点合规前门 validate_cuts)。
两者互补: 先用 classify_from_brief 定承诺, 合成后用 validate_cuts
校验切点, 出片后再过 delivery_gate。

全部为纯函数 + 显式数据, 零媒体解码依赖。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class PromiseType(Enum):
    MOTION_LED = "motion_led"
    SOURCE_LED = "source_led"
    DATA_EXPLAINER = "data_explainer"
    TEACHER_EXPLAINER = "teacher_explainer"
    SCREEN_DEMO = "screen_demo"
    AVATAR_PRESENTER = "avatar_presenter"
    HYBRID = "hybrid"
    LOCALIZATION = "localization"


# 每类承诺的合规规则 —— 什么能换、什么不能换。
PROMISE_RULES: dict[str, dict[str, Any]] = {
    "motion_led": {
        "still_fallback_allowed": False,
        "requires_video_generation": True,
        "min_motion_ratio": 0.7,
        "description": "成片质量靠真实运动: 生成视频/素材/动画, 不是 Remotion 幻灯片。",
    },
    "source_led": {
        "still_fallback_allowed": True,
        "requires_video_generation": False,
        "min_motion_ratio": 0.3,
        "description": "用户素材是主媒介, 生成资产只补缺口。",
    },
    "data_explainer": {
        "still_fallback_allowed": True,
        "requires_video_generation": False,
        "min_motion_ratio": 0.0,
        "description": "数据可视化与解说, 动效优先但图片可接受。",
    },
    "teacher_explainer": {
        "still_fallback_allowed": True,
        "requires_video_generation": False,
        "min_motion_ratio": 0.0,
        "description": "教育内容, 清晰度优先于场面。",
    },
    "screen_demo": {
        "still_fallback_allowed": True,
        "requires_video_generation": False,
        "min_motion_ratio": 0.0,
        "description": "录屏/产品演示, 可读性优先于电影感。",
    },
    "avatar_presenter": {
        "still_fallback_allowed": False,
        "requires_video_generation": True,
        "min_motion_ratio": 0.3,
        "description": "AI 数字人/口播, 主讲人必须是真的视频。",
    },
    "hybrid": {
        "still_fallback_allowed": True,
        "requires_video_generation": False,
        "min_motion_ratio": 0.2,
        "description": "用户素材 + 生成内容 + 图形的混合。",
    },
    "localization": {
        "still_fallback_allowed": True,
        "requires_video_generation": False,
        "min_motion_ratio": 0.0,
        "description": "译制/配音已有视频, 保源片节奏与清晰度。",
    },
}

# 幻灯片式语法(有转场但**不是**真实运动)。
_SLIDE_GRAMMAR_TYPES = frozenset({
    "text_card", "stat_card", "chart", "bar_chart",
    "line_chart", "pie_chart", "kpi_grid", "comparison",
    "progress", "callout",
})
# 真实运动来源。
_REAL_MOTION_TYPES = frozenset({"video", "animation", "avatar"})
_VIDEO_EXTS = frozenset({"mp4", "mov", "webm", "avi", "mkv"})


@dataclass
class DeliveryPromise:
    """已分类的交付承诺。motion_required / source_required 由分类器定死。"""

    promise_type: PromiseType
    motion_required: bool
    source_required: bool
    tone_mode: str          # "cinematic" | "educational" | "corporate" | "playful" | "raw"
    quality_floor: str      # "draft" | "presentable" | "broadcast"
    approved_fallback: str | None = None  # "animatic" | "still_led" | None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["promise_type"] = self.promise_type.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeliveryPromise:
        return cls(
            promise_type=PromiseType(data["promise_type"]),
            motion_required=bool(data.get("motion_required", False)),
            source_required=bool(data.get("source_required", False)),
            tone_mode=str(data.get("tone_mode", "corporate")),
            quality_floor=str(data.get("quality_floor", "presentable")),
            approved_fallback=data.get("approved_fallback"),
        )

    def get_rules(self) -> dict[str, Any]:
        return PROMISE_RULES.get(self.promise_type.value, {})

    def validate_cuts(self, cuts: list[dict[str, Any]]) -> dict[str, Any]:
        """校验切点列表是否兑现承诺。

        Returns:
            {valid, violations[], motion_ratio, motion_cuts, slide_cuts, still_cuts}
        只有真实视频/动画/数字人才算 motion; 图表/文本卡是「动效幻灯片」, 不算。
        """
        rules = self.get_rules()
        violations: list[str] = []

        if not cuts:
            return {"valid": False, "violations": ["无切点"], "motion_ratio": 0.0,
                    "motion_cuts": 0, "slide_cuts": 0, "still_cuts": 0}

        motion_cuts = slide_cuts = still_cuts = 0
        for cut in cuts:
            source = str(cut.get("source", ""))
            cut_type = str(cut.get("type", ""))
            ext = source.rsplit(".", 1)[-1].lower() if "." in source else ""

            if ext in _VIDEO_EXTS or cut_type in _REAL_MOTION_TYPES:
                motion_cuts += 1
            elif cut_type in _SLIDE_GRAMMAR_TYPES:
                slide_cuts += 1
            else:
                still_cuts += 1

        total = motion_cuts + slide_cuts + still_cuts
        motion_ratio = motion_cuts / total if total else 0.0

        min_ratio = rules.get("min_motion_ratio", 0.0)
        if self.motion_required and motion_ratio < min_ratio:
            violations.append(
                f"运动比 {motion_ratio:.0%} 低于 {self.promise_type.value} 下限 "
                f"{min_ratio:.0%}; {motion_cuts}/{total} 切点有真实运动 "
                f"({slide_cuts} 为动效幻灯片, 不计入 motion)。"
            )

        non_motion = slide_cuts + still_cuts
        if (
            not rules.get("still_fallback_allowed", True)
            and non_motion > total * 0.5
            and self.approved_fallback != "still_led"
        ):
            violations.append(
                f"{self.promise_type.value} 不允许静帧降级, 但 {non_motion}/{total} "
                f"切点是非运动(静帧 + 动效幻灯片)。须用户批准 'still_led' 或补运动内容。"
            )

        return {
            "valid": not violations,
            "violations": violations,
            "motion_ratio": round(motion_ratio, 3),
            "motion_cuts": motion_cuts,
            "slide_cuts": slide_cuts,
            "still_cuts": still_cuts,
        }


def classify_from_brief(
    pipeline_type: str,
    user_intent: dict[str, Any] | None = None,
) -> DeliveryPromise:
    """从管线类型 + 用户意图分类交付承诺(提案 director 可再精化)。

    Args:
        pipeline_type: 管线 manifest 名(cinematic / animated-explainer / ...)。
        user_intent: 键含 motion_required / has_footage / tone / quality / platform。
    """
    user_intent = user_intent or {}
    pipeline_defaults: dict[str, PromiseType] = {
        "cinematic": PromiseType.MOTION_LED,
        "animated-explainer": PromiseType.DATA_EXPLAINER,
        "animation": PromiseType.MOTION_LED,
        "talking-head": PromiseType.AVATAR_PRESENTER,
        "avatar-spokesperson": PromiseType.AVATAR_PRESENTER,
        "screen-demo": PromiseType.SCREEN_DEMO,
        "hybrid": PromiseType.HYBRID,
        "localization-dub": PromiseType.LOCALIZATION,
        "podcast-repurpose": PromiseType.SOURCE_LED,
        "clip-factory": PromiseType.SOURCE_LED,
    }

    promise_type = pipeline_defaults.get(pipeline_type, PromiseType.HYBRID)

    # 意图键显式 False 才降级; None/缺省视为未指定(保持管线默认)。
    if user_intent.get("motion_required") is False and promise_type == PromiseType.MOTION_LED:
        promise_type = PromiseType.HYBRID

    source_required = bool(user_intent.get("has_footage", False))
    if source_required and promise_type not in (PromiseType.SOURCE_LED, PromiseType.LOCALIZATION):
        promise_type = PromiseType.SOURCE_LED

    motion_required = bool(
        user_intent.get("motion_required")
        if user_intent.get("motion_required") is not None
        else promise_type in (PromiseType.MOTION_LED, PromiseType.AVATAR_PRESENTER)
    )

    return DeliveryPromise(
        promise_type=promise_type,
        motion_required=motion_required,
        source_required=source_required,
        tone_mode=str(user_intent.get("tone", "corporate")),
        quality_floor=str(user_intent.get("quality", "presentable")),
    )


__all__ = [
    "PROMISE_RULES",
    "DeliveryPromise",
    "PromiseType",
    "classify_from_brief",
]
