"""hevi 合成/装配模块。

RFC-002 后已从死代码转为主链路: assembler(音频驱动时长 + xfade + loudnorm)、
subtitle_align(ASR 强制对齐字幕)、cover_extractor 均被 longvideo 编排调用。
"""

from hevi.assembly.aspect_ratio import AspectRatio
from hevi.assembly.assembler import ShotSegment, assemble_longvideo
from hevi.assembly.cover_extractor import extract_cover
from hevi.assembly.postprocess_service import postprocess_video
from hevi.assembly.subtitle_align import align_subtitles

__all__ = [
    "AspectRatio",
    "ShotSegment",
    "align_subtitles",
    "assemble_longvideo",
    "extract_cover",
    "postprocess_video",
]
