"""导演层薄转发 —— 机位过渡视频。"""

from enum import Enum

from hevi.layer4_legacy.script2video.oprim_impl.transition_prompt import build_transition_prompt
from hevi.layer4_legacy.script2video.oskill_impl.transition_video import (
    generate_all_transitions,
    generate_transition_video,
)
from hevi.script2video.schemas import TransitionResult, TransitionSpec


class TransitionStrategy(str, Enum):
    """导演层转场策略枚举(ViMax 对接面,produce_v2 的参数类型)。

    成员值是导演/API 层口径的策略名,与 script2video schemas 的
    TransitionStrategyName 字面量同义(xfade ↔ xfade_fallback)。
    因继承 str,VIDEO_GEN/MORPH 与 schemas/legacy 实现中的同名字符串
    比较相等,可直接喂给 TransitionSpec.strategy。
    """

    VIDEO_GEN = "video_gen"  # 用视频生成模型生成过渡(最佳质量,最贵)
    MORPH = "morph"  # 帧插值 morph(中等质量,便宜)
    XFADE_FALLBACK = "xfade"  # FFmpeg xfade(兜底,最便宜)


__all__ = [
    "TransitionResult",
    "TransitionSpec",
    "TransitionStrategy",
    "build_transition_prompt",
    "generate_all_transitions",
    "generate_transition_video",
]
