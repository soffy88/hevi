"""导演层薄转发 —— 机位过渡视频。"""

from hevi.script2video.oprim.transition_prompt import build_transition_prompt
from hevi.script2video.oskill.transition_video import (
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
