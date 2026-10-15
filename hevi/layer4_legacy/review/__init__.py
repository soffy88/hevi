"""OMQUALITY 审片能力 —— 内化于 Layer 4 (3O), 与 enhance 同构。

渲染后自检 + 合成前门。三件套签名 ``(config, input_data, output_dir)`` 的事务落在
``omodul_impl``, 真实像素/音频/时间码量测落在 ``oprim_impl``, 纯算法(幻灯片风险
评分)落在 ``oskill_impl``。外观层 :mod:`hevi.review`。

与既有 ``hevi/video/quality_check.py`` 的关系:
quality_check 是**规格回归基线**(phash 连续性 + 响度 + ASR 字幕对齐), 依赖
faster-whisper; 本包是**审片门**(黑帧/破图/静音/字幕越界/幻灯片风险), 只依赖
ffmpeg/ffprobe, 可在没有 ASR 模型的机器上跑。两者互补, 不互相替代。
"""

from hevi.layer4_legacy.review.omodul_impl.review_workflow import (
    REVIEW_OPS,
    ReviewUnavailable,
    review_finished_video_workflow,
)

__all__ = [
    "REVIEW_OPS",
    "ReviewUnavailable",
    "review_finished_video_workflow",
]
