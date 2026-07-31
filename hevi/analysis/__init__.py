"""hevi 视频分析模块 —— 参考视频拆解、转录、场景检测、帧采样。

对标 OpenMontage 的 tools/analysis/(transcriber/scene_detect/frame_sampler/video_understand)。
"""

from hevi.analysis.reference_video import (
    ReferenceAnalysis,
    analyze_reference_video,
)
from hevi.analysis.scene_detect import detect_scenes
from hevi.analysis.transcribe import transcribe_video

__all__ = [
    "ReferenceAnalysis",
    "analyze_reference_video",
    "detect_scenes",
    "transcribe_video",
]
