"""导演层薄转发 —— 角色三联画。实现在 hevi.layer4_legacy.script2video.oskill_impl。"""

from hevi.layer4_legacy.script2video.oskill_impl.portrait_triptych import (
    generate_all_portraits,
    generate_portrait_triptych,
    generate_portrait_view,
)
from hevi.script2video.schemas import CharacterPortrait, PortraitRegistry, PortraitView

__all__ = [
    "CharacterPortrait",
    "PortraitRegistry",
    "PortraitView",
    "generate_all_portraits",
    "generate_portrait_triptych",
    "generate_portrait_view",
]
