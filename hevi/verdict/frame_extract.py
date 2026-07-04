"""帧抽取 —— 从候选视频(shot_XXXX_vN.mp4)取一张代表帧供审片/嵌入。

3O §C4 依赖:omodul 的 `consistency_fn` 收到的 `candidate_frames` 是 **.mp4**,不是图。
用 PyAV(自带 ffmpeg 库,不依赖系统 ffmpeg 二进制 —— 本环境 `shutil.which("ffmpeg")` 为空)
解码取中间帧。输入若已是图片则原样返回。
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


class FrameExtractError(Exception):
    """抽帧失败。"""


def extract_representative_frame(source: Path | str, out_path: Path | str) -> Path:
    """取一张代表帧写到 out_path,返回其路径。

    - source 已是图片 → 直接返回其路径(不复制)。
    - source 是视频 → PyAV 解码,seek 到中点取一帧存 PNG。
    抛 FrameExtractError:解码失败/无视频流/PyAV 缺失。
    """
    src = Path(source)
    if src.suffix.lower() in _IMAGE_SUFFIXES:
        return src
    if not src.exists():
        raise FrameExtractError(f"source not found: {src}")

    try:
        import av  # PyAV
    except ImportError as e:  # pragma: no cover - env guard
        raise FrameExtractError(f"需要 PyAV 抽帧: {e}") from e

    out = Path(out_path)
    try:
        with av.open(str(src)) as container:
            if not container.streams.video:
                raise FrameExtractError(f"no video stream: {src}")
            stream = container.streams.video[0]
            # seek 到中点(有时长信息时),让代表帧更贴镜头内容而非首帧黑场。
            if stream.duration and stream.time_base:
                mid = int((float(stream.duration * stream.time_base) / 2) / stream.time_base)
                try:
                    container.seek(mid, stream=stream)
                except Exception:  # seek 失败退化为首帧
                    pass
            for frame in container.decode(video=0):
                frame.to_image().save(out)
                return out
        raise FrameExtractError(f"no decodable frame: {src}")
    except FrameExtractError:
        raise
    except Exception as e:
        raise FrameExtractError(f"decode failed for {src}: {e}") from e
