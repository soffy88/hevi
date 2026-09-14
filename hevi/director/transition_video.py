"""导演层薄转发 —— 机位过渡视频。"""

from hevi.layer4_legacy.script2video.oprim_impl.transition_prompt import build_transition_prompt
from hevi.layer4_legacy.script2video.oskill_impl.transition_video import (
    generate_all_transitions,
    generate_transition_video,
)
from hevi.script2video.schemas import TransitionResult, TransitionSpec

__all__ = [
    "TransitionResult",
    "TransitionSpec",
    "build_transition_prompt",
    "generate_all_transitions",
    "generate_transition_video",
]
