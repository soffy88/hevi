"""Long-running video generation profiles and admission plans."""

from hevi.layer4_legacy.longvideo.omodul_impl.runtime import (
    compile_longvideo_plan,
    longvideo_capabilities,
)
from hevi.layer4_legacy.longvideo.oprim_impl.contracts import LongVideoRequest

__all__ = ["LongVideoRequest", "compile_longvideo_plan", "longvideo_capabilities"]
