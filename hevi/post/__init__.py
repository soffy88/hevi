"""镜头级后处理(超分 / 插帧)—— 挂在 h3_local provider 出 raw 之后、verdict 之前。

不是第二条「出品旁路」:本包只做 raw → final 的确定性后处理工序,输入是单镜产物,
输出仍是单镜产物(路径语义不变),装配/裁决仍走 hevi 本体。
"""

from hevi.post.flashvsr import FlashVSRUnavailable, upscale_flashvsr
from hevi.post.pipeline import PostResult, run_post_pipeline
from hevi.post.rife_vs import RifeUnavailable, interpolate_rife

__all__ = [
    "FlashVSRUnavailable",
    "PostResult",
    "RifeUnavailable",
    "interpolate_rife",
    "run_post_pipeline",
    "upscale_flashvsr",
]
